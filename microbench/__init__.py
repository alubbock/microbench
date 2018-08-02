from datetime import datetime
import json
import platform
import socket
import sys


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
        for method in self._capture_before:
            method(bm_data)

        # Special case, as we want this to run last
        self.capture_start(bm_data)

    def post_run_triggers(self, bm_data):
        for method_name in dir(self):
            if method_name.startswith('capture_'):
                method = getattr(self, method_name)
                if not callable(method):
                    raise ValueError('{} is not callable'.format(method_name))
                if method not in self._capture_before:
                    method(bm_data)

    def capture_start(self, bm_data):
        bm_data['start'] = datetime.now()

    def capture_finish(self, bm_data):
        bm_data['finish'] = datetime.now()

    @staticmethod
    def json_serializer(o):
        if isinstance(o, datetime):
            return o.isoformat()

    def output_result(self, bm_data):
        """ Output result to self.outfile as a line in JSON format """
        bm_str = '{}\n'.format(json.dumps(bm_data,
                                          default=self.json_serializer))

        # On python 2, decode bm_str as UTF-8
        if sys.version_info[0] < 3:
            bm_str = bm_str.decode('utf8')

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
    def capture_function_name(self, bm_data):
        bm_data['function_name'] = bm_data['_func'].__name__

    def capture_function_args_and_kwargs(self, bm_data):
        bm_data['args'] = bm_data['_args']
        bm_data['kwargs'] = bm_data['_kwargs']


class MBPythonVersion(object):
    def capture_python_version(self, bm_data):
        bm_data['python_version'] = platform.python_version()


class MBHostInfo(object):
    def capture_hostname(self, bm_data):
        bm_data['hostname'] = socket.gethostname()

    def capture_os(self, bm_data):
        bm_data['operating_system'] = sys.platform
