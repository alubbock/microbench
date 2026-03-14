import base64
import inspect
import io
import json
import os
import pickle
import platform
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import types
import uuid
import warnings
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

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
try:
    import pandas
except ImportError:
    pandas = None


try:
    # Written by setuptools-scm at build/install time
    from ._version_scm import __version__
except ImportError:
    try:
        from importlib.metadata import version as _version

        __version__ = _version('microbench')
    except Exception:
        __version__ = 'unknown'

# Generated once at import time; shared by all MicroBench instances in this
# process, allowing records from independent bench suites to be correlated.
_run_id = str(uuid.uuid4())

__all__ = [
    # Core
    'MicroBench',
    # Output sinks
    'Output',
    'FileOutput',
    'RedisOutput',
    # Mixins
    'MBFunctionCall',
    'MBReturnValue',
    'MBPythonVersion',
    'MBHostInfo',
    'MBHostCpuCores',
    'MBHostRamTotal',
    'MBPeakMemory',
    'MBSlurmInfo',
    'MBLoadedModules',
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


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, timedelta):
            return o.total_seconds()
        if isinstance(o, timezone):
            return str(o)
        if numpy:
            if isinstance(o, numpy.integer):
                return int(o)
            elif isinstance(o, numpy.floating):
                return float(o)
            elif isinstance(o, numpy.ndarray):
                return o.tolist()

        return super().default(o)


class JSONEncodeWarning(Warning):
    """Warning used when JSON encoding fails"""

    pass


_UNENCODABLE_PLACEHOLDER_VALUE = '__unencodable_as_json__'


class Output:
    """Abstract base class for benchmark output sinks.

    Subclass this to implement custom output destinations.
    Must implement :meth:`write`. May optionally implement
    :meth:`get_results` to allow reading back stored results.

    Example::

        class MyOutput(Output):
            def write(self, bm_json_str):
                send_somewhere(bm_json_str)
    """

    def write(self, bm_json_str):
        """Write a single JSON-encoded benchmark result.

        Args:
            bm_json_str (str): JSON string (without trailing newline).
        """
        raise NotImplementedError

    def get_results(self):
        """Return all stored results as a pandas DataFrame.

        Raises:
            NotImplementedError: If this sink does not support reading results.
            ImportError: If pandas is not installed.
        """
        raise NotImplementedError(
            f'{type(self).__name__} does not support get_results()'
        )


class FileOutput(Output):
    """Write benchmark results to a file path or file-like object (JSONL format).

    Each result is written as a single JSON line. When *outfile* is a path
    string, each write opens the file in append mode (POSIX ``O_APPEND``),
    which is safe for concurrent writers on the same filesystem. When
    *outfile* is a file-like object it is written to directly.

    When no *outfile* is given an :class:`io.StringIO` buffer is used,
    which allows results to be read back via :meth:`get_results`.

    Args:
        outfile (str or file-like, optional): Destination file path or
            file-like object. Defaults to a fresh :class:`io.StringIO`.
    """

    def __init__(self, outfile=None):
        if outfile is None:
            outfile = io.StringIO()
        self.outfile = outfile

    def write(self, bm_json_str):
        bm_str = bm_json_str + '\n'
        if isinstance(self.outfile, str):
            with open(self.outfile, 'a') as f:
                f.write(bm_str)
        else:
            self.outfile.write(bm_str)

    def get_results(self):
        if not pandas:
            raise ImportError('This functionality requires the "pandas" package')
        if hasattr(self.outfile, 'seek'):
            self.outfile.seek(0)
        return pandas.read_json(self.outfile, lines=True)


class RedisOutput(Output):
    """Write benchmark results to a Redis list (one JSON string per record).

    Results are appended using ``RPUSH`` and can be read back via
    :meth:`get_results` using ``LRANGE``.

    Args:
        redis_key (str): Redis key for the result list.
        **redis_connection: Keyword arguments forwarded to
            ``redis.StrictRedis()`` (e.g. ``host``, ``port``).

    Example::

        from microbench import MicroBench, RedisOutput

        bench = MicroBench(outputs=[RedisOutput('microbench:mykey',
                                                host='localhost', port=6379)])
    """

    def __init__(self, redis_key, **redis_connection):
        import redis as _redis

        self.rclient = _redis.StrictRedis(**redis_connection)
        self.redis_key = redis_key

    def write(self, bm_json_str):
        self.rclient.rpush(self.redis_key, bm_json_str)

    def get_results(self):
        if not pandas:
            raise ImportError('This functionality requires the "pandas" package')
        redis_data = self.rclient.lrange(self.redis_key, 0, -1)
        json_data = '\n'.join(r.decode('utf8') for r in redis_data)
        return pandas.read_json(io.StringIO(json_data), lines=True)


class MicroBench:
    def __init__(
        self,
        outfile=None,
        json_encoder=JSONEncoder,
        tz=timezone.utc,
        iterations=1,
        warmup=0,
        duration_counter=time.perf_counter,
        outputs=None,
        *args,
        **kwargs,
    ):
        """Benchmark and metadata capture suite.

        Args:
            outfile (str or file-like, optional): Shorthand for a single
                :class:`FileOutput` destination. Mutually exclusive with
                *outputs*. Defaults to None (an in-memory
                :class:`io.StringIO` buffer when no *outputs* are given).
            json_encoder (json.JSONEncoder, optional): JSONEncoder for
                benchmark results. Defaults to JSONEncoder.
            tz (timezone, optional): Timezone for start_time and finish_time.
                Defaults to timezone.utc.
            iterations (int, optional): Number of iterations to run function.
                Defaults to 1.
            warmup (int, optional): Number of unrecorded calls to make before
                timing begins. Useful for priming caches or JIT compilation.
                Defaults to 0.
            duration_counter (callable, optional): Timer function to use for
                run_durations. Defaults to time.perf_counter.
            outputs (list of Output, optional): One or more :class:`Output`
                sinks that receive each benchmark result. Mutually exclusive
                with *outfile*. Defaults to a single :class:`FileOutput`
                (using *outfile* if given, otherwise the class-level
                ``outfile`` attribute, otherwise an in-memory
                :class:`io.StringIO`).

        Raises:
            ValueError: If both *outfile* and *outputs* are provided, or if
                extra positional arguments are passed.
        """
        if args:
            raise ValueError('Only keyword arguments are allowed')
        if outfile is not None and outputs is not None:
            raise ValueError(
                'outfile and outputs are mutually exclusive; '
                'use outputs=[FileOutput(...)] to combine file output with '
                'other sinks'
            )
        self._bm_static = kwargs
        self._json_encoder = json_encoder
        self._duration_counter = duration_counter
        self.tz = tz
        self.iterations = iterations
        self.warmup = warmup

        if outputs is not None:
            self._outputs = list(outputs)
        elif outfile is not None:
            self._outputs = [FileOutput(outfile)]
        elif hasattr(self, 'outfile'):
            self._outputs = [FileOutput(self.outfile)]
        else:
            self._outputs = [FileOutput()]

    def pre_start_triggers(self, bm_data):
        # Store timezone
        bm_data['timestamp_tz'] = str(self.tz)
        # Store duration counter function name
        bm_data['duration_counter'] = self._duration_counter.__name__
        # Run ID and package version (added to every record automatically)
        bm_data['mb_run_id'] = _run_id
        bm_data['mb_version'] = __version__

        # Capture environment variables
        if hasattr(self, 'env_vars'):
            if not isinstance(self.env_vars, Iterable):
                raise ValueError(
                    'env_vars should be a tuple of environment variable names'
                )

            for env_var in self.env_vars:
                bm_data[f'env_{env_var}'] = os.environ.get(env_var)

        # Capture package versions
        if hasattr(self, 'capture_versions'):
            if not isinstance(self.capture_versions, Iterable):
                raise ValueError(
                    'capture_versions is reserved for a tuple of package names'
                    ' - please rename this method'
                )

            for pkg in self.capture_versions:
                self._capture_package_version(bm_data, pkg)

        # Run capture triggers
        for method_name in dir(self):
            if method_name.startswith('capture_'):
                method = getattr(self, method_name)
                if callable(method):
                    if getattr(self, 'capture_optional', False):
                        try:
                            method(bm_data)
                        except Exception as e:
                            bm_data.setdefault('mb_capture_errors', []).append(
                                {
                                    'method': method_name,
                                    'error': f'{type(e).__name__}: {e}',
                                }
                            )
                    else:
                        method(bm_data)

        # Initialise monitor thread
        if hasattr(self, 'monitor'):
            interval = getattr(self, 'monitor_interval', 60)
            bm_data['monitor'] = []
            self._monitor_thread = MonitorThread(
                self.monitor, interval, bm_data['monitor'], self.tz
            )
            self._monitor_thread.start()

        bm_data['run_durations'] = []
        bm_data['start_time'] = datetime.now(self.tz)

    def post_finish_triggers(self, bm_data):
        bm_data['finish_time'] = datetime.now(self.tz)

        # Terminate monitor thread and gather results
        if hasattr(self, '_monitor_thread'):
            self._monitor_thread.terminate()
            timeout = getattr(self, 'monitor_timeout', 30)
            self._monitor_thread.join(timeout)

        # Run capturepost triggers
        for method_name in dir(self):
            if method_name.startswith('capturepost_'):
                method = getattr(self, method_name)
                if callable(method):
                    if getattr(self, 'capture_optional', False):
                        try:
                            method(bm_data)
                        except Exception as e:
                            bm_data.setdefault('mb_capture_errors', []).append(
                                {
                                    'method': method_name,
                                    'error': f'{type(e).__name__}: {e}',
                                }
                            )
                    else:
                        method(bm_data)

    def pre_run_triggers(self, bm_data):
        bm_data['_run_start'] = self._duration_counter()

    def post_run_triggers(self, bm_data):
        bm_data['run_durations'].append(
            self._duration_counter() - bm_data['_run_start']
        )

    def capture_function_name(self, bm_data):
        bm_data['function_name'] = bm_data['_func'].__name__

    def _capture_package_version(self, bm_data, pkg, skip_if_none=False):
        bm_data.setdefault('package_versions', {})
        try:
            ver = pkg.__version__
        except AttributeError:
            if skip_if_none:
                return
            ver = None
        bm_data['package_versions'][pkg.__name__] = ver

    def to_json(self, bm_data):
        bm_str = f'{json.dumps(bm_data, cls=self._json_encoder)}'

        return bm_str

    def output_result(self, bm_data):
        """Fan out the JSON-encoded result to all configured output sinks."""
        bm_str = self.to_json(bm_data)
        for output in self._outputs:
            output.write(bm_str)

    def get_results(self):
        """Return results from the first output sink that supports it."""
        for output in self._outputs:
            try:
                return output.get_results()
            except NotImplementedError:
                continue
        raise RuntimeError(
            'None of the configured output sinks support get_results(). '
            'Use FileOutput or RedisOutput.'
        )

    def __call__(self, func):
        def inner(*args, **kwargs):
            bm_data = dict()
            bm_data.update(self._bm_static)
            bm_data['_func'] = func
            bm_data['_args'] = args
            bm_data['_kwargs'] = kwargs

            if isinstance(self, MBLineProfiler):
                if not line_profiler:
                    raise ImportError(
                        'This functionality requires the "line_profiler" package'
                    )
                self._line_profiler = line_profiler.LineProfiler(func)

            for _ in range(self.warmup):
                func(*args, **kwargs)

            self.pre_start_triggers(bm_data)

            for _ in range(self.iterations):
                self.pre_run_triggers(bm_data)

                if isinstance(self, MBLineProfiler):
                    res = self._line_profiler.runcall(func, *args, **kwargs)
                else:
                    res = func(*args, **kwargs)
                self.post_run_triggers(bm_data)

            self.post_finish_triggers(bm_data)

            if isinstance(self, MBReturnValue):
                try:
                    self.to_json(res)
                    bm_data['return_value'] = res
                except TypeError:
                    warnings.warn(
                        f'Return value is not JSON encodable (type: {type(res)}). '
                        'Extend JSONEncoder class to fix (see README).',
                        JSONEncodeWarning,
                    )
                    bm_data['return_value'] = _UNENCODABLE_PLACEHOLDER_VALUE

            # Delete any underscore-prefixed keys
            bm_data = {k: v for k, v in bm_data.items() if not k.startswith('_')}

            self.output_result(bm_data)

            return res

        return inner


class MBFunctionCall:
    """Capture function arguments and keyword arguments"""

    def capture_function_args_and_kwargs(self, bm_data):
        # Check all args are encodeable as JSON, then store the raw value
        bm_data['args'] = []
        for i, v in enumerate(bm_data['_args']):
            try:
                self.to_json(v)
                bm_data['args'].append(v)
            except TypeError:
                warnings.warn(
                    f'Function argument {i} is not JSON encodable (type: {type(v)}). '
                    'Extend JSONEncoder class to fix (see README).',
                    JSONEncodeWarning,
                )
                bm_data['args'].append(_UNENCODABLE_PLACEHOLDER_VALUE)

        # Check all kwargs are encodeable as JSON, then store the raw value
        bm_data['kwargs'] = {}
        for k, v in bm_data['_kwargs'].items():
            try:
                self.to_json(v)
                bm_data['kwargs'][k] = v
            except TypeError:
                warnings.warn(
                    f'Function keyword argument "{k}" is not JSON encodable'
                    f' (type: {type(v)}). Extend JSONEncoder class to fix'
                    ' (see README).',
                    JSONEncodeWarning,
                )
                bm_data['kwargs'][k] = _UNENCODABLE_PLACEHOLDER_VALUE


class MBReturnValue:
    """Capture the decorated function's return value"""

    pass


class MBPythonVersion:
    """Capture the Python version and location of the Python executable"""

    cli_compatible = True

    def capture_python_version(self, bm_data):
        bm_data['python_version'] = platform.python_version()

    def capture_python_executable(self, bm_data):
        bm_data['python_executable'] = sys.executable


class MBHostInfo:
    """Capture the hostname and operating system"""

    cli_compatible = True

    def capture_hostname(self, bm_data):
        bm_data['hostname'] = socket.gethostname()

    def capture_os(self, bm_data):
        bm_data['operating_system'] = sys.platform


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


class MBGitInfo:
    """Capture git repository information.

    Requires ``git`` ≥ 2.11 to be available on ``PATH``. Records the
    current repo directory, commit hash, branch name, and whether the
    working tree has uncommitted changes. Results are stored in the
    ``git_info`` field.

    By default inspects the repository containing the running script
    (``sys.argv[0]``), falling back to the shell's working directory
    when the script path is unavailable (e.g. interactive Python). Set
    ``git_repo`` explicitly to target a specific directory, which is
    useful when the script and the repository root are in different
    locations.

    Attributes:
        git_repo (str, optional): Directory to inspect. Defaults to the
            directory of the running script, or the shell's working
            directory if unavailable.

    Example output::

        {
            "git_info": {
                "repo": "/home/user/project",
                "commit": "a1b2c3d4e5f6...",
                "branch": "main",
                "dirty": false
            }
        }
    """

    cli_compatible = True

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

        bm_data['git_info'] = {
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
    """Capture Python packages imported in global environment"""

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
    """Capture conda packages using the conda CLI.

    Requires ``conda`` to be available on ``PATH``. Captures all packages
    in the active conda environment (determined by ``sys.prefix``).

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
        pkg_list = subprocess.check_output(
            ['conda', 'list', '--prefix', sys.prefix]
        ).decode('utf8')

        bm_data['conda_versions'] = {}

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
            bm_data['conda_versions'][pkg_name] = pkg_version


class MBInstalledPackages:
    """Capture installed Python packages using importlib.

    Records the name and version of every distribution available in the
    current Python environment via ``importlib.metadata``.

    Attributes:
        capture_paths (bool): Also record the installation path of each
            package under ``package_paths``. Defaults to ``False``.
    """

    cli_compatible = True
    capture_paths = False

    def capture_packages(self, bm_data):
        import importlib.metadata

        bm_data['package_versions'] = {}
        if self.capture_paths:
            bm_data['package_paths'] = {}

        for pkg in importlib.metadata.distributions():
            bm_data['package_versions'][pkg.name] = pkg.version
            if self.capture_paths:
                bm_data['package_paths'][pkg.name] = os.path.dirname(
                    pkg.locate_file(pkg.files[0])
                )


class MBLineProfiler:
    """
    Run the line profiler on the selected function

    Requires the line_profiler package. This will generate a benchmark which
    times the execution of each line of Python code in your function. This will
    slightly slow down the execution of your function, so it's not recommended
    in production.
    """

    def capturepost_line_profile(self, bm_data):
        bm_data['line_profiler'] = base64.b64encode(
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
    """Capture the number of logical CPU cores"""

    cli_compatible = True

    def capture_cpu_cores(self, bm_data):
        self._check_psutil()
        bm_data['cpu_cores_logical'] = psutil.cpu_count(logical=True)
        bm_data['cpu_cores_physical'] = psutil.cpu_count(logical=False)


class MBHostRamTotal(_NeedsPsUtil):
    """Capture the total host RAM in bytes"""

    cli_compatible = True

    def capture_total_ram(self, bm_data):
        self._check_psutil()
        bm_data['ram_total'] = psutil.virtual_memory().total


class MBPeakMemory:
    """Capture peak Python memory allocation during the benchmarked function.

    Uses :mod:`tracemalloc` from the Python standard library (no extra
    dependencies). Records the peak memory allocated in bytes across all
    iterations as ``peak_memory_bytes``.

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
        bm_data['peak_memory_bytes'] = peak
        if not self._tracemalloc_was_tracing:
            tracemalloc.stop()


class MBNvidiaSmi:
    """Capture attributes on installed NVIDIA GPUs using nvidia-smi.

    Requires the ``nvidia-smi`` utility to be available on ``PATH``
    (bundled with NVIDIA drivers).

    Results are stored as ``nvidia_<attr>`` fields, each a dict keyed by
    GPU UUID. Run ``nvidia-smi --help-query-gpu`` for all available
    attribute names. Run ``nvidia-smi -L`` to list GPU UUIDs.

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

        # Process results
        for gpu_line in res.split('\n'):
            if not gpu_line:
                continue
            gpu_res = gpu_line.split(', ')
            for attr_idx, attr in enumerate(nvidia_attributes):
                gpu_uuid = gpu_res[0]
                bm_data.setdefault(f'nvidia_{attr}', {})[gpu_uuid] = gpu_res[
                    attr_idx + 1
                ]


class MonitorThread(threading.Thread):
    def __init__(self, telem_fn, interval, slot, timezone, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._terminate = threading.Event()
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self.terminate)
            signal.signal(signal.SIGTERM, self.terminate)
        else:
            warnings.warn(
                'MonitorThread: signal handlers not registered because '
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
