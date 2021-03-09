from microbench import MicroBench, MBFunctionCall, MBPythonVersion, \
    MBHostInfo, MBInstalledPackages
from microbench import __version__ as microbench_version
import io
import pandas
import datetime
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

    results = pandas.read_json(benchmark.outfile.getvalue(), lines=True, )
    assert (results['function_name'] == 'my_function').all()
    assert results['package_versions'][0]['pandas'] == pandas.__version__
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
    assert results['package_versions'][0]['microbench'] == \
           str(microbench_version)
    assert results['package_versions'][0]['pandas'] == pandas.__version__


def test_capture_packages_pkg_resources():
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
            return {process.memory_full_info()}

    telem_bench = TelemBench()

    @telem_bench
    def noop():
        pass

    noop()

    # Check telemetry thread completed
    assert not telem_bench._telemetry_thread.isAlive()

    # Check some telemetry was captured
    results = pandas.read_json(telem_bench.outfile.getvalue(), lines=True)
    assert len(results['telemetry']) > 0
