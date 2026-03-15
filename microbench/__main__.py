"""Command-line interface for microbench.

Run an external command and record benchmark metadata:

    python -m microbench [options] -- COMMAND [ARGS...]

Results are written in JSONL format to stdout (default) or a file with
--outfile. By default MBHostInfo and MBSlurmInfo are included; use
--mixin to override.
"""

import argparse
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone


def _get_mixin_map():
    """Return {name: class} for all CLI-compatible mixins."""
    import microbench as _mb

    return {
        name: getattr(_mb, name)
        for name in _mb.__all__
        if isinstance(getattr(_mb, name, None), type)
        and getattr(getattr(_mb, name), 'cli_compatible', False)
    }


_DEFAULT_MIXINS = ('MBHostInfo', 'MBSlurmInfo', 'MBLoadedModules')

_CAPTURE_CHOICES = ('capture', 'suppress')


class _SubprocessMonitorThread(threading.Thread):
    """Background thread that samples CPU and RSS of a child process."""

    def __init__(self, pid, interval):
        super().__init__(daemon=True)
        self._pid = pid
        self._interval = interval
        self._stop = threading.Event()
        self.samples = []

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            import psutil
        except ImportError:
            return
        try:
            proc = psutil.Process(self._pid)
            # First call primes the CPU percentage counter; result is always 0.0.
            proc.cpu_percent(interval=None)
            while not self._stop.wait(self._interval):
                try:
                    self.samples.append(
                        {
                            'timestamp': datetime.now(timezone.utc),
                            'cpu_percent': proc.cpu_percent(interval=None),
                            'rss_bytes': proc.memory_info().rss,
                        }
                    )
                except psutil.NoSuchProcess:
                    break
        except psutil.NoSuchProcess:
            pass


def _int_at_least(minimum):
    """Return an argparse type function that accepts integers >= minimum."""

    def _parse(value):
        try:
            ivalue = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f'{value!r} is not an integer')
        if ivalue < minimum:
            raise argparse.ArgumentTypeError(f'must be >= {minimum}, got {ivalue}')
        return ivalue

    return _parse


def _build_parser(mixin_names):
    parser = argparse.ArgumentParser(
        prog='python -m microbench',
        description=(
            'Run an external command and record benchmark metadata to JSONL.\n\n'
            'By default captures MBHostInfo and MBSlurmInfo. '
            'Specifying --mixin replaces the defaults. '
            'Metadata capture failures are recorded in mb_capture_errors '
            'rather than aborting the run.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        '--outfile',
        '-o',
        metavar='FILE',
        help='Append results to FILE (JSONL format). Defaults to stdout.',
    )
    parser.add_argument(
        '--mixin',
        '-m',
        action='append',
        dest='mixins',
        metavar='MIXIN',
        choices=sorted(mixin_names),
        help=(
            'Mixin to include. Replaces defaults when specified. '
            'Can be repeated. Available: %(choices)s.'
        ),
    )
    parser.add_argument(
        '--all',
        '-a',
        action='store_true',
        dest='all_mixins',
        help='Include all available mixins. Overrides --mixin.',
    )
    parser.add_argument(
        '--no-mixin',
        action='store_true',
        dest='no_mixins',
        help='Disable all mixins including defaults. Overrides --mixin.',
    )
    parser.add_argument(
        '--iterations',
        '-n',
        type=_int_at_least(1),
        default=1,
        metavar='N',
        help='Run the command N times, recording each duration. Defaults to 1.',
    )
    parser.add_argument(
        '--warmup',
        '-w',
        type=_int_at_least(0),
        default=0,
        metavar='N',
        help='Run N unrecorded warm-up calls before timing begins. Defaults to 0.',
    )
    parser.add_argument(
        '--stdout',
        nargs='?',
        const='capture',
        default=None,
        metavar='suppress',
        help=(
            'Capture stdout into the record (one entry per iteration). '
            'Output is still shown on the terminal by default; '
            'use --stdout=suppress to hide it.'
        ),
    )
    parser.add_argument(
        '--stderr',
        nargs='?',
        const='capture',
        default=None,
        metavar='suppress',
        help=(
            'Capture stderr into the record (one entry per iteration). '
            'Output is still shown on the terminal by default; '
            'use --stderr=suppress to hide it.'
        ),
    )
    parser.add_argument(
        '--monitor-interval',
        type=_int_at_least(1),
        default=None,
        metavar='SECONDS',
        help=(
            'Sample child process CPU usage and RSS every SECONDS seconds, '
            'recording results in subprocess_monitor. Requires psutil. '
            'Monitoring is disabled when this flag is omitted.'
        ),
    )
    parser.add_argument(
        '--field',
        '-f',
        action='append',
        dest='fields',
        metavar='KEY=VALUE',
        help='Extra metadata field added to every record. Can be repeated.',
    )
    parser.add_argument(
        'command',
        nargs=argparse.REMAINDER,
        help='Command to benchmark (use -- to separate from microbench options).',
    )
    return parser


def main(argv=None):
    mixin_map = _get_mixin_map()
    parser = _build_parser(mixin_map)
    args = parser.parse_args(argv)

    cmd = args.command
    if cmd and cmd[0] == '--':
        cmd = cmd[1:]
    if not cmd:
        parser.error('No command specified.')

    for flag, val in (('--stdout', args.stdout), ('--stderr', args.stderr)):
        if val not in (None,) + _CAPTURE_CHOICES:
            parser.error(
                f'{flag}: invalid value {val!r}. '
                f'Use {flag} to capture or {flag}=suppress to capture and suppress.'
            )

    if args.all_mixins:
        mixin_names = sorted(mixin_map)
    elif args.no_mixins:
        mixin_names = []
    elif args.mixins is not None:
        mixin_names = args.mixins
    else:
        mixin_names = list(_DEFAULT_MIXINS)
    mixins = [mixin_map[name] for name in mixin_names]

    extra_fields = {}
    for field in args.fields or []:
        if '=' not in field:
            parser.error(f'Invalid --field: {field!r}. Use KEY=VALUE.')
        k, v = field.split('=', 1)
        extra_fields[k] = v

    if args.monitor_interval is not None:
        try:
            import psutil  # noqa: F401
        except ImportError:
            parser.error('--monitor-interval requires the "psutil" package.')

    from microbench import FileOutput, MicroBench

    class _MBSubprocessResult:
        def capture_subprocess_reset(self, bm_data):
            # Runs in pre_start_triggers: after warmup, before timed iterations.
            # Discard any warmup results so only timed iterations are recorded.
            self._subprocess_returncodes = []
            self._subprocess_stdout = []
            self._subprocess_stderr = []
            self._subprocess_monitor = []
            self._subprocess_timed_phase = True

        def capturepost_subprocess_result(self, bm_data):
            bm_data['command'] = self._subprocess_command
            bm_data['returncode'] = self._subprocess_returncodes
            if self._subprocess_stdout:
                bm_data['stdout'] = self._subprocess_stdout
            if self._subprocess_stderr:
                bm_data['stderr'] = self._subprocess_stderr
            if any(self._subprocess_monitor):
                bm_data['subprocess_monitor'] = self._subprocess_monitor

    BenchClass = type(
        'CLIBench',
        (MicroBench, _MBSubprocessResult, *mixins),
        {'capture_optional': True},
    )

    output = FileOutput(args.outfile) if args.outfile else FileOutput(sys.stdout)
    bench = BenchClass(
        outputs=[output],
        iterations=args.iterations,
        warmup=args.warmup,
        **extra_fields,
    )
    bench._subprocess_command = cmd
    bench._subprocess_returncodes = []
    bench._subprocess_stdout = []
    bench._subprocess_stderr = []
    bench._subprocess_monitor = []
    bench._subprocess_timed_phase = False  # becomes True after warmup

    # Hold references to the real streams before any patching in tests.
    _real_stdout = sys.__stdout__
    _real_stderr = sys.__stderr__

    def run():
        capture_stdout = args.stdout in _CAPTURE_CHOICES
        capture_stderr = args.stderr in _CAPTURE_CHOICES
        monitor_interval = args.monitor_interval

        if not capture_stdout and not capture_stderr and monitor_interval is None:
            result = subprocess.run(cmd)
            bench._subprocess_returncodes.append(result.returncode)
            return

        # Use Popen so we have the PID (needed for monitoring) and can read
        # stdout/stderr pipes in real time when capture is requested.
        stdout_chunks = []
        stderr_chunks = []

        def _reader(pipe, chunks, real_stream, passthrough):
            for line in pipe:
                chunk = line.decode(errors='replace')
                chunks.append(chunk)
                if passthrough:
                    real_stream.write(chunk)
                    real_stream.flush()

        popen_kwargs = {}
        if capture_stdout:
            popen_kwargs['stdout'] = subprocess.PIPE
        if capture_stderr:
            popen_kwargs['stderr'] = subprocess.PIPE

        with subprocess.Popen(cmd, **popen_kwargs) as proc:
            threads = []
            if capture_stdout:
                t = threading.Thread(
                    target=_reader,
                    args=(
                        proc.stdout,
                        stdout_chunks,
                        _real_stdout,
                        args.stdout == 'capture',
                    ),
                    daemon=True,
                )
                t.start()
                threads.append(t)
            if capture_stderr:
                t = threading.Thread(
                    target=_reader,
                    args=(
                        proc.stderr,
                        stderr_chunks,
                        _real_stderr,
                        args.stderr == 'capture',
                    ),
                    daemon=True,
                )
                t.start()
                threads.append(t)

            monitor_thread = None
            if monitor_interval is not None and bench._subprocess_timed_phase:
                monitor_thread = _SubprocessMonitorThread(proc.pid, monitor_interval)
                monitor_thread.start()

            proc.wait()

            if monitor_thread is not None:
                monitor_thread.stop()
                monitor_thread.join()
                bench._subprocess_monitor.append(monitor_thread.samples)

            for t in threads:
                t.join()

        bench._subprocess_returncodes.append(proc.returncode)
        if capture_stdout:
            bench._subprocess_stdout.append(''.join(stdout_chunks))
        if capture_stderr:
            bench._subprocess_stderr.append(''.join(stderr_chunks))

    run.__name__ = os.path.basename(cmd[0])
    bench(run)()

    sys.exit(max(bench._subprocess_returncodes, default=0))


if __name__ == '__main__':
    main()
