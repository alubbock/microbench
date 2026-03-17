"""System-info mixins.

Classes: MBHostInfo, MBWorkingDir, MBSlurmInfo, MBCgroupLimits, MBLoadedModules.
"""

import os
import socket
import sys

try:
    import psutil
except ImportError:
    psutil = None


class MBHostInfo:
    """Capture hostname, operating system, and (optionally) CPU and RAM info.

    Always records ``host.hostname`` and ``host.os`` using only the standard
    library. When `psutil <https://pypi.org/project/psutil/>`_ is installed,
    also records ``host.cpu_cores_logical``, ``host.cpu_cores_physical``, and
    ``host.ram_total`` (bytes). The psutil fields are silently omitted when
    psutil is not available — no error or warning is raised.

    This mixin supersedes the former ``MBHostCpuCores`` and ``MBHostRamTotal``
    mixins, which have been removed.
    """

    cli_compatible = True

    def capture_hostname(self, bm_data):
        bm_data.setdefault('host', {})['hostname'] = socket.gethostname()

    def capture_os(self, bm_data):
        bm_data.setdefault('host', {})['os'] = sys.platform

    def capture_cpu_cores(self, bm_data):
        if psutil is None:
            return
        host = bm_data.setdefault('host', {})
        host['cpu_cores_logical'] = psutil.cpu_count(logical=True)
        host['cpu_cores_physical'] = psutil.cpu_count(logical=False)

    def capture_ram_total(self, bm_data):
        if psutil is None:
            return
        bm_data.setdefault('host', {})['ram_total'] = psutil.virtual_memory().total


class MBWorkingDir:
    """Capture the working directory at benchmark time.

    Records the current working directory as ``call.working_dir``. This is
    per-call data since the working directory can change between calls.
    """

    cli_compatible = True

    def capture_working_dir(self, bm_data):
        bm_data.setdefault('call', {})['working_dir'] = os.getcwd()


class MBSlurmInfo:
    """Capture all SLURM_* environment variables.

    Results are stored in the ``slurm`` field as a dict, with keys
    lowercased and the ``SLURM_`` prefix stripped. If no SLURM environment
    variables are set (e.g. running locally), ``slurm`` is an empty dict.

    Example output::

        {
            "slurm": {
                "job_id": "12345",
                "array_task_id": "3",
                "nodelist": "gpu-node-[01-04]",
                "cpus_per_task": "4"
            }
        }
    """

    cli_compatible = True

    def capture_slurm(self, bm_data):
        bm_data['slurm'] = {
            k[6:].lower(): v for k, v in os.environ.items() if k.startswith('SLURM_')
        }


class MBLoadedModules:
    """Capture loaded Lmod / Environment Modules.

    Reads the ``LOADEDMODULES`` environment variable set by both Lmod and
    Environment Modules and records the loaded modules as a dict mapping
    module name to version string. If no modules are loaded, or the
    benchmark is not running in a module-enabled environment,
    ``loaded_modules`` is an empty dict.

    Example output::

        {
            "loaded_modules": {
                "gcc": "12.2.0",
                "openmpi": "4.1.5",
                "python": "3.10.4"
            }
        }

    Module entries without a version (e.g. ``null``) are stored with an
    empty string as the version.
    """

    cli_compatible = True

    def capture_loaded_modules(self, bm_data):
        loaded = os.environ.get('LOADEDMODULES', '')
        modules = {}
        for entry in loaded.split(':'):
            entry = entry.strip()
            if not entry:
                continue
            name, _, version = entry.partition('/')
            modules[name] = version
        bm_data['loaded_modules'] = modules


def _read_cgroup_v2():
    """Read CPU quota and memory limit from a cgroup v2 hierarchy."""
    cgroup_path = None
    with open('/proc/self/cgroup') as f:
        for line in f:
            parts = line.strip().split(':', 2)
            if len(parts) == 3 and parts[0] == '0':
                cgroup_path = parts[2]
                break
    if not cgroup_path:
        return {}

    base = os.path.join('/sys/fs/cgroup', cgroup_path.lstrip('/'))
    cpu_cores = None
    memory_bytes = None

    cpu_max = os.path.join(base, 'cpu.max')
    if os.path.exists(cpu_max):
        with open(cpu_max) as f:
            parts = f.read().split()
        if len(parts) == 2 and parts[0] != 'max':
            cpu_cores = int(parts[0]) / int(parts[1])

    mem_max = os.path.join(base, 'memory.max')
    if os.path.exists(mem_max):
        with open(mem_max) as f:
            content = f.read().strip()
        if content != 'max':
            memory_bytes = int(content)

    return {
        'cpu_cores_limit': cpu_cores,
        'memory_bytes_limit': memory_bytes,
        'version': 2,
    }


def _read_cgroup_v1():
    """Read CPU quota and memory limit from a cgroup v1 hierarchy."""
    cpu_path = None
    memory_path = None
    with open('/proc/self/cgroup') as f:
        for line in f:
            parts = line.strip().split(':', 2)
            if len(parts) != 3:
                continue
            _, controllers, path = parts
            controllers_list = controllers.split(',')
            if 'cpu' in controllers_list and cpu_path is None:
                cpu_path = path
            if 'memory' in controllers_list and memory_path is None:
                memory_path = path

    cpu_cores = None
    memory_bytes = None

    if cpu_path is not None:
        quota_path = '/sys/fs/cgroup/cpu' + cpu_path + '/cpu.cfs_quota_us'
        period_path = '/sys/fs/cgroup/cpu' + cpu_path + '/cpu.cfs_period_us'
        if os.path.exists(quota_path) and os.path.exists(period_path):
            with open(quota_path) as f:
                quota = int(f.read().strip())
            with open(period_path) as f:
                period = int(f.read().strip())
            if quota != -1:
                cpu_cores = quota / period

    if memory_path is not None:
        limit_path = '/sys/fs/cgroup/memory' + memory_path + '/memory.limit_in_bytes'
        if os.path.exists(limit_path):
            with open(limit_path) as f:
                limit = int(f.read().strip())
            if limit < 2**62:
                memory_bytes = limit

    return {
        'cpu_cores_limit': cpu_cores,
        'memory_bytes_limit': memory_bytes,
        'version': 1,
    }


class MBCgroupLimits:
    """Capture CPU quota and memory limit from Linux cgroups.

    Works for SLURM jobs and Kubernetes pods (cgroup v1 and v2). Results
    are stored in the ``cgroups`` field as a dict containing:

    - ``cpu_cores_limit``: effective CPU parallelism as a float (quota ÷
      period), or ``None`` if unlimited or unavailable.
    - ``memory_bytes_limit``: memory limit in bytes as an int, or ``None``
      if unlimited or unavailable.
    - ``version``: ``1`` or ``2``.

    On non-Linux systems or when the cgroup filesystem is unavailable,
    ``cgroups`` is an empty dict.

    Note:
        ``cpu_cores_limit`` is derived from the cgroup CPU quota and period,
        so it represents effective CPU parallelism, not a physical core count.
        A SLURM job launched with ``--cpus-per-task=4`` will typically report
        ``cpu_cores_limit: 4.0``.

    Example output::

        {
            "cgroups": {
                "cpu_cores_limit": 4.0,
                "memory_bytes_limit": 17179869184,
                "version": 2
            }
        }
    """

    cli_compatible = True

    def capture_cgroup_limits(self, bm_data):
        if sys.platform != 'linux':
            bm_data['cgroups'] = {}
            return
        try:
            if os.path.exists('/sys/fs/cgroup/cgroup.controllers'):
                bm_data['cgroups'] = _read_cgroup_v2()
            else:
                bm_data['cgroups'] = _read_cgroup_v1()
        except (OSError, ValueError, ZeroDivisionError):
            bm_data['cgroups'] = {}
