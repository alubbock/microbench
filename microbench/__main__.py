"""Command-line interface for microbench.

Run an external command and record benchmark metadata:

    python -m microbench [options] -- COMMAND [ARGS...]

Results are written in JSONL format to stdout (default) or a file with
--outfile. By default host-info, slurm-info, and loaded-modules are
included; use --mixin to override, --show-mixins to list all available.
"""

import argparse
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timezone


def _mb_name_to_cli(name):
    """Convert 'MBFooBar' -> 'foo-bar' (strip MB prefix, CamelCase to kebab-case)."""
    if name.startswith('MB'):
        name = name[2:]
    return re.sub(r'(?<=[a-z0-9])([A-Z])', r'-\1', name).lower()


def _get_mixin_map():
    """Return {cli_name: class} for all CLI-compatible mixins."""
    import microbench as _mb

    return {
        _mb_name_to_cli(name): getattr(_mb, name)
        for name in _mb.__all__
        if isinstance(getattr(_mb, name, None), type)
        and getattr(_mb, name).__dict__.get('cli_compatible', False)
    }


_DEFAULT_MIXINS = (
    'python-info',
    'host-info',
    'slurm-info',
    'loaded-modules',
    'working-dir',
)

_CAPTURE_CHOICES = ('capture', 'suppress')

# Seconds to wait after SIGTERM before sending SIGKILL on timeout.
_SIGTERM_GRACE_PERIOD = 5


def _make_mixin_type(mixin_map):
    """Return an argparse type function that normalises and validates mixin names."""

    def _parse(value):
        canonical = _mb_name_to_cli(value) if value.startswith('MB') else value
        if canonical not in mixin_map:
            valid = ', '.join(sorted(mixin_map))
            raise argparse.ArgumentTypeError(
                f'unknown mixin {value!r}. Available: {valid}'
            )
        return canonical

    return _parse


def _show_dry_run(args, cmd, mixin_names, mixin_map):
    """Print a summary of the resolved configuration and exit."""
    lines = ['Dry run — command will not be executed.\n']
    lines.append(f'  Command:    {" ".join(cmd)}')
    lines.append(f'  Output:     {args.outfile or "stdout"}')
    lines.append(f'  Mixins:     {", ".join(mixin_names) if mixin_names else "none"}')

    # Mixin-specific settings that were explicitly supplied on the command line.
    for name in mixin_names:
        for arg in getattr(mixin_map[name], 'cli_args', []):
            val = getattr(args, arg.dest, None)
            if val is not None:
                flag = arg.flags[0]
                val_str = (
                    ' '.join(str(v) for v in val) if isinstance(val, list) else val
                )
                lines.append(f'    {flag} {val_str}')

    iters = str(args.iterations)
    if args.warmup:
        iters += f' (+{args.warmup} warmup)'
    lines.append(f'  Iterations: {iters}')

    capture = [
        f for f, v in (('--stdout', args.stdout), ('--stderr', args.stderr)) if v
    ]
    if capture:
        lines.append(f'  Capture:    {" ".join(capture)}')

    if args.timeout is not None:
        grace = args.timeout_grace_period or _SIGTERM_GRACE_PERIOD
        lines.append(f'  Timeout:    {args.timeout}s (grace period: {grace}s)')

    if args.monitor_interval is not None:
        lines.append(f'  Monitor:    every {args.monitor_interval}s')

    if args.fields:
        lines.append(f'  Fields:     {", ".join(args.fields)}')

    print('\n'.join(lines))


def _show_mixins(mixin_map):
    """Print a table of available CLI-compatible mixins and their descriptions."""
    default_set = set(_DEFAULT_MIXINS)
    width = max(len(name) for name in mixin_map)
    arg_indent = ' ' * (4 + width + 2)
    print('Available mixins (* = included by default):\n')
    for name in sorted(mixin_map):
        cls = mixin_map[name]
        doc = (cls.__doc__ or '').strip()
        summary = doc.splitlines()[0] if doc else ''
        marker = '*' if name in default_set else ' '
        print(f'  {marker} {name:<{width}}  {summary}')
        for arg in getattr(cls, 'cli_args', []):
            flag = arg.flags[0]
            if arg.metavar:
                flag_display = (
                    f'{flag} {arg.metavar} [{arg.metavar} ...]'
                    if arg.nargs == '+'
                    else f'{flag} {arg.metavar}'
                )
            else:
                flag_display = flag
            print(f'{arg_indent}{flag_display}')


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
            # Prime the CPU counter with a short blocking interval so the
            # immediate first sample has a meaningful cpu_percent value.
            proc.cpu_percent(interval=0.1)
            while True:
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
                if self._stop.wait(self._interval):
                    break
        except psutil.NoSuchProcess:
            pass


def _positive_float(value):
    """Return an argparse type function that accepts positive floats."""
    try:
        fvalue = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f'{value!r} is not a number')
    if fvalue <= 0:
        raise argparse.ArgumentTypeError(f'must be > 0, got {fvalue}')
    return fvalue


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


def _build_parser(mixin_map):
    parser = argparse.ArgumentParser(
        prog='python -m microbench',
        description=(
            'Run an external command and record benchmark metadata to JSONL.\n\n'
            'By default captures host-info, slurm-info, and loaded-modules. '
            'Specifying --mixin replaces the defaults; use --show-mixins to '
            'list all available mixins. '
            'Metadata capture failures are recorded in call.capture_errors '
            'rather than aborting the run.'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    from microbench import __version__

    parser.add_argument(
        '--version',
        action='version',
        version=f'microbench {__version__}',
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
        nargs='+',
        dest='mixins',
        metavar='MIXIN',
        type=_make_mixin_type(mixin_map),
        help=(
            'One or more mixins to include. Replaces defaults when specified. '
            'Use --show-mixins to list available options. '
            'MB-prefixed names (e.g. MBHostInfo) are also accepted.'
        ),
    )
    parser.add_argument(
        '--show-mixins',
        action='store_true',
        help='List available mixins with descriptions and exit.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help=(
            'Print the resolved configuration (command, mixins, settings) '
            'and exit without running the command.'
        ),
    )
    mixin_scope = parser.add_mutually_exclusive_group()
    mixin_scope.add_argument(
        '--all',
        '-a',
        action='store_true',
        dest='all_mixins',
        help='Include all available mixins. Overrides --mixin.',
    )
    mixin_scope.add_argument(
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
        '--timeout',
        type=_positive_float,
        default=None,
        metavar='SECONDS',
        help=(
            'Send SIGTERM to the command after SECONDS seconds per iteration. '
            'If the process has not exited after an additional grace period '
            f'(default {_SIGTERM_GRACE_PERIOD}s, see --timeout-grace-period), '
            'sends SIGKILL. '
            'Timed-out iterations are recorded with call.timed_out = true.'
        ),
    )
    parser.add_argument(
        '--timeout-grace-period',
        type=_positive_float,
        default=None,
        metavar='SECONDS',
        help=(
            f'Seconds to wait after SIGTERM before sending SIGKILL. '
            f'Requires --timeout. Default: {_SIGTERM_GRACE_PERIOD}.'
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
    # Mixin-specific arguments, auto-discovered from cli_args on each mixin class.
    for cli_name, cls in sorted(mixin_map.items()):
        for arg in getattr(cls, 'cli_args', []):
            kwargs = {
                'dest': arg.dest,
                'default': None,
                'help': f'[{cli_name}] {arg.help}',
            }
            if arg.metavar is not None:
                kwargs['metavar'] = arg.metavar
            if arg.nargs is not None:
                kwargs['nargs'] = arg.nargs
            if arg.type is not str:
                kwargs['type'] = arg.type
            parser.add_argument(*arg.flags, **kwargs)
    return parser


def main(argv=None):
    mixin_map = _get_mixin_map()
    parser = _build_parser(mixin_map)
    args = parser.parse_args(argv)

    if args.show_mixins:
        _show_mixins(mixin_map)
        sys.exit(0)

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
        mixin_names = list(dict.fromkeys(args.mixins))
    else:
        mixin_names = list(_DEFAULT_MIXINS)

    # Validate: mixin-specific args require their mixin to be loaded.
    mixin_names_set = set(mixin_names)
    for cli_name, cls in mixin_map.items():
        if cli_name not in mixin_names_set:
            for arg in getattr(cls, 'cli_args', []):
                if getattr(args, arg.dest, None) is not None:
                    parser.error(
                        f'{arg.flags[0]}: the {cli_name!r} mixin is not loaded. '
                        f'Add it with --mixin {cli_name} or use --all.'
                    )

    mixins = [mixin_map[name] for name in mixin_names]

    extra_fields = {}
    for field in args.fields or []:
        if '=' not in field:
            parser.error(f'Invalid --field: {field!r}. Use KEY=VALUE.')
        k, v = field.split('=', 1)
        extra_fields[k] = v

    if args.timeout_grace_period is not None and args.timeout is None:
        parser.error('--timeout-grace-period requires --timeout.')

    if args.monitor_interval is not None:
        try:
            import psutil  # noqa: F401
        except ImportError:
            parser.error('--monitor-interval requires the "psutil" package.')

    if args.dry_run:
        _show_dry_run(args, cmd, mixin_names, mixin_map)
        sys.exit(0)

    from microbench import FileOutput, MicroBench

    class _MBSubprocessResult:
        def capture_subprocess_reset(self, bm_data):
            # Runs in pre_start_triggers: after warmup, before timed iterations.
            # Discard any warmup results so only timed iterations are recorded.
            self._subprocess_returncodes = []
            self._subprocess_stdout = []
            self._subprocess_stderr = []
            self._subprocess_monitor = []
            self._subprocess_timed_out = False
            self._subprocess_timed_phase = True

        def capturepost_subprocess_result(self, bm_data):
            call = bm_data.setdefault('call', {})
            call['invocation'] = 'CLI'
            call['command'] = self._subprocess_command
            call['returncode'] = self._subprocess_returncodes
            if self._subprocess_timed_out:
                call['timed_out'] = True
            if self._subprocess_stdout:
                call['stdout'] = self._subprocess_stdout
            if self._subprocess_stderr:
                call['stderr'] = self._subprocess_stderr
            if any(self._subprocess_monitor):
                call['monitor'] = self._subprocess_monitor

    BenchClass = type(
        'CLIBench',
        (MicroBench, _MBSubprocessResult, *mixins),
        {'capture_optional': True},
    )

    # Apply mixin-specific CLI arguments, using cli_defaults where not supplied.
    from microbench.mixins import _UNSET

    for name in mixin_names:
        for arg in getattr(mixin_map[name], 'cli_args', []):
            user_value = getattr(args, arg.dest, None)
            if user_value is not None:
                setattr(BenchClass, arg.dest, user_value)
            elif arg.cli_default is not _UNSET:
                setattr(
                    BenchClass,
                    arg.dest,
                    arg.cli_default(cmd)
                    if callable(arg.cli_default)
                    else arg.cli_default,
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
    bench._subprocess_timed_out = False
    bench._subprocess_timed_phase = False  # becomes True after warmup

    # Hold references to the real streams before any patching in tests.
    _real_stdout = sys.__stdout__
    _real_stderr = sys.__stderr__

    def run():
        capture_stdout = args.stdout in _CAPTURE_CHOICES
        capture_stderr = args.stderr in _CAPTURE_CHOICES
        monitor_interval = args.monitor_interval
        timeout = args.timeout

        if (
            not capture_stdout
            and not capture_stderr
            and monitor_interval is None
            and timeout is None
        ):
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

            timed_out = False
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                proc.terminate()
                try:
                    grace = args.timeout_grace_period or _SIGTERM_GRACE_PERIOD
                    proc.wait(timeout=grace)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()

            if monitor_thread is not None:
                monitor_thread.stop()
                monitor_thread.join()
                bench._subprocess_monitor.append(monitor_thread.samples)

            for t in threads:
                t.join()

        if timed_out and bench._subprocess_timed_phase:
            bench._subprocess_timed_out = True
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
