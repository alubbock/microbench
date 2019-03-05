from datetime import datetime
import json
import platform
import socket
import sys
import collections
import os
import inspect
import types


from ._version import get_versions
__version__ = get_versions()['version']
del get_versions


class MicroBench(object):
    def __init__(self, *args, **kwargs):
        self._capture_before = []
        if args:
            raise ValueError('Only keyword arguments are allowed')
        self._bm_static = kwargs

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

        for method in self._capture_before:
            method(bm_data)

        # Special case, as we want this to run immediately before run
        bm_data['start_time'] = datetime.now()

    def post_run_triggers(self, bm_data):
        # Special case, as we want this to run immediately after run
        bm_data['finish_time'] = datetime.now()

        for method_name in dir(self):
            if method_name.startswith('capture_'):
                method = getattr(self, method_name)
                if callable(method) and method not in self._capture_before:
                    method(bm_data)

    def capture_function_name(self, bm_data):
        bm_data['function_name'] = bm_data['_func'].__name__

    def _capture_package_version(self, bm_data, pkg, skip_if_none=False):
        try:
            ver = pkg.__version__
        except AttributeError:
            if skip_if_none:
                return
            ver = None
        bm_data['{}_version'.format(pkg.__name__)] = ver

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

            self.pre_run_triggers(bm_data)

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
    """ Capture the Python version """
    def capture_python_version(self, bm_data):
        bm_data['python_version'] = platform.python_version()


class MBHostInfo(object):
    """ Capture the hostname and operating system """
    def capture_hostname(self, bm_data):
        bm_data['hostname'] = socket.gethostname()

    def capture_os(self, bm_data):
        bm_data['operating_system'] = sys.platform


class MBGlobalPackages(object):
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


class MicroBenchRedis(MicroBench):
    def __init__(self, *args, **kwargs):
        super(MicroBenchRedis, self).__init__(*args, **kwargs)

        import redis
        self.rclient = redis.StrictRedis(**self.redis_connection)

    def output_result(self, bm_data):
        self.rclient.rpush(self.redis_key, self.to_json(bm_data))
