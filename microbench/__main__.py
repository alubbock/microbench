"""Entry point for ``python -m microbench``.

Delegates to :func:`microbench.cli.main.main`.

Private symbols (_get_mixin_map, _SubprocessMonitorThread) are re-exported
here for backwards compatibility with existing code that imports them from
this module. They will be removed in a future version.
"""

from microbench.cli.main import main  # noqa: F401
from microbench.cli.registry import MIXIN_REGISTRY as _MIXIN_REGISTRY  # noqa: F401
from microbench.cli.runner import _SubprocessMonitorThread  # noqa: F401


def _get_mixin_map():
    """Backwards-compat shim — returns MIXIN_REGISTRY dict."""
    return dict(_MIXIN_REGISTRY)


if __name__ == '__main__':
    main()
