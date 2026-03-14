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


def _get_mixin_map():
    """Return {name: class} for all CLI-compatible mixins."""
    import microbench as _mb

    return {
        name: getattr(_mb, name)
        for name in _mb.__all__
        if isinstance(getattr(_mb, name, None), type)
        and getattr(getattr(_mb, name), 'cli_compatible', False)
    }


_DEFAULT_MIXINS = ('MBHostInfo', 'MBSlurmInfo')

_CAPTURE_CHOICES = ('capture', 'suppress')


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
        '--iterations',
        '-n',
        type=int,
        default=1,
        metavar='N',
        help='Run the command N times, recording each duration. Defaults to 1.',
    )
    parser.add_argument(
        '--warmup',
        '-w',
        type=int,
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

    from microbench import FileOutput, MicroBench

    class _MBSubprocessResult:
        def capture_subprocess_reset(self, bm_data):
            # Runs in pre_start_triggers: after warmup, before timed iterations.
            # Discard any warmup results so only timed iterations are recorded.
            self._subprocess_returncodes = []
            self._subprocess_stdout = []
            self._subprocess_stderr = []

        def capturepost_subprocess_result(self, bm_data):
            bm_data['command'] = self._subprocess_command
            bm_data['returncode'] = self._subprocess_returncodes
            if self._subprocess_stdout:
                bm_data['stdout'] = self._subprocess_stdout
            if self._subprocess_stderr:
                bm_data['stderr'] = self._subprocess_stderr

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

    popen_kwargs = {}
    if args.stdout in _CAPTURE_CHOICES:
        popen_kwargs['stdout'] = subprocess.PIPE
    if args.stderr in _CAPTURE_CHOICES:
        popen_kwargs['stderr'] = subprocess.PIPE

    # Hold references to the real streams before any patching in tests.
    _real_stdout = sys.__stdout__
    _real_stderr = sys.__stderr__

    def run():
        result = subprocess.run(cmd, **popen_kwargs)
        bench._subprocess_returncodes.append(result.returncode)
        if args.stdout in _CAPTURE_CHOICES:
            out = result.stdout.decode(errors='replace') if result.stdout else ''
            bench._subprocess_stdout.append(out)
            if args.stdout == 'capture':
                _real_stdout.write(out)
        if args.stderr in _CAPTURE_CHOICES:
            err = result.stderr.decode(errors='replace') if result.stderr else ''
            bench._subprocess_stderr.append(err)
            if args.stderr == 'capture':
                _real_stderr.write(err)

    run.__name__ = os.path.basename(cmd[0])
    bench(run)()

    sys.exit(max(bench._subprocess_returncodes, default=0))


if __name__ == '__main__':
    main()
