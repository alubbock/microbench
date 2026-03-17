"""microbench — thin public facade.

All implementation lives in the sub-packages:
  microbench.core      — MicroBenchBase, MicroBench, encoding, monitoring, contexts
  microbench.mixins    — MB* mixin classes
  microbench.outputs   — Output, FileOutput, RedisOutput, HttpOutput
  microbench.cli       — command-line interface

Import everything from here as usual::

    from microbench import MicroBench, MBHostInfo, FileOutput
"""

from microbench.core.bench import (  # noqa: F401
    MicroBench,
    MicroBenchBase,
    _active_bm_data,
    _run_id,
    summary,
)
from microbench.core.contexts import (  # noqa: F401
    _AsyncContextManagerRun,
    _ContextManagerRun,
    _TimingSection,
)
from microbench.core.encoding import (  # noqa: F401
    _UNENCODABLE_PLACEHOLDER_VALUE,
    JSONEncoder,
    JSONEncodeWarning,
)
from microbench.core.monitoring import _MonitorThread  # noqa: F401
from microbench.mixins.base import _UNSET, CLIArg  # noqa: F401
from microbench.mixins.call import MBFunctionCall, MBReturnValue  # noqa: F401
from microbench.mixins.gpu import MBNvidiaSmi  # noqa: F401
from microbench.mixins.profiling import MBLineProfiler, MBPeakMemory  # noqa: F401
from microbench.mixins.python import (  # noqa: F401
    MBCondaPackages,
    MBGlobalPackages,
    MBInstalledPackages,
    MBPythonInfo,
)
from microbench.mixins.system import (  # noqa: F401
    MBCgroupLimits,
    MBHostInfo,
    MBLoadedModules,
    MBSlurmInfo,
    MBWorkingDir,
)
from microbench.mixins.vcs import MBFileHash, MBGitInfo  # noqa: F401
from microbench.outputs.base import Output  # noqa: F401
from microbench.outputs.file import FileOutput  # noqa: F401
from microbench.outputs.http import HttpOutput  # noqa: F401
from microbench.outputs.redis import RedisOutput  # noqa: F401
from microbench.version import __version__  # noqa: F401

__all__ = [
    # Core
    'MicroBenchBase',
    'MicroBench',
    'summary',
    # Output sinks
    'Output',
    'FileOutput',
    'HttpOutput',
    'RedisOutput',
    # Mixin authoring
    'CLIArg',
    # Mixins
    'MBFunctionCall',
    'MBReturnValue',
    'MBPythonInfo',
    'MBHostInfo',
    'MBPeakMemory',
    'MBSlurmInfo',
    'MBLoadedModules',
    'MBWorkingDir',
    'MBCgroupLimits',
    'MBGitInfo',
    'MBFileHash',
    'MBGlobalPackages',
    'MBInstalledPackages',
    'MBCondaPackages',
    'MBLineProfiler',
    'MBNvidiaSmi',
    # JSON encoding
    'JSONEncoder',
    'JSONEncodeWarning',
]
