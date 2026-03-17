"""Compatibility shim — re-exports from microbench.core.encoding.

Direct imports from ``microbench._encoding`` still work but are deprecated.
Use ``from microbench import JSONEncoder, JSONEncodeWarning`` instead.
"""

import warnings as _warnings

_warnings.warn(
    'microbench._encoding is a private compatibility shim and will be removed '
    'in a future version. Import from microbench directly instead.',
    DeprecationWarning,
    stacklevel=2,
)

from microbench.core.encoding import (  # noqa: F401, E402
    _UNENCODABLE_PLACEHOLDER_VALUE,
    JSONEncoder,
    JSONEncodeWarning,
)
