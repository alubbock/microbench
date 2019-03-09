import io
from microbench import MicroBench, MBHostCpuCores, MBHostRamTotal
import pandas


def test_psutil():
    output = io.StringIO()

    class MyBench(MicroBench, MBHostCpuCores, MBHostRamTotal):
        outfile = output

    mybench = MyBench()

    @mybench
    def test_func():
        pass

    test_func()

    results = pandas.read_json(mybench.outfile.getvalue(), lines=True)
    assert results['cpu_cores_logical'][0] >= 1
    assert results['ram_total'][0] > 0
