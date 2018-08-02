from microbench import MicroBench, MBFunctionCall, MBPythonVersion, MBHostInfo
import io


def test_function():
    output = io.StringIO()

    class MyBench(MicroBench, MBFunctionCall, MBPythonVersion, MBHostInfo):
        outfile = output

    benchmark = MyBench(some_info='123')

    @benchmark
    def my_function():
        """ Inefficient function for testing """
        acc = 0
        for i in range(1000000):
            acc += i

        return acc

    for i in range(5):
        assert my_function() == 499999500000
