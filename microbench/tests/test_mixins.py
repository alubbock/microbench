import os
import sys
from unittest.mock import patch

import pandas
import pytest

from microbench import (
    MBFileHash,
    MBGitInfo,
    MBInstalledPackages,
    MBLineProfiler,
    MBLoadedModules,
    MBPeakMemory,
    MBSlurmInfo,
    MicroBench,
)
from microbench import __version__ as microbench_version

from .globals_capture import globals_bench


def test_mb_slurm_info():
    class Bench(MicroBench, MBSlurmInfo):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    slurm_env = {
        'SLURM_JOB_ID': '12345',
        'SLURM_ARRAY_TASK_ID': '3',
        'SLURM_NODELIST': 'gpu-node-01',
        'NOT_SLURM': 'ignored',
    }

    with patch.dict(os.environ, slurm_env, clear=False):
        noop()

    results = bench.get_results()
    slurm = results['slurm'][0]
    assert slurm['job_id'] == '12345'
    assert slurm['array_task_id'] == '3'
    assert slurm['nodelist'] == 'gpu-node-01'
    assert 'not_slurm' not in slurm


def test_mb_slurm_info_empty():
    """slurm field is an empty dict when no SLURM_* vars are set."""

    class Bench(MicroBench, MBSlurmInfo):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    # Strip any real SLURM vars that might be in the test environment
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith('SLURM_')}
    with patch.dict(os.environ, clean_env, clear=True):
        noop()

    results = bench.get_results()
    assert results['slurm'][0] == {}


def test_mb_loaded_modules():
    """loaded_modules captures name/version pairs from LOADEDMODULES."""

    class Bench(MicroBench, MBLoadedModules):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    with patch.dict(
        os.environ,
        {'LOADEDMODULES': 'gcc/12.2.0:openmpi/4.1.5:python/3.10.4'},
        clear=False,
    ):
        noop()

    modules = bench.get_results()['loaded_modules'][0]
    assert modules['gcc'] == '12.2.0'
    assert modules['openmpi'] == '4.1.5'
    assert modules['python'] == '3.10.4'


def test_mb_loaded_modules_empty():
    """loaded_modules is an empty dict when LOADEDMODULES is unset."""

    class Bench(MicroBench, MBLoadedModules):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    clean_env = {k: v for k, v in os.environ.items() if k != 'LOADEDMODULES'}
    with patch.dict(os.environ, clean_env, clear=True):
        noop()

    assert bench.get_results()['loaded_modules'][0] == {}


def test_mb_loaded_modules_no_version():
    """Module entries without a version store an empty string."""

    class Bench(MicroBench, MBLoadedModules):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    with patch.dict(os.environ, {'LOADEDMODULES': 'null:gcc/12.2.0'}, clear=False):
        noop()

    modules = bench.get_results()['loaded_modules'][0]
    assert modules['null'] == ''
    assert modules['gcc'] == '12.2.0'


def test_mb_loaded_modules_version_with_slash():
    """Module versions containing slashes are captured in full."""

    class Bench(MicroBench, MBLoadedModules):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    # Some module systems use hierarchical names like GCC/12.2.0-GCCcore-12.2.0
    with patch.dict(
        os.environ,
        {'LOADEDMODULES': 'GCC/12.2.0-GCCcore-12.2.0'},
        clear=False,
    ):
        noop()

    modules = bench.get_results()['loaded_modules'][0]
    assert modules['GCC'] == '12.2.0-GCCcore-12.2.0'


def test_capture_global_packages():
    @globals_bench
    def noop():
        pass

    noop()

    results = globals_bench.get_results()

    # We should've captured microbench and pandas versions from top level
    # imports in this file
    assert results['package_versions'][0]['microbench'] == str(microbench_version)
    assert results['package_versions'][0]['pandas'] == pandas.__version__


def test_capture_packages_importlib():
    class PkgBench(MicroBench, MBInstalledPackages):
        capture_paths = True

    pkg_bench = PkgBench()

    @pkg_bench
    def noop():
        pass

    noop()

    results = pkg_bench.get_results()
    assert pandas.__version__ == results['package_versions'][0]['pandas']


def test_capture_packages_self_imports_metadata():
    """capture_packages imports importlib.metadata itself, not via prior imports."""
    import sys

    # Evict importlib.metadata so the method's own import statement is exercised.
    # Without 'import importlib.metadata' inside capture_packages, this would raise
    # AttributeError: module 'importlib' has no attribute 'metadata'.
    saved = sys.modules.pop('importlib.metadata', None)
    try:

        class PkgBench(MicroBench, MBInstalledPackages):
            pass

        bench = PkgBench()

        @bench
        def noop():
            pass

        noop()

        results = bench.get_results()
        assert isinstance(results['package_versions'][0], dict)
        assert len(results['package_versions'][0]) > 0
    finally:
        if saved is not None:
            sys.modules['importlib.metadata'] = saved


def test_mb_peak_memory():
    class Bench(MicroBench, MBPeakMemory):
        pass

    bench = Bench()

    @bench
    def allocate():
        return [0] * 100_000

    allocate()

    results = bench.get_results()
    assert results['peak_memory_bytes'][0] > 0


def test_mb_peak_memory_stops_tracemalloc():
    """MBPeakMemory stops tracemalloc after the call if it was not already running."""
    import tracemalloc

    assert not tracemalloc.is_tracing()

    class Bench(MicroBench, MBPeakMemory):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    noop()

    assert not tracemalloc.is_tracing()


def test_mb_peak_memory_preserves_existing_trace():
    """MBPeakMemory leaves tracemalloc running if it was already active."""
    import tracemalloc

    tracemalloc.start()
    try:

        class Bench(MicroBench, MBPeakMemory):
            pass

        bench = Bench()

        @bench
        def noop():
            pass

        noop()

        assert tracemalloc.is_tracing()
        results = bench.get_results()
        assert 'peak_memory_bytes' in results.columns
    finally:
        tracemalloc.stop()


# ---------------------------------------------------------------------------
# MBGitInfo
# ---------------------------------------------------------------------------

_GIT_TOPLEVEL = b'/home/user/project\n'
_GIT_STATUS_CLEAN = (
    '# branch.oid abc123def456abc123def456abc123def456abc1\n# branch.head main\n'
)
_GIT_STATUS_DIRTY = _GIT_STATUS_CLEAN + ' M modified_file.py\n'
_GIT_STATUS_DETACHED = (
    '# branch.oid abc123def456abc123def456abc123def456abc1\n# branch.head (detached)\n'
)


def _git_mock(status_output):
    """Return a subprocess.check_output side_effect that handles both git calls."""

    def side_effect(cmd, **kwargs):
        if 'rev-parse' in cmd:
            return _GIT_TOPLEVEL
        return status_output.encode()

    return side_effect


def test_mb_git_info():
    """MBGitInfo captures repo, commit, branch, and dirty=False from a clean repo."""

    class Bench(MicroBench, MBGitInfo):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    with patch('subprocess.check_output', side_effect=_git_mock(_GIT_STATUS_CLEAN)):
        noop()

    git_info = bench.get_results()['git_info'][0]
    assert git_info['repo'] == '/home/user/project'
    assert git_info['commit'] == 'abc123def456abc123def456abc123def456abc1'
    assert git_info['branch'] == 'main'
    assert git_info['dirty'] is False


def test_mb_git_info_dirty():
    """MBGitInfo sets dirty=True when the working tree has uncommitted changes."""

    class Bench(MicroBench, MBGitInfo):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    with patch('subprocess.check_output', side_effect=_git_mock(_GIT_STATUS_DIRTY)):
        noop()

    assert bench.get_results()['git_info'][0]['dirty'] is True


def test_mb_git_info_detached_head():
    """MBGitInfo stores an empty string for branch in detached HEAD state."""

    class Bench(MicroBench, MBGitInfo):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    with patch('subprocess.check_output', side_effect=_git_mock(_GIT_STATUS_DETACHED)):
        noop()

    assert bench.get_results()['git_info'][0]['branch'] == ''


def test_mb_git_info_no_git_raises():
    """MBGitInfo propagates FileNotFoundError when git is not on PATH."""

    class Bench(MicroBench, MBGitInfo):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    with patch(
        'subprocess.check_output', side_effect=FileNotFoundError('git not found')
    ):
        with pytest.raises(FileNotFoundError):
            noop()


def test_mb_git_info_default_uses_script_dir():
    """MBGitInfo defaults to the directory of sys.argv[0], not CWD."""
    captured_kwargs = []

    def side_effect(cmd, **kwargs):
        captured_kwargs.append(kwargs)
        return _GIT_TOPLEVEL if 'rev-parse' in cmd else _GIT_STATUS_CLEAN.encode()

    class Bench(MicroBench, MBGitInfo):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    script = '/some/project/script.py'
    expected_cwd = os.path.dirname(os.path.abspath(script))

    with patch.object(sys, 'argv', [script]):
        with patch('subprocess.check_output', side_effect=side_effect):
            noop()

    assert all(kw.get('cwd') == expected_cwd for kw in captured_kwargs)


def test_mb_git_info_custom_path():
    """MBGitInfo passes git_repo as cwd to subprocess."""
    captured_kwargs = []

    def side_effect(cmd, **kwargs):
        captured_kwargs.append(kwargs)
        return _GIT_TOPLEVEL if 'rev-parse' in cmd else _GIT_STATUS_CLEAN.encode()

    class Bench(MicroBench, MBGitInfo):
        git_repo = '/some/repo'

    bench = Bench()

    @bench
    def noop():
        pass

    with patch('subprocess.check_output', side_effect=side_effect):
        noop()

    assert all(kw.get('cwd') == '/some/repo' for kw in captured_kwargs)


# ---------------------------------------------------------------------------
# MBFileHash
# ---------------------------------------------------------------------------


def test_mb_file_hash_specific_file(tmp_path):
    """MBFileHash records the SHA-256 digest of a specified file."""
    import hashlib

    content = b'hello microbench'
    target = tmp_path / 'data.txt'
    target.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()

    class Bench(MicroBench, MBFileHash):
        hash_files = [str(target)]

    bench = Bench()

    @bench
    def noop():
        pass

    noop()

    results = bench.get_results()
    assert results['file_hashes'][0] == {str(target): expected}


def test_mb_file_hash_multiple_files(tmp_path):
    """MBFileHash records digests for all specified files."""
    import hashlib

    files = {}
    for name in ('a.txt', 'b.txt'):
        p = tmp_path / name
        p.write_bytes(name.encode())
        files[str(p)] = hashlib.sha256(name.encode()).hexdigest()

    class Bench(MicroBench, MBFileHash):
        hash_files = list(files.keys())

    bench = Bench()

    @bench
    def noop():
        pass

    noop()

    results = bench.get_results()
    assert results['file_hashes'][0] == files


def test_mb_file_hash_custom_algorithm(tmp_path):
    """MBFileHash respects the hash_algorithm class attribute."""
    import hashlib

    content = b'test data'
    target = tmp_path / 'script.py'
    target.write_bytes(content)

    expected = hashlib.md5(content).hexdigest()

    class Bench(MicroBench, MBFileHash):
        hash_files = [str(target)]
        hash_algorithm = 'md5'

    bench = Bench()

    @bench
    def noop():
        pass

    noop()

    results = bench.get_results()
    assert results['file_hashes'][0] == {str(target): expected}


def test_mb_file_hash_default_uses_argv(tmp_path):
    """MBFileHash defaults to sys.argv[0] when hash_files is not set."""
    import hashlib

    content = b'print("hello")'
    script = tmp_path / 'run.py'
    script.write_bytes(content)

    expected = hashlib.sha256(content).hexdigest()

    class Bench(MicroBench, MBFileHash):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    with patch.object(sys, 'argv', [str(script)]):
        noop()

    results = bench.get_results()
    assert results['file_hashes'][0] == {str(script): expected}


def test_mb_file_hash_no_argv_empty(tmp_path):
    """MBFileHash records an empty dict when sys.argv is empty."""

    class Bench(MicroBench, MBFileHash):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    with patch.object(sys, 'argv', []):
        noop()

    results = bench.get_results()
    assert results['file_hashes'][0] == {}


def test_mb_file_hash_interactive_argv_empty_string(tmp_path):
    """MBFileHash records an empty dict in interactive Python (argv[0] == '')."""

    class Bench(MicroBench, MBFileHash):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    with patch.object(sys, 'argv', ['']):
        noop()

    results = bench.get_results()
    assert results['file_hashes'][0] == {}


def test_mb_file_hash_missing_file_raises(tmp_path):
    """MBFileHash raises FileNotFoundError for a path that does not exist."""

    class Bench(MicroBench, MBFileHash):
        hash_files = [str(tmp_path / 'nonexistent.py')]

    bench = Bench()

    @bench
    def noop():
        pass

    with pytest.raises(FileNotFoundError):
        noop()


def test_record_mblineprofiler_raises():
    """MBLineProfiler raises NotImplementedError with bench.record()."""

    class Bench(MicroBench, MBLineProfiler):
        pass

    bench = Bench()

    with pytest.raises(NotImplementedError, match='MBLineProfiler'):
        with bench.record('block'):
            pass
