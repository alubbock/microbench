import argparse
import base64
import inspect
import os
import pickle
import platform
import re
import shutil
import signal
import socket
import subprocess
import sys
import threading
import types
import warnings
from datetime import datetime

try:
    import line_profiler
except ImportError:
    line_profiler = None
try:
    import psutil
except ImportError:
    psutil = None
try:
    import numpy
except ImportError:
    numpy = None

from ._encoding import _UNENCODABLE_PLACEHOLDER_VALUE, JSONEncodeWarning

_UNSET = object()


def _resolve_cmd_path(cmd):
    """Resolve cmd[0] to an absolute file path for use as a hash target.

    Tries ``shutil.which`` first (handles bare command names like ``echo``
    by searching PATH), then falls back to checking whether the string is
    itself an existing file (handles relative and absolute paths that may
    not be executable). Returns a one-element list with the resolved path,
    or an empty list if the command cannot be resolved to a file.
    """
    import shutil

    path = cmd[0]
    resolved = shutil.which(path)
    if resolved:
        return [resolved]
    if os.path.isfile(path):
        return [path]
    return []


def _existing_file(value):
    """argparse type: accept an existing file path, reject directories."""
    if os.path.isdir(value):
        raise argparse.ArgumentTypeError(f'{value!r} is a directory')
    if not os.path.isfile(value):
        raise argparse.ArgumentTypeError(f'file not found: {value!r}')
    return value


def _existing_dir(value):
    """argparse type: accept an existing directory path."""
    if not os.path.isdir(value):
        raise argparse.ArgumentTypeError(f'directory not found: {value!r}')
    return value


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


class MBFunctionCall:
    """Capture function arguments and keyword arguments"""

    def capture_function_args_and_kwargs(self, bm_data):
        call = bm_data.setdefault('call', {})
        # Check all args are encodeable as JSON, then store the raw value
        call['args'] = []
        for i, v in enumerate(bm_data['_args']):
            try:
                self.to_json(v)
                call['args'].append(v)
            except TypeError:
                warnings.warn(
                    f'Function argument {i} is not JSON encodable (type: {type(v)}). '
                    'Extend JSONEncoder class to fix (see README).',
                    JSONEncodeWarning,
                )
                call['args'].append(_UNENCODABLE_PLACEHOLDER_VALUE)

        # Check all kwargs are encodeable as JSON, then store the raw value
        call['kwargs'] = {}
        for k, v in bm_data['_kwargs'].items():
            try:
                self.to_json(v)
                call['kwargs'][k] = v
            except TypeError:
                warnings.warn(
                    f'Function keyword argument "{k}" is not JSON encodable'
                    f' (type: {type(v)}). Extend JSONEncoder class to fix'
                    ' (see README).',
                    JSONEncodeWarning,
                )
                call['kwargs'][k] = _UNENCODABLE_PLACEHOLDER_VALUE


class MBReturnValue:
    """Capture the decorated function's return value"""

    pass


class MBPythonVersion:
    """Capture the Python version and location of the Python executable.

    .. deprecated::
        Use :class:`MBPythonInfo` instead. ``MBPythonVersion`` will be
        removed in a future release.
    """

    cli_compatible = True

    def capture_python_version(self, bm_data):
        bm_data['python_version'] = platform.python_version()

    def capture_python_executable(self, bm_data):
        bm_data['python_executable'] = sys.executable


class MBPythonInfo:
    """Capture the Python interpreter version, prefix, and executable path.

    Records a ``python`` dict with three keys:

    - ``version``: the Python version string (e.g. ``"3.12.4"``)
    - ``prefix``: ``sys.prefix`` — the environment root
    - ``executable``: ``sys.executable`` — the absolute interpreter path

    This mixin is included in :class:`MicroBench` by default (Python API)
    and in the CLI default mixin set. It supersedes :class:`MBPythonVersion`.
    """

    cli_compatible = True

    def capture_python_info(self, bm_data):
        python = bm_data.setdefault('python', {})
        python['version'] = platform.python_version()
        python['prefix'] = sys.prefix
        python['executable'] = sys.executable


class MBHostInfo:
    """Capture the hostname and operating system.

    Results are stored in the ``host`` dict with keys ``hostname`` and ``os``.
    """

    cli_compatible = True

    def capture_hostname(self, bm_data):
        bm_data.setdefault('host', {})['hostname'] = socket.gethostname()

    def capture_os(self, bm_data):
        bm_data.setdefault('host', {})['os'] = sys.platform


_microbench_dir = os.path.dirname(os.path.abspath(__file__))
_microbench_tests_dir = os.path.join(_microbench_dir, 'tests')


def _is_microbench_internal(filename):
    """True for source files inside the microbench package, excluding tests/."""
    abs_file = os.path.abspath(filename)
    if abs_file.startswith(_microbench_tests_dir + os.sep):
        return False
    return abs_file == _microbench_dir or abs_file.startswith(_microbench_dir + os.sep)


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


class MBWorkingDir:
    """Capture the working directory at benchmark time.

    Records the current working directory as ``call.working_dir``. This is
    per-call data since the working directory can change between calls.
    """

    cli_compatible = True

    def capture_working_dir(self, bm_data):
        bm_data.setdefault('call', {})['working_dir'] = os.getcwd()


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


class MBGitInfo:
    """Capture git repository information.

    Requires ``git`` ≥ 2.11 to be available on ``PATH``. Records the
    current repo directory, commit hash, branch name, and whether the
    working tree has uncommitted changes. Results are stored in the
    ``git`` field.

    By default inspects the repository containing the running script
    (``sys.argv[0]``), falling back to the shell's working directory
    when the script path is unavailable (e.g. interactive Python). Set
    ``git_repo`` explicitly to target a specific directory, which is
    useful when the script and the repository root are in different
    locations.

    **CLI usage** (``python -m microbench``): the default is the current
    working directory rather than the script directory, since
    ``sys.argv[0]`` points to the microbench package itself. Use
    ``--git-repo DIR`` to override.

    Attributes:
        git_repo (str, optional): Directory to inspect. Defaults to the
            directory of the running script, or the shell's working
            directory if unavailable.

    Example output::

        {
            "git": {
                "repo": "/home/user/project",
                "commit": "a1b2c3d4e5f6...",
                "branch": "main",
                "dirty": false
            }
        }
    """

    cli_compatible = True
    cli_args = [
        CLIArg(
            flags=['--git-repo'],
            dest='git_repo',
            metavar='DIR',
            type=_existing_dir,
            help=(
                'Directory to inspect for git info. '
                'CLI default: current working directory. '
                'Python API default: directory of the running script.'
            ),
            cli_default=lambda cmd: os.getcwd(),
        ),
    ]

    def capture_git_info(self, bm_data):
        if hasattr(self, 'git_repo'):
            cwd = self.git_repo
        else:
            argv0 = sys.argv[0] if sys.argv else ''
            if argv0 and not argv0.startswith('-'):
                cwd = os.path.dirname(os.path.abspath(argv0))
            else:
                cwd = None  # fall back to shell's working directory

        kwargs = {'cwd': cwd, 'stderr': subprocess.DEVNULL}

        repo = (
            subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], **kwargs)
            .decode()
            .strip()
        )

        output = subprocess.check_output(
            ['git', 'status', '--porcelain=v2', '--branch'], **kwargs
        ).decode()

        commit = ''
        branch = ''
        dirty = False
        for line in output.splitlines():
            if line.startswith('# branch.oid '):
                commit = line[13:]
            elif line.startswith('# branch.head '):
                head = line[14:]
                branch = '' if head == '(detached)' else head
            elif not line.startswith('#'):
                dirty = True

        bm_data['git'] = {
            'repo': repo,
            'commit': commit,
            'branch': branch,
            'dirty': dirty,
        }


class MBFileHash:
    """Capture cryptographic hashes of specified files.

    Useful for recording the exact state of scripts or configuration
    files alongside benchmark results, so results can be tied to a
    specific version of the code even without version control.

    By default hashes the running script (``sys.argv[0]``). Set
    ``hash_files`` to an iterable of paths to hash specific files
    instead. Files are read in 64 KB chunks, so large files are handled
    without loading them fully into memory.

    **CLI usage** (``python -m microbench``): the default is the
    benchmarked command executable (``cmd[0]``) rather than the running
    script, since ``sys.argv[0]`` points to the microbench package
    itself. Use ``--hash-file FILE [FILE ...]`` to override, and
    ``--hash-algorithm`` to change the algorithm.

    Attributes:
        hash_files (iterable of str, optional): File paths to hash.
            Defaults to ``[sys.argv[0]]``.
        hash_algorithm (str, optional): Hash algorithm name accepted by
            :func:`hashlib.new`. Defaults to ``'sha256'``. Use ``'md5'``
            for faster hashing of large files where cryptographic strength
            is not required.

    Example output::

        {
            "file_hashes": {
                "run_experiment.py": "e3b0c44298fc1c14..."
            }
        }
    """

    cli_compatible = True
    cli_args = [
        CLIArg(
            flags=['--hash-file'],
            dest='hash_files',
            metavar='FILE',
            nargs='+',
            type=_existing_file,
            help=(
                'File(s) to hash with the file-hash mixin. '
                'CLI default: the benchmarked command executable. '
                'Python API default: the running script.'
            ),
            cli_default=_resolve_cmd_path,
        ),
        CLIArg(
            flags=['--hash-algorithm'],
            dest='hash_algorithm',
            metavar='ALGORITHM',
            help='Hash algorithm for the file-hash mixin (e.g. sha256, md5). Default: sha256.',  # noqa: E501
        ),
    ]

    def capture_file_hashes(self, bm_data):
        import hashlib

        if hasattr(self, 'hash_files'):
            paths = list(self.hash_files)
        else:
            argv0 = sys.argv[0] if sys.argv else ''
            paths = [argv0] if argv0 and not argv0.startswith('-') else []

        algorithm = getattr(self, 'hash_algorithm', 'sha256')
        hashes = {}
        for path in paths:
            with open(path, 'rb') as f:
                if hasattr(hashlib, 'file_digest'):
                    # Python 3.11+: C-level loop, faster for large files
                    hashes[path] = hashlib.file_digest(f, algorithm).hexdigest()
                else:
                    h = hashlib.new(algorithm)
                    for chunk in iter(lambda: f.read(65536), b''):
                        h.update(chunk)
                    hashes[path] = h.hexdigest()
        bm_data['file_hashes'] = hashes


class MBGlobalPackages:
    """Capture Python packages imported in global environment.

    Results are stored in ``python.loaded_packages`` as a dict mapping
    package name to version string.
    """

    def capture_functions(self, bm_data):
        # Walk up the call stack to the first frame outside the microbench
        # package (excluding tests/) — that is the user's module whose globals
        # we want to inspect.
        caller_frame = inspect.currentframe()
        while caller_frame is not None:
            if not _is_microbench_internal(caller_frame.f_code.co_filename):
                break
            caller_frame = caller_frame.f_back
        if caller_frame is None:
            return
        caller_globals = caller_frame.f_globals
        for g in caller_globals.values():
            if isinstance(g, types.ModuleType):
                self._capture_package_version(bm_data, g, skip_if_none=True)
            else:
                try:
                    module_name = g.__module__
                except AttributeError:
                    continue

                self._capture_package_version(
                    bm_data, sys.modules[module_name.split('.')[0]], skip_if_none=True
                )


class MBCondaPackages:
    """Capture conda packages and active environment metadata.

    Runs ``conda list --prefix PREFIX`` where PREFIX is taken from the
    ``CONDA_PREFIX`` environment variable (the active conda environment).
    Falls back to ``sys.prefix`` when ``CONDA_PREFIX`` is not set (e.g.
    when running inside the base environment without explicit activation).

    If ``conda`` is not on ``PATH``, the ``CONDA_EXE`` environment variable
    is tried as a fallback before raising an error.

    Records a single ``conda`` dict with three keys:

    - ``name`` (from ``CONDA_DEFAULT_ENV``) — may be ``None`` if unset.
    - ``path`` (from ``CONDA_PREFIX``) — may be ``None`` if unset.
    - ``packages`` — dict mapping package name to version string.

    Attributes:
        include_builds (bool): Include the build string in the version.
            Defaults to ``True``.
        include_channels (bool): Include the channel name in the version.
            Defaults to ``False``.
    """

    cli_compatible = True
    include_builds = True
    include_channels = False

    def capture_conda_packages(self, bm_data):
        conda_prefix = os.environ.get('CONDA_PREFIX', sys.prefix)
        bm_data['conda'] = {
            'name': os.environ.get('CONDA_DEFAULT_ENV'),
            'path': os.environ.get('CONDA_PREFIX'),
            'packages': {},
        }

        conda_prefix = os.environ.get('CONDA_PREFIX', sys.prefix)
        conda_exe = shutil.which('conda') or os.environ.get('CONDA_EXE', 'conda')
        pkg_list = subprocess.check_output(
            [conda_exe, 'list', '--prefix', conda_prefix]
        ).decode('utf8')

        for pkg in pkg_list.splitlines():
            if pkg.startswith('#') or not pkg.strip():
                continue
            pkg_data = pkg.split()
            pkg_name = pkg_data[0]
            pkg_version = pkg_data[1]
            if self.include_builds:
                pkg_version += pkg_data[2]
            if self.include_channels and len(pkg_data) == 4:
                pkg_version += '(' + pkg_data[3] + ')'
            bm_data['conda']['packages'][pkg_name] = pkg_version


class MBInstalledPackages:
    """Capture installed Python packages using importlib.

    Records the name and version of every distribution available in the
    current Python environment via ``importlib.metadata``.

    Results are stored in ``python.installed_packages`` as a dict mapping
    package name to version string. When ``capture_paths=True``,
    installation paths are stored in ``python.installed_package_paths``.

    Attributes:
        capture_paths (bool): Also record the installation path of each
            package under ``python.installed_package_paths``. Defaults to
            ``False``.
    """

    cli_compatible = True
    capture_paths = False

    def capture_packages(self, bm_data):
        import importlib.metadata

        python = bm_data.setdefault('python', {})
        python['installed_packages'] = {}
        if self.capture_paths:
            python['installed_package_paths'] = {}

        for pkg in importlib.metadata.distributions():
            python['installed_packages'][pkg.name] = pkg.version
            if self.capture_paths:
                python['installed_package_paths'][pkg.name] = os.path.dirname(
                    pkg.locate_file(pkg.files[0])
                )


class MBLineProfiler:
    """
    Run the line profiler on the selected function

    Requires the line_profiler package. This will generate a benchmark which
    times the execution of each line of Python code in your function. This will
    slightly slow down the execution of your function, so it's not recommended
    in production.

    Results are stored in ``call.line_profiler`` as a base64-encoded pickled
    ``LineStats`` object.
    """

    def capturepost_line_profile(self, bm_data):
        bm_data.setdefault('call', {})['line_profiler'] = base64.b64encode(
            pickle.dumps(self._line_profiler.get_stats())
        ).decode('utf8')

    @staticmethod
    def decode_line_profile(line_profile_pickled):
        """Decode a base64-encoded pickled line profiler result.

        Security note: This uses pickle.loads, which can execute arbitrary
        code. Only call this on data from a trusted source (e.g. your own
        benchmark output files). Do not decode line profile data received
        over a network or from an untrusted file.
        """
        return pickle.loads(base64.b64decode(line_profile_pickled))

    @classmethod
    def print_line_profile(cls, line_profile_pickled, **kwargs):
        lp_data = cls.decode_line_profile(line_profile_pickled)
        line_profiler.show_text(lp_data.timings, lp_data.unit, **kwargs)


class _NeedsPsUtil:
    @classmethod
    def _check_psutil(cls):
        if not psutil:
            raise ImportError('psutil library needed')


class MBHostCpuCores(_NeedsPsUtil):
    """Capture the number of logical and physical CPU cores.

    Results are stored in the ``host`` dict under ``cpu_cores_logical``
    and ``cpu_cores_physical``.
    """

    cli_compatible = True

    def capture_cpu_cores(self, bm_data):
        self._check_psutil()
        host = bm_data.setdefault('host', {})
        host['cpu_cores_logical'] = psutil.cpu_count(logical=True)
        host['cpu_cores_physical'] = psutil.cpu_count(logical=False)


class MBHostRamTotal(_NeedsPsUtil):
    """Capture the total host RAM in bytes.

    Result is stored in ``host.ram_total``.
    """

    cli_compatible = True

    def capture_total_ram(self, bm_data):
        self._check_psutil()
        bm_data.setdefault('host', {})['ram_total'] = psutil.virtual_memory().total


class MBPeakMemory:
    """Capture peak Python memory allocation during the benchmarked function.

    Uses :mod:`tracemalloc` from the Python standard library (no extra
    dependencies). Records the peak memory allocated in bytes across all
    iterations as ``call.peak_memory_bytes``.

    Note:
        ``tracemalloc`` tracks memory that goes through Python's allocator,
        which covers Python objects and most C-extension allocations. Memory
        allocated directly via ``malloc`` in C extensions (e.g. some large
        NumPy arrays) is not tracked.
    """

    def capture_peak_memory(self, bm_data):
        import tracemalloc

        self._tracemalloc_was_tracing = tracemalloc.is_tracing()
        if self._tracemalloc_was_tracing:
            tracemalloc.reset_peak()
        else:
            tracemalloc.start()

    def capturepost_peak_memory(self, bm_data):
        import tracemalloc

        _, peak = tracemalloc.get_traced_memory()
        bm_data.setdefault('call', {})['peak_memory_bytes'] = peak
        if not self._tracemalloc_was_tracing:
            tracemalloc.stop()


class MBNvidiaSmi:
    """Capture attributes on installed NVIDIA GPUs using nvidia-smi.

    Requires the ``nvidia-smi`` utility to be available on ``PATH``
    (bundled with NVIDIA drivers).

    Results are stored as ``nvidia``, a list of per-GPU dicts. Each dict
    contains ``uuid`` plus one key per queried attribute. Run
    ``nvidia-smi --help-query-gpu`` for all available attribute names.
    Run ``nvidia-smi -L`` to list GPU UUIDs.

    Example output::

        {
            "nvidia": [
                {
                    "uuid": "GPU-abc123",
                    "gpu_name": "Tesla T4",
                    "memory.total": "16160 MiB"
                }
            ]
        }

    Attributes:
        nvidia_attributes (tuple[str]): Attributes to query. Defaults to
            ``('gpu_name', 'memory.total')``.
        nvidia_gpus (tuple): GPU IDs to poll — zero-based indexes, UUIDs,
            or PCI bus IDs. GPU UUIDs are recommended (indexes can change
            after a reboot). Omit to poll all installed GPUs.
    """

    cli_compatible = True
    _nvidia_default_attributes = ('gpu_name', 'memory.total')
    _nvidia_gpu_regex = re.compile(r'^[0-9A-Za-z\-:]+$')

    def capture_nvidia(self, bm_data):
        nvidia_attributes = getattr(
            self, 'nvidia_attributes', self._nvidia_default_attributes
        )

        if hasattr(self, 'nvidia_gpus'):
            gpus = self.nvidia_gpus
            if not gpus:
                raise ValueError(
                    'nvidia_gpus cannot be empty. Leave the attribute out'
                    ' to capture data for all GPUs'
                )
            for gpu in gpus:
                if not self._nvidia_gpu_regex.match(str(gpu)):
                    raise ValueError(
                        'nvidia_gpus must be a list of GPU indexes (zero-based),'
                        ' UUIDs, or PCI bus IDs'
                    )
        else:
            gpus = None

        # Construct the command
        cmd = [
            'nvidia-smi',
            '--format=csv,noheader',
            '--query-gpu=uuid,{}'.format(','.join(nvidia_attributes)),
        ]
        if gpus:
            cmd += ['-i', ','.join(str(g) for g in gpus)]

        # Execute the command
        res = subprocess.check_output(cmd).decode('utf8')

        # Process results into a list of per-GPU dicts
        nvidia_list = []
        for gpu_line in res.split('\n'):
            if not gpu_line:
                continue
            gpu_res = gpu_line.split(', ')
            gpu_uuid = gpu_res[0]
            gpu_dict = {'uuid': gpu_uuid}
            for attr_idx, attr in enumerate(nvidia_attributes):
                gpu_dict[attr] = gpu_res[attr_idx + 1]
            nvidia_list.append(gpu_dict)
        bm_data['nvidia'] = nvidia_list


class _MonitorThread(threading.Thread):
    def __init__(self, telem_fn, interval, slot, timezone, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._terminate = threading.Event()
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self.terminate)
            signal.signal(signal.SIGTERM, self.terminate)
        else:
            warnings.warn(
                '_MonitorThread: signal handlers not registered because '
                'benchmark was started from a non-main thread. Monitoring '
                'will still be collected but may not stop cleanly on '
                'SIGINT/SIGTERM.',
                RuntimeWarning,
            )
        self._interval = interval
        self._monitor_data = slot
        self._monitor_fn = telem_fn
        self._tz = timezone
        if not psutil:
            raise ImportError('Monitoring requires the "psutil" package')
        self.process = psutil.Process()

    def terminate(self, signum=None, frame=None):
        self._terminate.set()

    def _get_sample(self):
        sample = {'timestamp': datetime.now(self._tz)}
        sample.update(self._monitor_fn(self.process))
        self._monitor_data.append(sample)

    def run(self):
        self._get_sample()
        while not self._terminate.wait(self._interval):
            self._get_sample()
