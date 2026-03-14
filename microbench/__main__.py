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
        def capturepost_subprocess_result(self, bm_data):
            bm_data['command'] = self._subprocess_command
            bm_data['returncode'] = self._subprocess_returncode

    BenchClass = type(
        'CLIBench',
        (MicroBench, _MBSubprocessResult, *mixins),
        {'capture_optional': True},
    )

    output = FileOutput(args.outfile) if args.outfile else FileOutput(sys.stdout)
    bench = BenchClass(outputs=[output], **extra_fields)
    bench._subprocess_command = cmd

    def run():
        result = subprocess.run(cmd)
        bench._subprocess_returncode = result.returncode

    run.__name__ = os.path.basename(cmd[0])
    bench(run)()

    sys.exit(bench._subprocess_returncode or 0)


if __name__ == '__main__':
    main()
