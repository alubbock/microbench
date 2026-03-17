"""Shared mixin utilities: CLIArg descriptor and internal sentinels."""

_UNSET = object()


class CLIArg:
    """Declares a CLI argument that sets a mixin attribute.

    Attach a list of ``CLIArg`` instances to a mixin class as ``cli_args``
    to expose configurable attributes through ``python -m microbench``.
    Arguments are added to the parser automatically; no changes to the CLI
    code are needed when adding new configurable mixins.

    Args:
        flags: Flag strings for the argument, e.g. ``['--git-repo']``.
        dest: Mixin attribute name to set, e.g. ``'git_repo'``.
        help: Help text shown in ``--help`` and ``--show-mixins``.
        metavar: Display name for the value in help text.
        type: Callable to convert the raw string. Defaults to ``str``.
        nargs: Number of arguments (e.g. ``'+'`` for one or more).
        cli_default: Default when the flag is not given on the CLI.
            If callable, called with the command list (``cmd``) to
            compute the default at run time (e.g. ``lambda cmd:
            [cmd[0]]``). Use ``_UNSET`` (the default) to fall back to
            the mixin's own Python-API default logic instead.
    """

    def __init__(
        self,
        flags,
        dest,
        help,
        *,
        metavar=None,
        type=str,
        nargs=None,
        cli_default=_UNSET,
    ):
        self.flags = flags
        self.dest = dest
        self.help = help
        self.metavar = metavar
        self.type = type
        self.nargs = nargs
        self.cli_default = cli_default
