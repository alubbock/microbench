from microbench import MicroBench, MBFunctionCall, MBPythonVersion, MBHostInfo
import io
import pandas
import datetime

def test_function():
    output = io.StringIO()

    class MyBench(MicroBench, MBFunctionCall, MBPythonVersion, MBHostInfo):
        outfile = output
        capture_versions = (pandas, io)

    benchmark = MyBench(some_info='123')

    @benchmark
    def my_function():
        """ Inefficient function for testing """
        acc = 0
        for i in range(1000000):
            acc += i

        return acc

    for i in range(3):
        assert my_function() == 499999500000

    results = pandas.read_json(output.getvalue(), lines=True, )
    assert (results['function_name'] == 'my_function').all()
    assert (results['pandas_version'] == pandas.__version__).all()
    runtimes = results['finish_time'] - results['start_time']
    assert (runtimes > datetime.timedelta(0)).all()
