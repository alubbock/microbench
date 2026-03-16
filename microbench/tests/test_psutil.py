from unittest.mock import patch

import microbench._mixins
from microbench import MBHostInfo, MicroBench


def test_mbhostinfo_with_psutil():
    """MBHostInfo captures all five host fields when psutil is available."""

    class MyBench(MicroBench, MBHostInfo):
        pass

    mybench = MyBench()

    @mybench
    def test_func():
        pass

    test_func()

    host = mybench.get_results()[0]['host']
    assert host['hostname']
    assert host['os']
    logical = host['cpu_cores_logical']
    physical = host['cpu_cores_physical']
    # psutil.cpu_count(logical=True) can return None on some platforms
    # (e.g. macOS with psutil 7.x), so check at least one is non-None
    assert (logical is not None and logical >= 1) or (
        physical is not None and physical >= 1
    ), f'Expected at least one core count, got logical={logical}, physical={physical}'
    assert host['ram_total'] > 0


def test_mbhostinfo_without_psutil():
    """MBHostInfo silently omits psutil fields when psutil is unavailable."""

    class MyBench(MicroBench, MBHostInfo):
        pass

    mybench = MyBench()

    @mybench
    def test_func():
        pass

    with patch.object(microbench._mixins, 'psutil', None):
        test_func()

    host = mybench.get_results()[0]['host']
    assert host['hostname']
    assert host['os']
    assert 'cpu_cores_logical' not in host
    assert 'cpu_cores_physical' not in host
    assert 'ram_total' not in host
