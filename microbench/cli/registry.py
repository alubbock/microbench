"""Explicit CLI mixin registry.

Replaces the old ``__all__``-scanning approach in ``_get_mixin_map()``.
Each entry maps a kebab-case CLI name to the mixin class. Add new
CLI-compatible mixins here — no other changes needed.
"""

from microbench.mixins.gpu import MBNvidiaSmi
from microbench.mixins.profiling import MBPeakMemory
from microbench.mixins.python import MBCondaPackages, MBInstalledPackages, MBPythonInfo
from microbench.mixins.system import (
    MBCgroupLimits,
    MBHostInfo,
    MBLoadedModules,
    MBSlurmInfo,
    MBWorkingDir,
)
from microbench.mixins.vcs import MBFileHash, MBGitInfo

# Maps kebab-case CLI name → mixin class.
# Only CLI-compatible mixins (noted in their docstring) should be listed here.
MIXIN_REGISTRY: dict = {
    'python-info': MBPythonInfo,
    'host-info': MBHostInfo,
    'slurm-info': MBSlurmInfo,
    'loaded-modules': MBLoadedModules,
    'working-dir': MBWorkingDir,
    'cgroup-limits': MBCgroupLimits,
    'git-info': MBGitInfo,
    'file-hash': MBFileHash,
    'installed-packages': MBInstalledPackages,
    'conda-packages': MBCondaPackages,
    'peak-memory': MBPeakMemory,
    'nvidia-smi': MBNvidiaSmi,
}
