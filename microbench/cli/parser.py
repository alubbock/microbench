"""CLI argument parser for microbench."""

import argparse
import re

_SIGTERM_GRACE_PERIOD = 5
_CAPTURE_CHOICES = ('capture', 'suppress')


def _mb_name_to_cli(name):
    """Convert 'MBFooBar' -> 'foo-bar' (strip MB prefix, CamelCase to kebab-case)."""
    if name.startswith('MB'):
        name = name[2:]
    return re.sub(r'(?<=[a-z0-9])([A-Z])', r'-\1', name).lower()


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


def _build_parser(mixin_map):
    from microbench.version import __version__

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

    parser.add_argument(
        '--version',
        action='version',
        version=f'microbench {__version__}',
    )

    output_group = parser.add_argument_group('output')
    output_group.add_argument(
        '--outfile',
        '-o',
        metavar='FILE',
        help='Append results to FILE (JSONL format). Defaults to stdout.',
    )
    output_group.add_argument(
        '--http-output',
        metavar='URL',
        help=(
            'POST each record as JSON to URL. '
            'Can be combined with --outfile to write to both destinations.'
        ),
    )
    output_group.add_argument(
        '--http-output-header',
        metavar='KEY:VALUE',
        action='append',
        dest='http_output_headers',
        help=(
            'Extra HTTP header for --http-output (repeatable). '
            'Use for authentication, e.g. '
            '"Authorization:Bearer $TOKEN". '
            'Requires --http-output.'
        ),
    )
    output_group.add_argument(
        '--http-output-method',
        metavar='METHOD',
        default='POST',
        help='HTTP method for --http-output. Defaults to POST. Requires --http-output.',
    )
    output_group.add_argument(
        '--redis-output',
        metavar='KEY',
        help=(
            'RPUSH each record as JSON to a Redis list at KEY. '
            'Can be combined with --outfile or --http-output. '
            'Requires the "redis" package (pip install redis).'
        ),
    )
    output_group.add_argument(
        '--redis-host',
        metavar='HOST',
        default='localhost',
        help='Redis server hostname for --redis-output (default: localhost).',
    )
    output_group.add_argument(
        '--redis-port',
        metavar='PORT',
        type=int,
        default=6379,
        help=(
            'Redis server port for --redis-output (default: 6379). '
            'Requires --redis-output.'
        ),
    )
    output_group.add_argument(
        '--redis-db',
        metavar='DB',
        type=int,
        default=0,
        help=(
            'Redis database index for --redis-output (default: 0). '
            'Requires --redis-output.'
        ),
    )
    output_group.add_argument(
        '--redis-password',
        metavar='PASSWORD',
        default=None,
        help='Redis AUTH password for --redis-output. Requires --redis-output.',
    )

    mixin_group = parser.add_argument_group('mixins')
    mixin_group.add_argument(
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
    mixin_group.add_argument(
        '--show-mixins',
        action='store_true',
        help='List available mixins with descriptions and exit.',
    )
    mixin_scope = mixin_group.add_mutually_exclusive_group()
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

    exec_group = parser.add_argument_group('execution')
    exec_group.add_argument(
        '--iterations',
        '-n',
        type=_int_at_least(1),
        default=1,
        metavar='N',
        help='Run the command N times, recording each duration. Defaults to 1.',
    )
    exec_group.add_argument(
        '--warmup',
        '-w',
        type=_int_at_least(0),
        default=0,
        metavar='N',
        help='Run N unrecorded warm-up calls before timing begins. Defaults to 0.',
    )
    exec_group.add_argument(
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
    exec_group.add_argument(
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
    exec_group.add_argument(
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
    exec_group.add_argument(
        '--timeout-grace-period',
        type=_positive_float,
        default=None,
        metavar='SECONDS',
        help=(
            f'Seconds to wait after SIGTERM before sending SIGKILL. '
            f'Requires --timeout. Default: {_SIGTERM_GRACE_PERIOD}.'
        ),
    )
    exec_group.add_argument(
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
    exec_group.add_argument(
        '--dry-run',
        action='store_true',
        help=(
            'Print the resolved configuration (command, mixins, settings) '
            'and exit without running the command.'
        ),
    )
    exec_group.add_argument(
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
    mixin_opts_group = parser.add_argument_group('mixin options')
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
            mixin_opts_group.add_argument(*arg.flags, **kwargs)
    return parser
