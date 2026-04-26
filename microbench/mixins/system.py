"""System-info mixins.

Classes: MBHostInfo, MBWorkingDir, MBSlurmInfo, MBCgroupLimits, MBLoadedModules,
MBResourceUsage.
"""

import os
import socket
import sys

try:
    import psutil
except ImportError:
    psutil = None

try:
    import resource as _resource
except ImportError:
    _resource = None


class MBHostInfo:
    """Capture hostname, operating system, and (optionally) CPU and RAM info.

    Always records ``host.hostname`` and ``host.os`` using only the standard
    library. When `psutil <https://pypi.org/project/psutil/>`_ is installed,
    also records ``host.cpu_cores_logical``, ``host.cpu_cores_physical``, and
    ``host.ram_total`` (bytes). The psutil fields are silently omitted when
    psutil is not available — no error or warning is raised.

    This mixin supersedes the former ``MBHostCpuCores`` and ``MBHostRamTotal``
    mixins, which have been removed.

    Note:
        CLI compatible.
    """

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

    Note:
        CLI compatible.
    """

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

    Note:
        CLI compatible.
    """

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

    Note:
        CLI compatible.
    """

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

    Note:
        CLI compatible.
    """

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


def _rusage_to_dict(ru, *, include_maxrss=True):
    """Convert a ``struct_rusage`` to a plain dict with normalised fields.

    ``maxrss`` is normalised to bytes: macOS already reports bytes; Linux
    reports kilobytes and is multiplied by 1024.

    Pass ``include_maxrss=False`` to omit ``maxrss`` (used in Python API mode
    where ``RUSAGE_SELF.maxrss`` is a lifetime process high-water mark and
    cannot meaningfully isolate a single function call).
    """
    d = {
        'utime': ru.ru_utime,
        'stime': ru.ru_stime,
        'minflt': ru.ru_minflt,
        'majflt': ru.ru_majflt,
        'inblock': ru.ru_inblock,
        'oublock': ru.ru_oublock,
        'nvcsw': ru.ru_nvcsw,
        'nivcsw': ru.ru_nivcsw,
    }
    if include_maxrss:
        maxrss = ru.ru_maxrss
        if sys.platform == 'linux':
            maxrss *= 1024
        d['maxrss'] = maxrss
    return d


def _rusage_from_wait4(raw_ru):
    """Convert the raw rusage object returned by ``os.wait4()`` to a dict.

    ``os.wait4()`` returns a ``resource.struct_rusage``-compatible object
    whose ``ru_maxrss`` already reflects **only that child process** — no
    cumulative HWM subtraction is needed.  ``maxrss`` is normalised to bytes
    using the same platform rule as ``_rusage_to_dict``.
    """
    maxrss = raw_ru.ru_maxrss
    if sys.platform == 'linux':
        maxrss *= 1024
    return {
        'utime': raw_ru.ru_utime,
        'stime': raw_ru.ru_stime,
        'maxrss': maxrss,
        'minflt': raw_ru.ru_minflt,
        'majflt': raw_ru.ru_majflt,
        'inblock': raw_ru.ru_inblock,
        'oublock': raw_ru.ru_oublock,
        'nvcsw': raw_ru.ru_nvcsw,
        'nivcsw': raw_ru.ru_nivcsw,
    }


def _rusage_delta(before, after):
    return {
        'utime': after['utime'] - before['utime'],
        'stime': after['stime'] - before['stime'],
        'minflt': after['minflt'] - before['minflt'],
        'majflt': after['majflt'] - before['majflt'],
        'inblock': after['inblock'] - before['inblock'],
        'oublock': after['oublock'] - before['oublock'],
        'nvcsw': after['nvcsw'] - before['nvcsw'],
        'nivcsw': after['nivcsw'] - before['nivcsw'],
    }


class MBResourceUsage:
    """Capture POSIX ``getrusage()`` data for the benchmarked code.

    Records CPU time, page faults, block I/O operations, and context switches.
    Results are stored as a **list** of dicts, one entry per timed iteration
    in both CLI and Python API mode, aligning index-for-index with
    ``call.durations`` and ``call.returncode``.

    **Modes**

    - *CLI mode* (subprocess): on POSIX, uses ``os.wait4()`` to capture the
      exact rusage of each child process as reported by the kernel — one entry
      per timed iteration, aligned with ``call.durations`` and
      ``call.returncode``.

    - *Python API mode* (function): uses ``RUSAGE_SELF`` — one entry per
      timed iteration (matching ``call.durations`` index-for-index), each a
      before/after delta around that single call.  ``maxrss`` is **always
      omitted** in this mode because ``RUSAGE_SELF.maxrss`` is a lifetime
      process high-water mark; it reflects peak usage since program start,
      not just the decorated function.  Use ``MBPeakMemory`` for per-call
      peak RSS in Python API mode.

    On non-POSIX platforms where the ``resource`` module is unavailable, this
    mixin omits the ``resource_usage`` key entirely.

    Output key: ``resource_usage`` (list of dicts)

    Fields per entry (CLI mode with ``os.wait4()`` — the common POSIX case):

    - ``utime``: user CPU time consumed by the child (seconds, float)
    - ``stime``: system CPU time consumed by the child (seconds, float)
    - ``maxrss``: peak RSS of the child in bytes (int) — see platform notes
    - ``minflt``: minor page faults (int)
    - ``majflt``: major page faults (int)
    - ``inblock``: block input operations (int) — see platform notes
    - ``oublock``: block output operations (int) — see platform notes
    - ``nvcsw``: voluntary context switches (int)
    - ``nivcsw``: involuntary context switches (int)

    Fields per entry (Python API mode): all of the above **except** ``maxrss``.

    **Platform notes**

    *maxrss* (CLI mode with ``os.wait4()``):
        Reported directly by the kernel as the child's own peak RSS.  Exact
        and per-child regardless of iteration count or warmup.

    *inblock / oublock* (macOS):
        These counters are almost always zero on macOS regardless of actual
        I/O performed.  The macOS unified buffer cache charges block I/O to
        the *first* process that touches each page; subsequent reads and
        writes to cached pages are not counted.  In practice nearly all file
        I/O is served from the cache and the counters never increment.  This
        is a kernel accounting limitation, not a microbench bug.  On Linux,
        ``inblock`` and ``oublock`` increment only for I/O that bypasses the
        page cache (i.e. cold-cache reads or ``O_DIRECT`` writes); warm-cache
        reads also show zero.

    *majflt* (macOS):
        Major page faults are rare on macOS because the unified buffer cache
        handles most page-in activity.  Zero is normal.

    *utime / stime / minflt / nvcsw / nivcsw*:
        These are the most reliable fields across both Linux and macOS and
        should be non-zero for any non-trivial workload.

    Example output (CLI mode, 2 iterations)::

        {
            "resource_usage": [
                {
                    "utime": 0.123456,
                    "stime": 0.012345,
                    "maxrss": 10485760,
                    "minflt": 512,
                    "majflt": 0,
                    "inblock": 0,
                    "oublock": 0,
                    "nvcsw": 3,
                    "nivcsw": 1
                },
                {
                    "utime": 0.118000,
                    "stime": 0.011000,
                    "maxrss": 10485760,
                    "minflt": 498,
                    "majflt": 0,
                    "inblock": 0,
                    "oublock": 0,
                    "nvcsw": 2,
                    "nivcsw": 1
                }
            ]
        }

    Note:
        CLI compatible.
    """

    def capture_resource_usage(self, bm_data):
        """Initialise resource-usage accumulator before all iterations."""
        if _resource is None:
            return
        if hasattr(self, '_subprocess_command'):
            # CLI mode: accumulator populated by run() in main.py.
            self._subprocess_resource_usage = []
        else:
            # Python API mode: per-iteration list populated by pre/post_run_triggers.
            self._rusage_iter_entries = []

    def pre_run_triggers(self, bm_data):
        if _resource is not None and not hasattr(self, '_subprocess_command'):
            self._rusage_iter_before = _rusage_to_dict(
                _resource.getrusage(_resource.RUSAGE_SELF), include_maxrss=False
            )

    def post_run_triggers(self, bm_data):
        if _resource is not None and not hasattr(self, '_subprocess_command'):
            after = _rusage_to_dict(
                _resource.getrusage(_resource.RUSAGE_SELF), include_maxrss=False
            )
            self._rusage_iter_entries.append(
                _rusage_delta(self._rusage_iter_before, after)
            )

    def capturepost_resource_usage(self, bm_data):
        """Write the resource_usage list to bm_data after all iterations."""
        if _resource is None:
            return
        if hasattr(self, '_subprocess_command'):
            # CLI mode: list already populated by run() in main.py.
            bm_data['resource_usage'] = list(
                getattr(self, '_subprocess_resource_usage', [])
            )
        else:
            # Python API mode: one entry per timed iteration.
            bm_data['resource_usage'] = list(getattr(self, '_rusage_iter_entries', []))
