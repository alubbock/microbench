from unittest.mock import patch

import pytest

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
    # psutil.cpu_count(logical=True) can return None on some platforms
    # (e.g. macOS with psutil 7.x), so check that at least one is set
    logical = results['cpu_cores_logical'][0]
    physical = results['cpu_cores_physical'][0]
    assert (logical is not None and logical >= 1) or (
        physical is not None and physical >= 1
    ), f'Expected at least one core count, got logical={logical}, physical={physical}'
    assert results['ram_total'][0] > 0


def test_psutil_missing_raises():
    """_NeedsPsUtil._check_psutil raises ImportError when psutil is unavailable."""
    import microbench.mixins
    from microbench.mixins import _NeedsPsUtil

    with patch.object(microbench.mixins, 'psutil', None):
        with pytest.raises(ImportError, match='psutil'):
            _NeedsPsUtil._check_psutil()
