"""Compatibility shim — re-exports from microbench.outputs.*.

Direct imports from ``microbench._output`` still work but are deprecated.
Use ``from microbench import Output, FileOutput, RedisOutput, HttpOutput`` instead.
"""

import warnings as _warnings

_warnings.warn(
    'microbench._output is a private compatibility shim and will be removed '
    'in a future version. Import from microbench directly instead.',
    DeprecationWarning,
    stacklevel=2,
)

from microbench.outputs.base import Output  # noqa: E402, F401
from microbench.outputs.file import FileOutput  # noqa: E402, F401
from microbench.outputs.http import HttpOutput  # noqa: E402, F401
from microbench.outputs.redis import RedisOutput  # noqa: E402, F401
from microbench.outputs.utils import _flatten_dict  # noqa: E402, F401
