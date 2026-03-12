import subprocess
import unittest
from unittest.mock import patch

import pytest

from microbench import MBNvidiaSmi, MicroBench

try:
    subprocess.call(['nvidia-smi'])
    nvidia_smi_available = True
except FileNotFoundError:
    nvidia_smi_available = False

# Fake nvidia-smi CSV output: uuid, gpu_name, memory.total
_FAKE_NVIDIA_SMI_OUTPUT = b'GPU-abc123, Tesla T4, 16160 MiB\n'


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


def test_nvidia_unknown_attribute_raises():
    """Specifying an unknown nvidia_attribute must raise ValueError."""

    class Bench(MicroBench, MBNvidiaSmi):
        nvidia_attributes = ('gpu_name', 'nonexistent_attr')

    bench = Bench()

    @bench
    def noop():
        pass

    with pytest.raises(ValueError, match='nonexistent_attr'):
        noop()


def test_nvidia_known_attribute_does_not_raise():
    """Specifying only known attributes must not raise a ValueError."""

    class Bench(MicroBench, MBNvidiaSmi):
        nvidia_attributes = ('gpu_name',)

    bench = Bench()

    @bench
    def noop():
        pass

    with patch('subprocess.check_output', return_value=_FAKE_NVIDIA_SMI_OUTPUT):
        noop()

    results = bench.get_results()
    assert 'nvidia_gpu_name' in results.columns


def test_nvidia_default_attribute_not_flagged_as_unknown():
    """Omitting a default attribute (memory.total) must not raise (B2 regression check).

    With the original bug, set(available).difference(user_attrs) would flag
    'memory.total' as 'unknown' simply because the user didn't include it.
    """

    class Bench(MicroBench, MBNvidiaSmi):
        # Only request gpu_name, intentionally omitting memory.total
        nvidia_attributes = ('gpu_name',)

    bench = Bench()

    @bench
    def noop():
        pass

    # Should NOT raise; memory.total being absent from user's list is fine
    with patch('subprocess.check_output', return_value=_FAKE_NVIDIA_SMI_OUTPUT):
        noop()
