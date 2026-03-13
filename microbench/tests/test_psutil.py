from unittest.mock import patch

import pytest

import microbench
from microbench import MBHostCpuCores, MBHostRamTotal, MicroBench


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


def test_psutil_missing_raises():
    """_NeedsPsUtil._check_psutil raises ImportError when psutil is unavailable."""
    with patch.object(microbench, 'psutil', None):
        with pytest.raises(ImportError, match='psutil'):
            microbench._NeedsPsUtil._check_psutil()
