"""Compatibility shim — re-exports from microbench.mixins.* and microbench.core.*.

Direct imports from ``microbench._mixins`` still work but are deprecated.
Use ``from microbench import MB*, CLIArg`` instead.
"""

import warnings as _warnings

_warnings.warn(
    'microbench._mixins is a private compatibility shim and will be removed '
    'in a future version. Import from microbench directly instead.',
    DeprecationWarning,
    stacklevel=2,
)

from microbench.core.monitoring import _MonitorThread  # noqa: E402, F401
from microbench.mixins.base import _UNSET, CLIArg  # noqa: E402, F401
from microbench.mixins.call import MBFunctionCall, MBReturnValue  # noqa: E402, F401
from microbench.mixins.gpu import MBNvidiaSmi  # noqa: E402, F401
from microbench.mixins.profiling import MBLineProfiler, MBPeakMemory  # noqa: E402, F401
from microbench.mixins.python import (  # noqa: E402, F401
    MBCondaPackages,
    MBGlobalPackages,
    MBInstalledPackages,
    MBPythonInfo,
)
from microbench.mixins.system import (  # noqa: E402, F401
    MBCgroupLimits,
    MBHostInfo,
    MBLoadedModules,
    MBSlurmInfo,
    MBWorkingDir,
)
from microbench.mixins.vcs import MBFileHash, MBGitInfo  # noqa: E402, F401
