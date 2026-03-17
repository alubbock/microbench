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
    assert 'nvidia' in results[0]
    assert len(results[0]['nvidia']) > 0
    assert 'gpu_name' in results[0]['nvidia'][0]
    assert 'memory.total' in results[0]['nvidia'][0]


def test_nvidia_custom_attributes():
    """Custom nvidia_attributes are passed through to nvidia-smi."""

    class Bench(MicroBench, MBNvidiaSmi):
        nvidia_attributes = ('gpu_name',)

    bench = Bench()

    @bench
    def noop():
        pass

    with patch('subprocess.check_output', return_value=_FAKE_NVIDIA_SMI_OUTPUT):
        noop()

    results = bench.get_results()
    assert 'nvidia' in results[0]
    assert results[0]['nvidia'][0]['gpu_name'] == 'Tesla T4'


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


def test_nvidia_gpus_integer_accepted():
    """Integer GPU indexes must be accepted (README documents this usage)."""

    class Bench(MicroBench, MBNvidiaSmi):
        nvidia_gpus = (0,)

    bench = Bench()

    @bench
    def noop():
        pass

    with patch('subprocess.check_output', return_value=_FAKE_NVIDIA_SMI_OUTPUT):
        noop()


def test_nvidia_default_attributes_command():
    """Default attributes produce --query-gpu=uuid,gpu_name,memory.total."""

    class Bench(MicroBench, MBNvidiaSmi):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    with patch(
        'subprocess.check_output', return_value=_FAKE_NVIDIA_SMI_OUTPUT
    ) as mock_co:
        noop()

    cmd = mock_co.call_args[0][0]
    assert '--query-gpu=uuid,gpu_name,memory.total' in cmd
    assert '-i' not in cmd


def test_nvidia_custom_attributes_command():
    """Custom nvidia_attributes appear in the --query-gpu flag."""

    class Bench(MicroBench, MBNvidiaSmi):
        nvidia_attributes = ('gpu_name', 'power.draw')

    bench = Bench()

    @bench
    def noop():
        pass

    fake_output = b'GPU-abc123, Tesla T4, 300.00 W\n'
    with patch('subprocess.check_output', return_value=fake_output) as mock_co:
        noop()

    cmd = mock_co.call_args[0][0]
    assert '--query-gpu=uuid,gpu_name,power.draw' in cmd


def test_nvidia_gpus_uuid_accepted():
    """UUID-format GPU IDs are passed via the -i flag."""

    class Bench(MicroBench, MBNvidiaSmi):
        nvidia_gpus = ('GPU-abc123def456',)

    bench = Bench()

    @bench
    def noop():
        pass

    with patch(
        'subprocess.check_output', return_value=_FAKE_NVIDIA_SMI_OUTPUT
    ) as mock_co:
        noop()

    cmd = mock_co.call_args[0][0]
    assert '-i' in cmd
    assert cmd[cmd.index('-i') + 1] == 'GPU-abc123def456'


def test_nvidia_gpus_multiple_joined():
    """Multiple GPU IDs are joined with commas in the -i flag."""

    class Bench(MicroBench, MBNvidiaSmi):
        nvidia_gpus = (0, 1)

    bench = Bench()

    @bench
    def noop():
        pass

    fake_output = b'GPU-abc123, Tesla T4, 16160 MiB\nGPU-def456, Tesla T4, 16160 MiB\n'
    with patch('subprocess.check_output', return_value=fake_output) as mock_co:
        noop()

    cmd = mock_co.call_args[0][0]
    assert '-i' in cmd
    assert cmd[cmd.index('-i') + 1] == '0,1'
