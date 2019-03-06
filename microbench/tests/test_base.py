from microbench import MicroBench, MBFunctionCall, MBPythonVersion, MBHostInfo
from microbench import __version__ as microbench_version
import io
import pandas
import datetime
from .globals_capture import globals_bench


def test_function():
    output = io.StringIO()

    class MyBench(MicroBench, MBFunctionCall, MBPythonVersion, MBHostInfo):
        outfile = output
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

    results = pandas.read_json(output.getvalue(), lines=True, )
    assert (results['function_name'] == 'my_function').all()
    assert (results['pandas_version'] == pandas.__version__).all()
    runtimes = results['finish_time'] - results['start_time']
    assert (runtimes > datetime.timedelta(0)).all()


def test_capture_global_packages():
    @globals_bench
    def noop():
        pass

    noop()

    results = pandas.read_json(globals_bench.outfile.getvalue(), lines=True)

    # We should've captured microbench and pandas versions from top level
    # imports in this file
    assert (results['microbench_version'] == str(microbench_version)).all()
    assert (results['pandas_version'] == pandas.__version__).all()
