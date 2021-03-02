from datetime import datetime
import json
import platform
import socket
import sys
import collections
import os
import inspect
import types
import pickle
import base64
import re
import subprocess
import io
try:
    import pkg_resources
except ImportError:
    pkg_resources = None
try:
    import line_profiler
except ImportError:
    line_profiler = None
try:
    import psutil
except ImportError:
    psutil = None
try:
    import conda
    import conda.cli.python_api
except ImportError:
    conda = None


from ._version import get_versions
__version__ = get_versions()['version']
del get_versions


class MicroBench(object):
    def __init__(self, outfile=None, *args, **kwargs):
        self._capture_before = []
        if args:
            raise ValueError('Only keyword arguments are allowed')
        self._bm_static = kwargs
        if outfile is not None:
            self.outfile = outfile
        elif not hasattr(self, 'outfile'):
            self.outfile = io.StringIO()

    def pre_run_triggers(self, bm_data):
        # Capture environment variables
        if hasattr(self, 'env_vars'):
            if not isinstance(self.env_vars, collections.Iterable):
                raise ValueError('env_vars should be a tuple of environment '
                                 'variable names')

            for env_var in self.env_vars:
                bm_data['env_{}'.format(env_var)] = os.environ.get(env_var)

        # Capture package versions
        if hasattr(self, 'capture_versions'):
            if not isinstance(self.capture_versions, collections.Iterable):
                raise ValueError('capture_versions is reserved for a tuple of'
                                 'package names - please rename this method')

            for pkg in self.capture_versions:
                self._capture_package_version(bm_data, pkg)

        # Run capture triggers
        for method_name in dir(self):
            if method_name.startswith('capture_'):
                method = getattr(self, method_name)
                if callable(method) and method not in self._capture_before:
                    method(bm_data)

        # Special case, as we want this to run immediately before run
        bm_data['start_time'] = datetime.now()

    def post_run_triggers(self, bm_data):
        # Special case, as we want this to run immediately after run
        bm_data['finish_time'] = datetime.now()

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

    @staticmethod
    def json_serializer(o):
        if isinstance(o, datetime):
            return o.isoformat()

    @classmethod
    def to_json(cls, bm_data):
        bm_str = '{}'.format(json.dumps(bm_data,
                                        default=cls.json_serializer))

        # On python 2, decode bm_str as UTF-8
        if sys.version_info[0] < 3:
            bm_str = bm_str.decode('utf8')

        return bm_str

    def output_result(self, bm_data):
        """ Output result to self.outfile as a line in JSON format """
        bm_str = self.to_json(bm_data) + '\n'

        # This should guarantee atomic writes on POSIX by setting O_APPEND
        if isinstance(self.outfile, str):
            with open(self.outfile, 'a') as f:
                f.write(bm_str)
        else:
            # Assume file-like object
            self.outfile.write(bm_str)

    def __call__(self, func):
        def inner(*args, **kwargs):
            bm_data = dict()
            bm_data.update(self._bm_static)
            bm_data['_func'] = func
            bm_data['_args'] = args
            bm_data['_kwargs'] = kwargs

            if isinstance(self, MBLineProfiler):
                if not line_profiler:
                    raise ImportError('This functionality requires the '
                                      '"line_profiler" package')
                self._line_profiler = line_profiler.LineProfiler(func)

            self.pre_run_triggers(bm_data)

            if isinstance(self, MBLineProfiler):
                res = self._line_profiler.runcall(func, *args, **kwargs)
            else:
                res = func(*args, **kwargs)

            self.post_run_triggers(bm_data)

            # Delete any underscore-prefixed keys
            bm_data = {k: v for k, v in bm_data.items()
                       if not k.startswith('_')}

            self.output_result(bm_data)

            return res

        return inner


class MBFunctionCall(object):
    """ Capture function arguments and keyword arguments """
    def capture_function_args_and_kwargs(self, bm_data):
        bm_data['args'] = bm_data['_args']
        bm_data['kwargs'] = bm_data['_kwargs']


class MBPythonVersion(object):
    """ Capture the Python version and location of the Python executable """
    def capture_python_version(self, bm_data):
        bm_data['python_version'] = platform.python_version()

    def capture_python_executable(self, bm_data):
        bm_data['python_executable'] = sys.executable


class MBHostInfo(object):
    """ Capture the hostname and operating system """
    def capture_hostname(self, bm_data):
        bm_data['hostname'] = socket.gethostname()

    def capture_os(self, bm_data):
        bm_data['operating_system'] = sys.platform


class MBGlobalPackages(object):
    """ Capture Python packages imported in global environment """
    def capture_functions(self, bm_data):
        # Get globals of caller
        caller_frame = inspect.currentframe().f_back.f_back.f_back
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
                    bm_data,
                    sys.modules[module_name.split('.')[0]],
                    skip_if_none=True
                )


class MBCondaPackages(object):
    """ Capture conda packages; requires 'conda' package (pip install conda) """
    include_builds = True
    include_channels = False

    def capture_conda_packages(self, bm_data):
        if conda is None:
            # Use subprocess
            pkg_list = subprocess.check_output(['conda', 'list']).decode('utf8')
        else:
            # Use conda Python API
            pkg_list, stderr, ret_code = conda.cli.python_api.run_command(
                conda.cli.python_api.Commands.LIST)

            if ret_code != 0 or stderr:
                raise RuntimeError('Error running conda list: {}'.format(
                    stderr))

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
                pkg_version += pkg_version + '(' + pkg_data[3] + ')'
            bm_data['conda_versions'][pkg_name] = pkg_version


class MBInstalledPackages(object):
    """ Capture installed Python packages using pkg_resources """
    capture_paths = False

    def capture_packages(self, bm_data):
        if not pkg_resources:
            raise ImportError(
                'pkg_resources is required to capture package names, which is '
                'provided with the "setuptools" package')

        bm_data['package_versions'] = {}
        if self.capture_paths:
            bm_data['package_paths'] = {}

        for pkg in pkg_resources.working_set:
            bm_data['package_versions'][pkg.project_name] = pkg.version
            if self.capture_paths:
                bm_data['package_paths'][pkg.project_name] = pkg.location


class MBLineProfiler(object):
    """
    Run the line profiler on the selected function

    Requires the line_profiler package. This will generate a benchmark which
    times the execution of each line of Python code in your function. This will
    slightly slow down the execution of your function, so it's not recommended
    in production.
    """
    def capture_line_profile(self, bm_data):
        bm_data['line_profiler'] = base64.encodebytes(
            pickle.dumps(self._line_profiler.get_stats())
        ).decode('utf8')

    @staticmethod
    def decode_line_profile(line_profile_pickled):
        return pickle.loads(base64.decodebytes(line_profile_pickled.encode()))

    @classmethod
    def print_line_profile(self, line_profile_pickled, **kwargs):
        lp_data = self.decode_line_profile(line_profile_pickled)
        line_profiler.show_text(lp_data.timings, lp_data.unit, **kwargs)


class _NeedsPsUtil(object):
    @classmethod
    def _check_psutil(cls):
        if not psutil:
            raise ImportError('psutil library needed')


class MBHostCpuCores(_NeedsPsUtil):
    """ Capture the number of logical CPU cores """
    def capture_cpu_cores(self, bm_data):
        self._check_psutil()
        bm_data['cpu_cores_logical'] = psutil.cpu_count()


class MBHostRamTotal(_NeedsPsUtil):
    """ Capture the total host RAM in bytes """
    def capture_total_ram(self, bm_data):
        self._check_psutil()
        bm_data['ram_total'] = psutil.virtual_memory().total


class MBNvidiaSmi(object):
    """
    Capture attributes on installed NVIDIA GPUs using nvidia-smi

    Requires the nvidia-smi utility to be available in the current PATH.

    By default, the gpu_name and memory.total attributes are captured. Extra
    attributes can be specified using the class or object-level variable
    nvidia_attributes.

    By default, all installed GPUs will be polled. To limit to a specific GPU,
    specify the nvidia_gpus attribute as a tuple of GPU IDs, which can be
    zero-based GPU indexes (can change between reboots, not recommended),
    GPU UUIDs, or PCI bus IDs.
    """

    _nvidia_attributes_available = ('gpu_name', 'memory.total')
    _nvidia_gpu_regex = re.compile(r'^[0-9A-Za-z\-:]+$')

    def capture_nvidia(self, bm_data):
        if hasattr(self, 'nvidia_attributes'):
            nvidia_attributes = self.nvidia_attributes
            unknown_attrs = set(self._nvidia_attributes_available).difference(
                nvidia_attributes
            )
            if unknown_attrs:
                raise ValueError("Unknown nvidia_attributes: {}".format(
                    ', '.join(unknown_attrs)
                ))
        else:
            nvidia_attributes = self._nvidia_attributes_available

        if hasattr(self, 'nvidia_gpus'):
            gpus = self.nvidia_gpus
            if not gpus:
                raise ValueError('nvidia_gpus cannot be empty. Leave the '
                                 'attribute out to capture data for all GPUs')
            for gpu in gpus:
                if not self._nvidia_gpu_regex.match(gpu):
                    raise ValueError('nvidia_gpus must be a list of GPU indexes'
                                     '(zero-based), UUIDs, or PCI bus IDs')
        else:
            gpus = None

        # Construct the command
        cmd = ['nvidia-smi', '--format=csv,noheader',
               '--query-gpu=uuid,{}'.format(','.join(nvidia_attributes))]
        if gpus:
            cmd += ['-i', ','.join(gpus)]

        # Execute the command
        res = subprocess.check_output(cmd).decode('utf8')

        # Process results
        for gpu_line in res.split('\n'):
            if not gpu_line:
                continue
            gpu_res = gpu_line.split(', ')
            for attr_idx, attr in enumerate(nvidia_attributes):
                gpu_uuid = gpu_res[0]
                bm_data.setdefault('nvidia_{}'.format(attr), {})[gpu_uuid] = \
                    gpu_res[attr_idx + 1]


class MicroBenchRedis(MicroBench):
    def __init__(self, *args, **kwargs):
        super(MicroBenchRedis, self).__init__(*args, **kwargs)

        import redis
        self.rclient = redis.StrictRedis(**self.redis_connection)

    def output_result(self, bm_data):
        self.rclient.rpush(self.redis_key, self.to_json(bm_data))
