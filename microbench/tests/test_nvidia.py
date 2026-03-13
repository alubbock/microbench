import subprocess
import unittest

import pytest

from microbench import MBNvidiaSmi, MicroBench

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


def test_nvidia_gpus_empty_raises():
    """An empty nvidia_gpus tuple must raise ValueError."""

    class Bench(MicroBench, MBNvidiaSmi):
        nvidia_gpus = ()

    bench = Bench()

    @bench
    def noop():
        pass

    with pytest.raises(ValueError, match='nvidia_gpus cannot be empty'):
        noop()


def test_nvidia_gpus_invalid_format_raises():
    """A GPU identifier containing whitespace must raise ValueError."""

    class Bench(MicroBench, MBNvidiaSmi):
        nvidia_gpus = ('invalid gpu id',)

    bench = Bench()

    @bench
    def noop():
        pass

    with pytest.raises(ValueError, match='nvidia_gpus must be'):
        noop()
