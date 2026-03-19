"""Entry point for ``python -m microbench`` / ``microbench`` console script."""

import os
import subprocess
import sys
import threading

from microbench.cli.parser import (
    _CAPTURE_CHOICES,
    _SIGTERM_GRACE_PERIOD,
    _build_parser,
)
from microbench.cli.registry import MIXIN_REGISTRY
from microbench.cli.runner import _SubprocessMonitorThread

_DEFAULT_MIXINS = (
    'python-info',
    'host-info',
    'slurm-info',
    'loaded-modules',
    'working-dir',
    'resource-usage',
)


def _show_dry_run(args, cmd, mixin_names, mixin_map):
    """Print a summary of the resolved configuration and exit."""
    lines = ['Dry run — command will not be executed.\n']
    lines.append(f'  Command:    {" ".join(cmd)}')
    output_parts = []
    if args.outfile:
        output_parts.append(args.outfile)
    if args.http_output:
        output_parts.append(args.http_output)
    if args.redis_output:
        output_parts.append(f'redis:{args.redis_output}')
    lines.append(f'  Output:     {", ".join(output_parts) or "stdout"}')
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


def main(argv=None):
    mixin_map = MIXIN_REGISTRY
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
        expanded = []
        for name in args.mixins:
            if name == 'defaults':
                expanded.extend(_DEFAULT_MIXINS)
            else:
                expanded.append(name)
        mixin_names = list(dict.fromkeys(expanded))
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

    if args.http_output_headers is not None and args.http_output is None:
        parser.error('--http-output-header requires --http-output.')
    if args.http_output_method != 'POST' and args.http_output is None:
        parser.error('--http-output-method requires --http-output.')

    if args.redis_port != 6379 and args.redis_output is None:
        parser.error('--redis-port requires --redis-output.')
    if args.redis_db != 0 and args.redis_output is None:
        parser.error('--redis-db requires --redis-output.')
    if args.redis_password is not None and args.redis_output is None:
        parser.error('--redis-password requires --redis-output.')
    if args.redis_output:
        try:
            import redis  # noqa: F401
        except ImportError:
            parser.error(
                '--redis-output requires the "redis" package. '
                'Install it with: pip install redis'
            )

    if args.monitor_interval is not None:
        try:
            import psutil  # noqa: F401
        except ImportError:
            parser.error('--monitor-interval requires the "psutil" package.')

    if args.dry_run:
        _show_dry_run(args, cmd, mixin_names, mixin_map)
        sys.exit(0)

    from microbench import FileOutput, HttpOutput, MicroBench
    from microbench.mixins.base import _UNSET

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
            # Reset resource-usage accumulator (populated by run() per iteration).
            self._subprocess_resource_usage = []

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

    outputs = []
    if args.outfile:
        outputs.append(FileOutput(args.outfile))
    if args.http_output:
        http_headers = {}
        for h in args.http_output_headers or []:
            if ':' not in h:
                parser.error(f'--http-output-header: expected KEY:VALUE, got {h!r}')
            k, v = h.split(':', 1)
            http_headers[k.strip()] = v.strip()
        outputs.append(
            HttpOutput(
                args.http_output,
                headers=http_headers or None,
                method=args.http_output_method,
            )
        )
    if args.redis_output:
        from microbench import RedisOutput

        redis_kwargs = dict(
            host=args.redis_host, port=args.redis_port, db=args.redis_db
        )
        if args.redis_password is not None:
            redis_kwargs['password'] = args.redis_password
        outputs.append(RedisOutput(args.redis_output, **redis_kwargs))
    if not outputs:
        outputs.append(FileOutput(sys.stdout))

    bench = BenchClass(
        outputs=outputs,
        iterations=args.iterations,
        warmup=args.warmup,
        **extra_fields,
    )
    bench._subprocess_command = cmd
    bench._subprocess_returncodes = []
    bench._subprocess_stdout = []
    bench._subprocess_stderr = []
    bench._subprocess_monitor = []
    bench._subprocess_resource_usage = []
    bench._subprocess_timed_out = False
    bench._subprocess_timed_phase = False  # becomes True after warmup

    # Hold references to the real streams before any patching in tests.
    _real_stdout = sys.__stdout__
    _real_stderr = sys.__stderr__

    # Lazy import: resource module is POSIX-only.
    try:
        import resource as _resource
    except ImportError:
        _resource = None

    def run():
        capture_stdout = args.stdout in _CAPTURE_CHOICES
        capture_stderr = args.stderr in _CAPTURE_CHOICES
        monitor_interval = args.monitor_interval
        timeout = args.timeout

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

        proc = subprocess.Popen(cmd, **popen_kwargs)

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
        child_rusage = None

        if _resource is not None:
            # os.wait4() reaps the child and returns its exact per-child rusage
            # in a single syscall.  It must be called *instead* of proc.wait().
            #
            # Timeout handling: os.wait4() is a blocking call with no built-in
            # deadline.  We handle it by running wait4 in a daemon thread and
            # joining with a timeout.  If the join times out, we terminate/kill
            # the child, then block on wait4 (the child is now dying so this
            # completes quickly).
            _wait4_result = [None]  # [(pid, status, rusage)]
            _wait4_error = [None]

            def _do_wait4():
                try:
                    _wait4_result[0] = os.wait4(proc.pid, 0)
                except BaseException as exc:  # pragma: no cover - defensive
                    _wait4_error[0] = exc

            _wait4_thread = threading.Thread(target=_do_wait4, daemon=True)
            _wait4_thread.start()
            _wait4_thread.join(timeout=timeout)

            if _wait4_thread.is_alive():
                # Timed out — terminate/kill the child and wait for it to exit.
                timed_out = True
                proc.terminate()
                try:
                    grace = args.timeout_grace_period or _SIGTERM_GRACE_PERIOD
                    _wait4_thread.join(timeout=grace)
                except Exception:
                    pass
                if _wait4_thread.is_alive():
                    proc.kill()
                    _wait4_thread.join()  # child is dead; this will return quickly

            if _wait4_error[0] is not None:
                raise _wait4_error[0]

            if _wait4_result[0] is None:  # pragma: no cover - defensive
                raise RuntimeError('os.wait4() returned no child status')

            _, wait_status, raw_ru = _wait4_result[0]
            proc.returncode = os.waitstatus_to_exitcode(wait_status)
            child_rusage = raw_ru
        else:
            # No resource module available: use proc.wait() with optional timeout.
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

        # Accumulate per-iteration resource usage (only during timed phase).
        if bench._subprocess_timed_phase and child_rusage is not None:
            from microbench.mixins.system import _rusage_from_wait4

            bench._subprocess_resource_usage.append(_rusage_from_wait4(child_rusage))

    run.__name__ = os.path.basename(cmd[0])
    bench(run)()

    sys.exit(next((code for code in bench._subprocess_returncodes if code != 0), 0))
