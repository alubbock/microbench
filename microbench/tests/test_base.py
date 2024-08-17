from microbench import MicroBench, MBFunctionCall, MBPythonVersion, \
    MBReturnValue, MBHostInfo, MBInstalledPackages, \
    JSONEncodeWarning, JSONEncoder, _UNENCODABLE_PLACEHOLDER_VALUE
from microbench import __version__ as microbench_version
import io
import pandas
import datetime
import warnings
from .globals_capture import globals_bench


def test_function():
    class MyBench(MicroBench, MBFunctionCall, MBPythonVersion, MBHostInfo):
        capture_versions = (pandas, io)
        env_vars = ('TEST_NON_EXISTENT', 'HOME')

    benchmark = MyBench(some_info='123')

    @benchmark
    def my_function():
        """ Inefficient function for testing """
        acc = 0
        for i in range(1000000):
            acc += i

        return acc

    for _ in range(3):
        assert my_function() == 499999500000

    results = pandas.read_json(benchmark.outfile.getvalue(), lines=True)
    assert (results['function_name'] == 'my_function').all()
    assert results['package_versions'][0]['pandas'] == pandas.__version__
    runtimes = results['finish_time'] - results['start_time']
    assert (runtimes > datetime.timedelta(0)).all()


def test_multi_iterations():
    class MyBench(MicroBench):
        pass

    timezone = datetime.timezone(datetime.timedelta(hours=10))
    iterations = 3
    benchmark = MyBench(iterations=iterations, timezone=timezone)

    @benchmark
    def my_function():
        pass

    # call the function
    my_function()

    results = pandas.read_json(benchmark.outfile.getvalue(), lines=True)
    assert (results['function_name'] == 'my_function').all()
    runtimes = results['finish_time'] - results['start_time']
    assert (runtimes > datetime.timedelta(0)).all()
    assert results['timezone'][0] == str(timezone)

    assert len(results['run_durations'][0]) == iterations
    assert all(dur >= 0 for dur in results['run_durations'][0])
    assert sum(results['run_durations'][0]) < runtimes[0].total_seconds()


def test_capture_global_packages():
    @globals_bench
    def noop():
        pass

    noop()

    results = pandas.read_json(globals_bench.outfile.getvalue(), lines=True)

    # We should've captured microbench and pandas versions from top level
    # imports in this file
    assert results['package_versions'][0]['microbench'] == \
           str(microbench_version)
    assert results['package_versions'][0]['pandas'] == pandas.__version__


def test_capture_packages_importlib():
    class PkgBench(MicroBench, MBInstalledPackages):
        capture_paths = True

    pkg_bench = PkgBench()

    @pkg_bench
    def noop():
        pass

    noop()

    results = pandas.read_json(pkg_bench.outfile.getvalue(), lines=True)
    assert pandas.__version__ == results['package_versions'][0]['pandas']


def test_telemetry():
    class TelemBench(MicroBench):
        @staticmethod
        def telemetry(process):
            return process.memory_full_info()._asdict()

    telem_bench = TelemBench()

    @telem_bench
    def noop():
        pass

    noop()

    # Check telemetry thread completed
    assert not telem_bench._telemetry_thread.is_alive()

    # Check some telemetry was captured
    results = pandas.read_json(telem_bench.outfile.getvalue(), lines=True)
    assert len(results['telemetry']) > 0


def test_unjsonencodable_arg_kwarg_retval():
    class Bench(MicroBench, MBFunctionCall, MBReturnValue):
        pass

    bench = Bench()

    @bench
    def dummy(arg1, arg2):
        return object()

    with warnings.catch_warnings(record=True) as w:
        # Run a function with unencodable arg, kwarg, return value
        dummy(object(), arg2=object())

        # Check that we get three warnings - one each for args,
        # kwargs, return value
        assert len(w) == 3
        assert all(issubclass(w_.category, JSONEncodeWarning) for w_ in w)


    results = pandas.read_json(bench.outfile.getvalue(), lines=True)
    assert results['args'][0] == [_UNENCODABLE_PLACEHOLDER_VALUE]
    assert results['kwargs'][0] == {'arg2': _UNENCODABLE_PLACEHOLDER_VALUE}
    assert results['return_value'][0] == _UNENCODABLE_PLACEHOLDER_VALUE


def test_custom_jsonencoder():
    # A custom class which can't be encoded to JSON by default
    class MyCustomClass(object):
        def __init__(self, message):
            self.message = message

        def __str__(self):
            return f'<MyCustomClass "{self.message}">'

    # Implement JSON encoding for objects of the above class
    class CustomJSONEncoder(JSONEncoder):
        def default(self, o):
            if isinstance(o, MyCustomClass):
                return str(o)

            return super().default(o)

    class Bench(MicroBench, MBReturnValue):
        pass

    # Create a benchmark suite with custom JSON encoder
    bench = Bench(json_encoder=CustomJSONEncoder)

    # Custom object which requires special handling for JSONEncoder
    obj = MyCustomClass('test message')

    @bench
    def dummy():
        return obj

    dummy()

    results = pandas.read_json(bench.outfile.getvalue(), lines=True)
    assert results['return_value'][0] == str(obj)
