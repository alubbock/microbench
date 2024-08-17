from microbench import MicroBench, MBNvidiaSmi
import subprocess
import unittest
import pandas

try:
    subprocess.call(['nvidia-smi'])
    nvidia_smi_available = True
except FileNotFoundError:
    nvidia_smi_available = False


@unittest.skipIf(not nvidia_smi_available, 'nvidia-smi command not found')
def test_nvidia():
    class Bench(MicroBench, MBNvidiaSmi):
        pass

    bench = Bench()

    @bench
    def test():
        pass

    test()

    results = bench.get_results()
    assert 'nvidia_gpu_name' in results.columns
    assert 'nvidia_memory.total' in results.columns
