from microbench import MicroBench, MBHostCpuCores, MBHostRamTotal
import pandas


def test_psutil():
    class MyBench(MicroBench, MBHostCpuCores, MBHostRamTotal):
        pass

    mybench = MyBench()

    @mybench
    def test_func():
        pass

    test_func()

    results = mybench.get_results()
    assert results['cpu_cores_logical'][0] >= 1
    assert results['ram_total'][0] > 0
