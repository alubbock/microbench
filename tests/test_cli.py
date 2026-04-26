import io
import json
import os
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest

from microbench import __version__
from microbench.__main__ import main


class _FakeRusage:
    def __init__(
        self,
        *,
        utime=0.0,
        stime=0.0,
        maxrss=1,
        minflt=0,
        majflt=0,
        inblock=0,
        oublock=0,
        nvcsw=0,
        nivcsw=0,
    ):
        self.ru_utime = utime
        self.ru_stime = stime
        self.ru_maxrss = maxrss
        self.ru_minflt = minflt
        self.ru_majflt = majflt
        self.ru_inblock = inblock
        self.ru_oublock = oublock
        self.ru_nvcsw = nvcsw
        self.ru_nivcsw = nivcsw


class _MockPipe:
    """Iterable pipe mock that supports .close(), as real subprocess pipes do."""

    def __init__(self, lines):
        self._iter = iter(lines)
        self.closed = False

    def __iter__(self):
        return self._iter

    def close(self):
        self.closed = True


def _make_mock_popen(returncode=0, stdout_lines=None, stderr_lines=None, pid=12345):
    """Create a mock Popen process."""
    mock_proc = MagicMock()
    mock_proc.returncode = returncode
    mock_proc.pid = pid
    mock_proc.stdout = _MockPipe(stdout_lines) if stdout_lines is not None else None
    mock_proc.stderr = _MockPipe(stderr_lines) if stderr_lines is not None else None
    return mock_proc


def _run_main(argv, mock_returncode=0):
    """Run main() with a mocked subprocess and captured stdout."""
    mock_proc = _make_mock_popen(returncode=mock_returncode)

    buf = io.StringIO()
    wait_status = 0 if mock_returncode == 0 else mock_returncode << 8
    fake_wait4 = (mock_proc.pid, wait_status, _FakeRusage())
    with patch('subprocess.Popen', return_value=mock_proc) as mock_popen:
        with patch('os.wait4', return_value=fake_wait4, create=True):
            with patch('sys.stdout', buf):
                with pytest.raises(SystemExit) as exc:
                    main(argv)
    return exc.value.code, json.loads(buf.getvalue()), mock_popen


def _patch_wait4_success(mock_proc, *, rusage=None, status=0):
    if rusage is None:
        rusage = _FakeRusage()
    return patch('os.wait4', return_value=(mock_proc.pid, status, rusage), create=True)


def _patch_wait4_sleep(mock_proc, delay, *, status=0, rusage=None):
    if rusage is None:
        rusage = _FakeRusage()

    def _wait4(pid, options):
        import time

        time.sleep(delay)
        return (mock_proc.pid, status, rusage)

    return patch('os.wait4', side_effect=_wait4)


def _patch_wait4_sequence(*results):
    iterator = iter(results)

    def _wait4(pid, options):
        result = next(iterator)
        if callable(result):
            return result(pid, options)
        return result

    return patch('os.wait4', side_effect=_wait4, create=True)


def test_cli_records_command_and_timing():
    """CLI records command list, returncode, and standard timing fields."""
    code, record, _ = _run_main(['--', 'sleep', '1'])

    assert code == 0
    assert record['call']['invocation'] == 'CLI'
    assert record['call']['command'] == ['sleep', '1']
    assert record['call']['returncode'] == [0]
    assert 'start_time' in record['call']
    assert 'finish_time' in record['call']
    assert 'durations' in record['call']
    assert record['call']['name'] == 'sleep'


def test_cli_nonzero_returncode():
    """CLI exits with the subprocess returncode."""
    code, record, _ = _run_main(['--', 'false'], mock_returncode=1)

    assert code == 1
    assert record['call']['returncode'] == [1]


def test_cli_custom_field():
    """--field KEY=VALUE adds metadata to every record."""
    _, record, _ = _run_main(['--field', 'experiment=run-1', '--', 'true'])

    assert record['experiment'] == 'run-1'


def test_cli_multiple_fields():
    """Multiple --field flags all appear in the record."""
    _, record, _ = _run_main(
        ['--field', 'experiment=run-1', '--field', 'trial=3', '--', 'true']
    )

    assert record['experiment'] == 'run-1'
    assert record['trial'] == '3'


def test_cli_default_mixins_include_host_info():
    """Default configuration includes MBHostInfo fields."""
    _, record, _ = _run_main(['--', 'true'])

    assert 'hostname' in record['host']
    assert 'os' in record['host']


def test_cli_default_mixins_include_slurm():
    """Default configuration includes MBSlurmInfo (slurm field)."""
    _, record, _ = _run_main(['--', 'true'])

    assert 'slurm' in record


def test_cli_default_mixins_include_loaded_modules():
    """Default configuration includes MBLoadedModules (loaded_modules field)."""
    _, record, _ = _run_main(['--', 'true'])

    assert 'loaded_modules' in record


def test_cli_default_mixins_include_working_dir():
    """Default configuration includes MBWorkingDir (working_dir field)."""
    _, record, _ = _run_main(['--', 'true'])

    assert 'working_dir' in record['call']
    assert record['call']['working_dir'] == os.getcwd()


def test_cli_default_mixins_include_python_info():
    """Default configuration includes MBPythonInfo (python field)."""
    _, record, _ = _run_main(['--', 'true'])

    assert 'python' in record
    assert 'version' in record['python']
    assert 'prefix' in record['python']
    assert 'executable' in record['python']


def test_cli_explicit_mixin_replaces_defaults():
    """Specifying --mixin replaces the default mixin set."""
    _, record, _ = _run_main(['--mixin', 'python-info', '--', 'true'])

    assert 'python' in record
    # Default mixins should not be present
    assert 'host' not in record
    assert 'slurm' not in record


def test_cli_mixin_defaults_keyword_alone():
    """--mixin defaults alone is equivalent to omitting --mixin."""
    _, record_explicit, _ = _run_main(['--mixin', 'defaults', '--', 'true'])
    _, record_implicit, _ = _run_main(['--', 'true'])

    for key in ('python', 'host', 'slurm', 'loaded_modules'):
        assert key in record_explicit
    assert record_explicit['python']['version'] == record_implicit['python']['version']


def test_cli_mixin_defaults_keyword_extends_defaults():
    """--mixin defaults plus a default mixin on top works."""
    _, record, _ = _run_main(['--mixin', 'defaults', 'working-dir', '--', 'true'])

    # All defaults present
    assert 'python' in record
    assert 'host' in record
    assert 'slurm' in record
    assert 'loaded_modules' in record
    # working-dir is already in defaults, so no duplicate effect needed — just check
    assert 'working_dir' in record['call']


def test_cli_mixin_defaults_keyword_with_extra_mixin():
    """--mixin defaults file-hash produces defaults plus file-hash."""
    _, record, _ = _run_main(['--mixin', 'defaults', 'peak-memory', '--', 'true'])

    assert 'python' in record
    assert 'host' in record
    # peak-memory records to call.peak_memory_bytes
    assert 'peak_memory_bytes' in record['call']


def test_cli_mixin_defaults_keyword_deduplicates():
    """Repeating defaults in --mixin does not produce duplicate mixins."""
    _, record, _ = _run_main(['--mixin', 'defaults', 'defaults', '--', 'true'])

    assert 'python' in record
    assert 'host' in record


def test_cli_mixin_defaults_keyword_invalid_extra():
    """An unknown mixin alongside defaults exits non-zero."""
    with pytest.raises(SystemExit) as exc:
        main(['--mixin', 'defaults', 'no-such-mixin', '--', 'true'])
    assert exc.value.code != 0


def test_cli_outfile(tmp_path):
    """--outfile writes JSONL to the specified file."""
    outfile = tmp_path / 'results.jsonl'
    mock_proc = _make_mock_popen(returncode=0)

    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_success(mock_proc):
            with pytest.raises(SystemExit):
                main(['--outfile', str(outfile), '--', 'true'])

    record = json.loads(outfile.read_text())
    assert record['call']['command'] == ['true']
    assert record['call']['returncode'] == [0]


def test_cli_no_command_exits_with_error():
    """Omitting the command prints an error and exits non-zero."""
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0


def test_cli_show_mixins():
    """--show-mixins lists available mixins and exits cleanly."""
    buf = io.StringIO()
    with patch('sys.stdout', buf):
        with pytest.raises(SystemExit) as exc:
            main(['--show-mixins'])
    assert exc.value.code == 0
    output = buf.getvalue()
    assert 'host-info' in output
    assert 'python-info' in output
    assert '--hash-file' in output  # mixin-specific arg shown under file-hash
    assert '--git-repo' in output  # mixin-specific arg shown under git-info


def test_cli_capture_optional_on_by_default():
    """Capture failures are recorded in call.capture_errors, not raised."""

    def bad_capture(self, bm_data):
        raise RuntimeError('simulated capture failure')

    from microbench import MBHostInfo

    with patch.object(MBHostInfo, 'capture_hostname', bad_capture):
        _, record, _ = _run_main(['--mixin', 'MBHostInfo', '--', 'true'])

    assert 'capture_errors' in record['call']
    assert any(
        'capture_hostname' in e['method'] for e in record['call']['capture_errors']
    )


def test_cli_all_flag_includes_all_mixins():
    """--all includes every mixin in the CLI registry."""
    from microbench.__main__ import _get_mixin_map

    all_names = set(_get_mixin_map())

    # Patch every mixin's capture methods to no-ops to avoid external calls
    mock_proc = _make_mock_popen(returncode=0)
    buf = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_success(mock_proc):
            with patch('sys.stdout', buf):
                with pytest.raises(SystemExit):
                    with patch(
                        'subprocess.check_output', side_effect=Exception('skip')
                    ):
                        main(['--all', '--', 'true'])

    # At minimum the record should be written (even with capture_optional errors)
    record = json.loads(buf.getvalue())
    assert 'command' in record['call']
    assert len(all_names) > 2  # sanity: more than just defaults


def test_cli_includes_mb_run_id_and_version():
    """CLI records mb.run_id and mb.version in every record."""
    import re

    import microbench

    _, record, _ = _run_main(['--', 'true'])

    uuid_re = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    )
    assert uuid_re.match(record['mb']['run_id'])
    assert record['mb']['version'] == microbench.__version__


def test_cli_double_dash_separator():
    """-- separator is stripped before passing the command to subprocess."""
    _, _, mock_popen = _run_main(['--', 'echo', 'hello'])

    mock_popen.assert_called_once()
    called_cmd = mock_popen.call_args[0][0]
    assert called_cmd == ['echo', 'hello']


def test_cli_iterations():
    """--iterations N runs the command N times and produces N durations entries."""
    _, record, mock_popen = _run_main(['--iterations', '3', '--', 'true'])

    assert mock_popen.call_count == 3
    assert len(record['call']['durations']) == 3
    assert len(record['call']['returncode']) == 3


def test_cli_warmup():
    """--warmup N runs the command N extra times before timing begins."""
    _, record, mock_popen = _run_main(['--warmup', '2', '--', 'true'])

    # 2 warmup calls + 1 timed call
    assert mock_popen.call_count == 3
    assert len(record['call']['durations']) == 1
    assert len(record['call']['returncode']) == 1


def test_cli_iterations_and_warmup():
    """--iterations and --warmup together produce the right call count."""
    _, record, mock_popen = _run_main(
        ['--iterations', '4', '--warmup', '2', '--', 'true']
    )

    assert mock_popen.call_count == 6
    assert len(record['call']['durations']) == 4
    assert len(record['call']['returncode']) == 4


def test_cli_returncode_is_first_nonzero_across_iterations():
    """Process exits with the first non-zero returncode seen across timed iterations."""
    mock_procs = [
        _make_mock_popen(returncode=0),
        _make_mock_popen(returncode=2),
        _make_mock_popen(returncode=1),
    ]
    buf = io.StringIO()
    with patch('subprocess.Popen', side_effect=mock_procs):
        with _patch_wait4_sequence(
            (mock_procs[0].pid, 0, _FakeRusage()),
            (mock_procs[1].pid, 2 << 8, _FakeRusage()),
            (mock_procs[2].pid, 1 << 8, _FakeRusage()),
        ):
            with patch('sys.stdout', buf):
                with pytest.raises(SystemExit) as exc:
                    main(['--iterations', '3', '--', 'true'])

    assert exc.value.code == 2
    assert json.loads(buf.getvalue())['call']['returncode'] == [0, 2, 1]


def test_cli_returncode_preserves_first_nonzero_even_if_later_is_larger():
    """A later larger returncode does not override the first failure."""
    mock_procs = [
        _make_mock_popen(returncode=0),
        _make_mock_popen(returncode=1),
        _make_mock_popen(returncode=2),
    ]
    buf = io.StringIO()
    with patch('subprocess.Popen', side_effect=mock_procs):
        with _patch_wait4_sequence(
            (mock_procs[0].pid, 0, _FakeRusage()),
            (mock_procs[1].pid, 1 << 8, _FakeRusage()),
            (mock_procs[2].pid, 2 << 8, _FakeRusage()),
        ):
            with patch('sys.stdout', buf):
                with pytest.raises(SystemExit) as exc:
                    main(['--iterations', '3', '--', 'true'])

    assert exc.value.code == 1
    assert json.loads(buf.getvalue())['call']['returncode'] == [0, 1, 2]


def test_cli_returncode_preserves_first_nonzero_signal_code():
    """Negative subprocess returncodes are also returned if they are first non-zero."""
    mock_procs = [
        _make_mock_popen(returncode=0),
        _make_mock_popen(returncode=-15),
        _make_mock_popen(returncode=1),
    ]
    buf = io.StringIO()
    with patch('subprocess.Popen', side_effect=mock_procs):
        with _patch_wait4_sequence(
            (mock_procs[0].pid, 0, _FakeRusage()),
            (mock_procs[1].pid, 15, _FakeRusage()),
            (mock_procs[2].pid, 1 << 8, _FakeRusage()),
        ):
            with patch('sys.stdout', buf):
                with pytest.raises(SystemExit) as exc:
                    main(['--iterations', '3', '--', 'true'])

    assert exc.value.code == -15
    assert json.loads(buf.getvalue())['call']['returncode'] == [0, -15, 1]


def test_cli_multiple_mixins():
    """Multiple space-separated mixins all take effect."""
    _, record, _ = _run_main(['--mixin', 'MBHostInfo', 'MBPythonInfo', '--', 'true'])

    assert 'hostname' in record['host']
    assert 'version' in record['python']


def test_cli_all_overrides_mixin():
    """--all takes precedence over --mixin."""
    mock_proc = _make_mock_popen(returncode=0)
    buf = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_success(mock_proc):
            with patch('sys.stdout', buf):
                with pytest.raises(SystemExit):
                    with patch(
                        'subprocess.check_output', side_effect=Exception('skip')
                    ):
                        main(['--mixin', 'MBHostInfo', '--all', '--', 'true'])

    record = json.loads(buf.getvalue())
    # --all should activate every mixin, so slurm (from MBSlurmInfo) must be present
    # even though --mixin only listed MBHostInfo
    assert 'slurm' in record


def test_cli_field_invalid_format():
    """--field without = exits non-zero."""
    with pytest.raises(SystemExit) as exc:
        main(['--field', 'no-equals', '--', 'true'])
    assert exc.value.code != 0


def test_cli_field_value_with_equals():
    """--field preserves = characters in the value."""
    _, record, _ = _run_main(['--field', 'url=a=b=c', '--', 'true'])

    assert record['url'] == 'a=b=c'


def test_cli_field_values_are_strings():
    """--field values are always stored as strings, not coerced to other types."""
    _, record, _ = _run_main(
        ['--field', 'count=42', '--field', 'ratio=3.14', '--', 'true']
    )

    assert record['count'] == '42'
    assert isinstance(record['count'], str)
    assert record['ratio'] == '3.14'
    assert isinstance(record['ratio'], str)


def test_cli_no_stdout_capture_by_default():
    """stdout and stderr fields are absent unless --stdout/--stderr are given."""
    _, record, _ = _run_main(['--', 'echo', 'hello'])

    assert 'stdout' not in record.get('call', {})
    assert 'stderr' not in record.get('call', {})


def test_cli_capture_stdout_records_output():
    """--stdout records subprocess stdout as a list and re-prints to terminal."""
    mock_proc = _make_mock_popen(returncode=0, stdout_lines=[b'hello\n'])

    buf = io.StringIO()
    terminal = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc) as mock_popen:
        with _patch_wait4_success(mock_proc):
            with patch('sys.stdout', buf):
                with patch('sys.__stdout__', terminal):
                    with pytest.raises(SystemExit):
                        main(['--stdout', '--', 'echo', 'hello'])

    record = json.loads(buf.getvalue())
    assert record['call']['stdout'] == ['hello\n']
    assert 'stderr' not in record.get('call', {})
    assert terminal.getvalue() == 'hello\n'
    assert mock_popen.call_args[1].get('stdout') == subprocess.PIPE


def test_cli_capture_stdout_suppress():
    """--stdout=suppress records output without re-printing to terminal."""
    mock_proc = _make_mock_popen(returncode=0, stdout_lines=[b'hello\n'])

    buf = io.StringIO()
    terminal = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_success(mock_proc):
            with patch('sys.stdout', buf):
                with patch('sys.__stdout__', terminal):
                    with pytest.raises(SystemExit):
                        main(['--stdout=suppress', '--', 'echo', 'hello'])

    record = json.loads(buf.getvalue())
    assert record['call']['stdout'] == ['hello\n']
    assert terminal.getvalue() == ''  # nothing re-printed


def test_cli_capture_stderr_records_output():
    """--stderr records subprocess stderr as a list and re-prints to terminal."""
    mock_proc = _make_mock_popen(returncode=0, stderr_lines=[b'warning\n'])

    buf = io.StringIO()
    terminal_err = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_success(mock_proc):
            with patch('sys.stdout', buf):
                with patch('sys.__stderr__', terminal_err):
                    with pytest.raises(SystemExit):
                        main(['--stderr', '--', 'cmd'])

    record = json.loads(buf.getvalue())
    assert record['call']['stderr'] == ['warning\n']
    assert 'stdout' not in record.get('call', {})
    assert terminal_err.getvalue() == 'warning\n'


def test_cli_capture_stderr_suppress():
    """--stderr=suppress records stderr without re-printing."""
    mock_proc = _make_mock_popen(returncode=0, stderr_lines=[b'warning\n'])

    buf = io.StringIO()
    terminal_err = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_success(mock_proc):
            with patch('sys.stdout', buf):
                with patch('sys.__stderr__', terminal_err):
                    with pytest.raises(SystemExit):
                        main(['--stderr=suppress', '--', 'cmd'])

    record = json.loads(buf.getvalue())
    assert record['call']['stderr'] == ['warning\n']
    assert terminal_err.getvalue() == ''


def test_cli_capture_stdout_multiple_iterations():
    """With --iterations, stdout has one entry per timed iteration (warmup excluded)."""
    mock_procs = [
        _make_mock_popen(returncode=0, stdout_lines=[b'warmup\n']),  # warmup
        _make_mock_popen(returncode=0, stdout_lines=[b'run1\n']),
        _make_mock_popen(returncode=0, stdout_lines=[b'run2\n']),
        _make_mock_popen(returncode=0, stdout_lines=[b'run3\n']),
    ]

    buf = io.StringIO()
    with patch('subprocess.Popen', side_effect=mock_procs):
        with _patch_wait4_sequence(
            (mock_procs[0].pid, 0, _FakeRusage()),
            (mock_procs[1].pid, 0, _FakeRusage()),
            (mock_procs[2].pid, 0, _FakeRusage()),
            (mock_procs[3].pid, 0, _FakeRusage()),
        ):
            with patch('sys.stdout', buf):
                with patch('sys.__stdout__', io.StringIO()):
                    with pytest.raises(SystemExit):
                        main(
                            [
                                '--stdout',
                                '--warmup',
                                '1',
                                '--iterations',
                                '3',
                                '--',
                                'cmd',
                            ]
                        )

    record = json.loads(buf.getvalue())
    assert record['call']['stdout'] == ['run1\n', 'run2\n', 'run3\n']
    assert len(record['call']['stdout']) == len(record['call']['durations'])


def test_cli_capture_stdout_and_stderr():
    """--stdout and --stderr can be used together."""
    mock_proc = _make_mock_popen(
        returncode=0, stdout_lines=[b'out\n'], stderr_lines=[b'err\n']
    )

    buf = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_success(mock_proc):
            with patch('sys.stdout', buf):
                with patch('sys.__stdout__', io.StringIO()):
                    with patch('sys.__stderr__', io.StringIO()):
                        with pytest.raises(SystemExit):
                            main(['--stdout', '--stderr', '--', 'cmd'])

    record = json.loads(buf.getvalue())
    assert record['call']['stdout'] == ['out\n']
    assert record['call']['stderr'] == ['err\n']


def test_cli_capture_invalid_value():
    """--stdout=invalid exits non-zero."""
    with pytest.raises(SystemExit) as exc:
        main(['--stdout=invalid', '--', 'cmd'])
    assert exc.value.code != 0


def test_cli_iterations_zero_exits_error():
    """--iterations 0 is rejected."""
    with pytest.raises(SystemExit) as exc:
        main(['--iterations', '0', '--', 'true'])
    assert exc.value.code != 0


def test_cli_iterations_negative_exits_error():
    """--iterations -1 is rejected."""
    with pytest.raises(SystemExit) as exc:
        main(['--iterations', '-1', '--', 'true'])
    assert exc.value.code != 0


def test_cli_warmup_negative_exits_error():
    """--warmup -1 is rejected."""
    with pytest.raises(SystemExit) as exc:
        main(['--warmup', '-1', '--', 'true'])
    assert exc.value.code != 0


def test_cli_no_mixin_omits_all_metadata():
    """--no-mixin produces a record with no mixin fields."""
    _, record, _ = _run_main(['--no-mixin', '--', 'true'])

    assert 'host' not in record
    assert 'slurm' not in record
    assert 'python_version' not in record
    # Core fields still present
    assert 'command' in record['call']
    assert 'returncode' in record['call']
    assert 'durations' in record['call']


def test_cli_no_mixin_overrides_mixin():
    """--no-mixin takes precedence over --mixin."""
    _, record, _ = _run_main(['--no-mixin', '--mixin', 'MBHostInfo', '--', 'true'])

    assert 'host' not in record


def test_cli_all_and_no_mixin_are_mutually_exclusive():
    """--all and --no-mixin cannot be used together."""
    with pytest.raises(SystemExit) as exc:
        main(['--all', '--no-mixin', '--', 'true'])
    assert exc.value.code != 0


# ---------------------------------------------------------------------------
# --monitor-interval tests
# ---------------------------------------------------------------------------


def _make_mock_popen_for_monitor(returncode=0, pid=12345):
    """Popen mock that exposes a .pid and no pipes (no stdout/stderr capture)."""
    mock_proc = MagicMock()
    mock_proc.__enter__.return_value = mock_proc
    mock_proc.__exit__.return_value = False
    mock_proc.returncode = returncode
    mock_proc.pid = pid
    mock_proc.stdout = None
    mock_proc.stderr = None
    return mock_proc


def _run_main_with_monitor(argv, mock_pid=12345, mock_returncode=0, fake_samples=None):
    """
    Run main() with --monitor-interval, mocking both Popen and the monitor thread.

    fake_samples: list of sample dicts the thread will report (default: one sample).
    """
    if fake_samples is None:
        fake_samples = [{'timestamp': 'T0', 'cpu_percent': 12.5, 'rss_bytes': 1048576}]

    mock_proc = _make_mock_popen_for_monitor(returncode=mock_returncode, pid=mock_pid)

    # Patch _SubprocessMonitorThread so no real psutil calls happen.
    with patch('microbench.cli.main._SubprocessMonitorThread') as MockThread:
        mock_thread = MagicMock()
        mock_thread.samples = fake_samples
        MockThread.return_value = mock_thread

        buf = io.StringIO()
        with patch('subprocess.Popen', return_value=mock_proc):
            with _patch_wait4_success(mock_proc):
                with patch('sys.stdout', buf):
                    with pytest.raises(SystemExit):
                        main(argv)

    return json.loads(buf.getvalue()), MockThread, mock_thread


def test_cli_monitor_interval_absent_by_default():
    """call.monitor is absent when --monitor-interval is not given."""
    _, record, _ = _run_main(['--no-mixin', '--', 'true'])

    assert 'monitor' not in record.get('call', {})


def test_cli_monitor_interval_creates_field():
    """--monitor-interval produces a call.monitor field with samples."""
    record, MockThread, mock_thread = _run_main_with_monitor(
        ['--no-mixin', '--monitor-interval', '5', '--', 'sleep', '10']
    )

    assert 'monitor' in record['call']
    assert len(record['call']['monitor']) == 1  # one iteration
    assert record['call']['monitor'][0][0]['cpu_percent'] == 12.5
    assert record['call']['monitor'][0][0]['rss_bytes'] == 1048576


def test_cli_monitor_interval_thread_constructed_correctly():
    """Monitor thread is created with the subprocess PID and requested interval."""
    _, MockThread, _ = _run_main_with_monitor(
        ['--no-mixin', '--monitor-interval', '30', '--', 'cmd'],
        mock_pid=99999,
    )

    MockThread.assert_called_once_with(99999, 30)


def test_cli_monitor_interval_thread_lifecycle():
    """Monitor thread is started, stopped, and joined for each iteration."""
    _, _, mock_thread = _run_main_with_monitor(
        ['--no-mixin', '--monitor-interval', '5', '--', 'cmd']
    )

    mock_thread.start.assert_called_once()
    mock_thread.stop.assert_called_once()
    mock_thread.join.assert_called_once()


def test_cli_monitor_interval_empty_samples():
    """call.monitor field is absent when no samples were collected."""
    # A very fast process may exit before the first sample interval fires.
    record, _, _ = _run_main_with_monitor(
        ['--no-mixin', '--monitor-interval', '60', '--', 'true'],
        fake_samples=[],
    )

    # Empty per-iteration lists → outer list is [[]], which is falsy per-element
    # but the field should still be absent (no data to report).
    assert 'monitor' not in record.get('call', {})


def test_cli_monitor_interval_multiple_iterations():
    """With --iterations N, call.monitor has N inner lists."""
    mock_proc = _make_mock_popen_for_monitor(pid=42)

    samples_per_iter = [
        [{'timestamp': 'T0', 'cpu_percent': 10.0, 'rss_bytes': 100}],
        [{'timestamp': 'T1', 'cpu_percent': 20.0, 'rss_bytes': 200}],
        [{'timestamp': 'T2', 'cpu_percent': 30.0, 'rss_bytes': 300}],
    ]
    call_count = {'n': 0}

    def make_thread(pid, interval):
        idx = call_count['n']
        call_count['n'] += 1
        t = MagicMock()
        t.samples = samples_per_iter[idx]
        return t

    buf = io.StringIO()
    with patch('microbench.cli.main._SubprocessMonitorThread', side_effect=make_thread):
        with patch('subprocess.Popen', return_value=mock_proc):
            with _patch_wait4_success(mock_proc):
                with patch('sys.stdout', buf):
                    with pytest.raises(SystemExit):
                        main(
                            [
                                '--no-mixin',
                                '--monitor-interval',
                                '5',
                                '--iterations',
                                '3',
                                '--',
                                'cmd',
                            ]
                        )

    record = json.loads(buf.getvalue())
    assert len(record['call']['monitor']) == 3
    assert record['call']['monitor'][0][0]['cpu_percent'] == 10.0
    assert record['call']['monitor'][1][0]['cpu_percent'] == 20.0
    assert record['call']['monitor'][2][0]['cpu_percent'] == 30.0


def test_cli_monitor_interval_warmup_excluded():
    """Warmup iterations not monitored; call.monitor length == --iterations."""
    mock_proc = _make_mock_popen_for_monitor(pid=7)
    call_count = {'n': 0}
    # 2 warmup + 2 timed = 4 Popen calls; but only 2 monitor threads should start.
    sample = [{'timestamp': 'T', 'cpu_percent': 5.0, 'rss_bytes': 50}]

    def make_thread(pid, interval):
        call_count['n'] += 1
        t = MagicMock()
        t.samples = sample
        return t

    buf = io.StringIO()
    with patch('microbench.cli.main._SubprocessMonitorThread', side_effect=make_thread):
        with patch('subprocess.Popen', return_value=mock_proc):
            with _patch_wait4_success(mock_proc):
                with patch('sys.stdout', buf):
                    with pytest.raises(SystemExit):
                        main(
                            [
                                '--no-mixin',
                                '--monitor-interval',
                                '5',
                                '--warmup',
                                '2',
                                '--iterations',
                                '2',
                                '--',
                                'cmd',
                            ]
                        )

    record = json.loads(buf.getvalue())
    assert len(record['call']['monitor']) == 2
    assert call_count['n'] == 2  # only timed iterations got a monitor thread


def test_cli_monitor_interval_minimum_one():
    """--monitor-interval 0 is rejected."""
    with pytest.raises(SystemExit) as exc:
        main(['--monitor-interval', '0', '--', 'cmd'])
    assert exc.value.code != 0


def test_cli_monitor_interval_negative_rejected():
    """--monitor-interval -1 is rejected."""
    with pytest.raises(SystemExit) as exc:
        main(['--monitor-interval', '-1', '--', 'cmd'])
    assert exc.value.code != 0


def test_cli_monitor_interval_requires_psutil():
    """--monitor-interval exits with an error when psutil is not installed."""
    with patch.dict('sys.modules', {'psutil': None}):
        with pytest.raises(SystemExit) as exc:
            main(['--monitor-interval', '5', '--', 'cmd'])
    assert exc.value.code != 0


def test_cli_monitor_interval_with_stdout_capture():
    """--monitor-interval and --stdout can be combined."""
    mock_proc = _make_mock_popen_for_monitor(pid=55)
    mock_proc.stdout = _MockPipe([b'hello\n'])
    mock_proc.stderr = None
    fake_samples = [{'timestamp': 'T', 'cpu_percent': 8.0, 'rss_bytes': 2048}]

    buf = io.StringIO()
    with patch('microbench.cli.main._SubprocessMonitorThread') as MockThread:
        mock_thread = MagicMock()
        mock_thread.samples = fake_samples
        MockThread.return_value = mock_thread
        with patch('subprocess.Popen', return_value=mock_proc):
            with _patch_wait4_success(mock_proc):
                with patch('sys.stdout', buf):
                    with patch('sys.__stdout__', io.StringIO()):
                        with pytest.raises(SystemExit):
                            main(
                                [
                                    '--no-mixin',
                                    '--monitor-interval',
                                    '5',
                                    '--stdout',
                                    '--',
                                    'cmd',
                                ]
                            )

    record = json.loads(buf.getvalue())
    assert record['call']['stdout'] == ['hello\n']
    assert record['call']['monitor'][0][0]['cpu_percent'] == 8.0


# ---------------------------------------------------------------------------
# --http-output
# ---------------------------------------------------------------------------


def _run_main_http(argv, fake_status=200):
    """Run main() with --http-output, mocking urlopen and subprocess."""
    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)

    mock_proc = _make_mock_popen(returncode=0)
    buf = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_success(mock_proc):
            with patch(
                'urllib.request.urlopen', return_value=mock_response
            ) as mock_urlopen:
                with patch('sys.stdout', buf):
                    with pytest.raises(SystemExit) as exc:
                        main(argv)
    return exc.value.code, mock_urlopen


def test_cli_http_output_posts_record():
    """--http-output POSTs a JSON record to the given URL."""
    code, mock_urlopen = _run_main_http(
        ['--no-mixin', '--http-output', 'https://example.com/hook', '--', 'true']
    )
    assert code == 0
    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    assert req.get_full_url() == 'https://example.com/hook'
    body = json.loads(req.data)
    assert body['call']['name'] == 'true'


def test_cli_http_output_no_stdout_record():
    """--http-output without --outfile produces no stdout JSONL."""
    buf = io.StringIO()
    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_proc = _make_mock_popen(returncode=0)
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_success(mock_proc):
            with patch('urllib.request.urlopen', return_value=mock_response):
                with patch('sys.stdout', buf):
                    with pytest.raises(SystemExit):
                        main(
                            [
                                '--no-mixin',
                                '--http-output',
                                'https://x.com',
                                '--',
                                'true',
                            ]
                        )
    assert buf.getvalue() == ''


def test_cli_http_output_and_outfile(tmp_path):
    """--http-output and --outfile together write to both destinations."""
    outfile = tmp_path / 'results.jsonl'
    mock_response = MagicMock()
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    mock_proc = _make_mock_popen(returncode=0)
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_success(mock_proc):
            with patch(
                'urllib.request.urlopen', return_value=mock_response
            ) as mock_urlopen:
                with pytest.raises(SystemExit):
                    main(
                        [
                            '--no-mixin',
                            '--outfile',
                            str(outfile),
                            '--http-output',
                            'https://x.com',
                            '--',
                            'true',
                        ]
                    )
    assert outfile.exists()
    assert json.loads(outfile.read_text())['call']['name'] == 'true'
    mock_urlopen.assert_called_once()


def test_cli_http_output_header_sets_authorization():
    """--http-output-header KEY:VALUE is sent as an HTTP header."""
    _, mock_urlopen = _run_main_http(
        [
            '--no-mixin',
            '--http-output',
            'https://example.com/hook',
            '--http-output-header',
            'Authorization:Bearer secret',
            '--',
            'true',
        ]
    )
    req = mock_urlopen.call_args[0][0]
    assert req.get_header('Authorization') == 'Bearer secret'


def test_cli_http_output_header_strips_whitespace():
    """Whitespace around KEY and VALUE in --http-output-header is stripped."""
    _, mock_urlopen = _run_main_http(
        [
            '--no-mixin',
            '--http-output',
            'https://example.com/hook',
            '--http-output-header',
            'X-Custom: my value',
            '--',
            'true',
        ]
    )
    req = mock_urlopen.call_args[0][0]
    assert req.get_header('X-custom') == 'my value'


def test_cli_http_output_multiple_headers():
    """Multiple --http-output-header flags are all applied."""
    _, mock_urlopen = _run_main_http(
        [
            '--no-mixin',
            '--http-output',
            'https://example.com/hook',
            '--http-output-header',
            'Authorization:Bearer tok',
            '--http-output-header',
            'X-Tenant:acme',
            '--',
            'true',
        ]
    )
    req = mock_urlopen.call_args[0][0]
    assert req.get_header('Authorization') == 'Bearer tok'
    assert req.get_header('X-tenant') == 'acme'


def test_cli_http_output_method():
    """--http-output-method PUT sends a PUT request."""
    _, mock_urlopen = _run_main_http(
        [
            '--no-mixin',
            '--http-output',
            'https://example.com/hook',
            '--http-output-method',
            'PUT',
            '--',
            'true',
        ]
    )
    req = mock_urlopen.call_args[0][0]
    assert req.get_method() == 'PUT'


def test_cli_http_output_header_without_http_output_errors():
    """--http-output-header without --http-output is an error."""
    with pytest.raises(SystemExit) as exc:
        main(['--no-mixin', '--http-output-header', 'X-Key:val', '--', 'true'])
    assert exc.value.code != 0


def test_cli_http_output_method_without_http_output_errors():
    """--http-output-method without --http-output is an error."""
    with pytest.raises(SystemExit) as exc:
        main(['--no-mixin', '--http-output-method', 'PUT', '--', 'true'])
    assert exc.value.code != 0


def test_cli_http_output_header_invalid_format_errors():
    """--http-output-header without : separator is an error."""
    with pytest.raises(SystemExit) as exc:
        main(
            [
                '--no-mixin',
                '--http-output',
                'https://x.com',
                '--http-output-header',
                'NoColonHere',
                '--',
                'true',
            ]
        )
    assert exc.value.code != 0


# ---------------------------------------------------------------------------
# Redis output
# ---------------------------------------------------------------------------


def _run_main_redis(argv):
    redis_store = []
    mock_client = MagicMock()
    mock_client.rpush.side_effect = lambda key, val: redis_store.append(val)
    mock_redis = MagicMock()
    mock_redis.StrictRedis.return_value = mock_client
    mock_proc = _make_mock_popen(returncode=0)
    buf = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_success(mock_proc):
            with patch.dict('sys.modules', {'redis': mock_redis}):
                with patch('sys.stdout', buf):
                    with pytest.raises(SystemExit) as exc:
                        main(argv)
    return exc.value.code, mock_redis, mock_client, redis_store


def test_cli_redis_output_rpushes_record():
    """--redis-output calls StrictRedis with defaults and rpushes a JSON record."""
    code, mock_redis, mock_client, redis_store = _run_main_redis(
        ['--no-mixin', '--redis-output', 'bench:results', '--', 'true']
    )
    assert code == 0
    mock_redis.StrictRedis.assert_called_once_with(host='localhost', port=6379, db=0)
    mock_client.rpush.assert_called_once()
    key, val = mock_client.rpush.call_args[0]
    assert key == 'bench:results'
    record = json.loads(val)
    assert record['call']['name'] == 'true'


def test_cli_redis_output_no_stdout_record():
    """--redis-output without --outfile produces no stdout JSONL."""
    _, _, _, _ = _run_main_redis(
        ['--no-mixin', '--redis-output', 'bench:results', '--', 'true']
    )
    # Implicitly verified: _run_main_redis uses a buf but doesn't return it;
    # if stdout were written the rpush mock would still be called, so we
    # test stdout directly here.
    buf = io.StringIO()
    mock_client = MagicMock()
    mock_redis = MagicMock()
    mock_redis.StrictRedis.return_value = mock_client
    mock_proc = _make_mock_popen(returncode=0)
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_success(mock_proc):
            with patch.dict('sys.modules', {'redis': mock_redis}):
                with patch('sys.stdout', buf):
                    with pytest.raises(SystemExit):
                        main(
                            [
                                '--no-mixin',
                                '--redis-output',
                                'bench:results',
                                '--',
                                'true',
                            ]
                        )
    assert buf.getvalue() == ''


def test_cli_redis_output_and_outfile(tmp_path):
    """--redis-output and --outfile together write to both destinations."""
    outfile = tmp_path / 'results.jsonl'
    mock_client = MagicMock()
    mock_redis = MagicMock()
    mock_redis.StrictRedis.return_value = mock_client
    mock_proc = _make_mock_popen(returncode=0)
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_success(mock_proc):
            with patch.dict('sys.modules', {'redis': mock_redis}):
                with pytest.raises(SystemExit):
                    main(
                        [
                            '--no-mixin',
                            '--outfile',
                            str(outfile),
                            '--redis-output',
                            'bench:results',
                            '--',
                            'true',
                        ]
                    )
    assert outfile.exists()
    assert json.loads(outfile.read_text())['call']['name'] == 'true'
    mock_client.rpush.assert_called_once()


def test_cli_redis_output_custom_host_port_db():
    """--redis-host/port/db are forwarded to StrictRedis."""
    _, mock_redis, _, _ = _run_main_redis(
        [
            '--no-mixin',
            '--redis-output',
            'bench:results',
            '--redis-host',
            'redis.example.com',
            '--redis-port',
            '6380',
            '--redis-db',
            '2',
            '--',
            'true',
        ]
    )
    mock_redis.StrictRedis.assert_called_once_with(
        host='redis.example.com', port=6380, db=2
    )


def test_cli_redis_output_password():
    """--redis-password is forwarded as a password= kwarg to StrictRedis."""
    _, mock_redis, _, _ = _run_main_redis(
        [
            '--no-mixin',
            '--redis-output',
            'bench:results',
            '--redis-password',
            'secret',
            '--',
            'true',
        ]
    )
    mock_redis.StrictRedis.assert_called_once_with(
        host='localhost', port=6379, db=0, password='secret'
    )


def test_cli_redis_port_without_redis_output_errors():
    """--redis-port without --redis-output exits with a non-zero code."""
    with pytest.raises(SystemExit) as exc:
        main(['--no-mixin', '--redis-port', '6380', '--', 'true'])
    assert exc.value.code != 0


def test_cli_redis_db_without_redis_output_errors():
    """--redis-db without --redis-output exits with a non-zero code."""
    with pytest.raises(SystemExit) as exc:
        main(['--no-mixin', '--redis-db', '1', '--', 'true'])
    assert exc.value.code != 0


def test_cli_redis_password_without_redis_output_errors():
    """--redis-password without --redis-output exits with a non-zero code."""
    with pytest.raises(SystemExit) as exc:
        main(['--no-mixin', '--redis-password', 'secret', '--', 'true'])
    assert exc.value.code != 0


def test_cli_redis_output_missing_package_errors():
    """--redis-output gives a helpful error when the redis package is not installed."""
    with patch.dict('sys.modules', {'redis': None}):
        with pytest.raises(SystemExit) as exc:
            main(['--no-mixin', '--redis-output', 'bench:results', '--', 'true'])
    assert exc.value.code != 0


# ---------------------------------------------------------------------------
# Mixin CLI args: MBGitInfo and MBFileHash
# ---------------------------------------------------------------------------


def test_cli_mixin_arg_without_mixin_errors():
    """Supplying a mixin arg without the corresponding mixin loaded is an error."""
    with pytest.raises(SystemExit) as exc:
        main(['--mixin', 'host-info', '--hash-file', 'data.txt', '--', 'echo'])
    assert exc.value.code != 0


def test_cli_git_repo_without_mixin_errors():
    """--git-repo without the git-info mixin is an error."""
    with pytest.raises(SystemExit) as exc:
        main(['--git-repo', '/some/path', '--', 'echo'])
    assert exc.value.code != 0


def test_cli_mixin_arg_accepted_with_all_flag(tmp_path):
    """Mixin args are accepted when --all is used (all mixins loaded)."""
    target = tmp_path / 'f.txt'
    target.write_bytes(b'x')
    with patch('subprocess.check_output', side_effect=_fake_git_output):
        _, record, _ = _run_main(['--all', '--hash-file', str(target), '--', 'true'])
    assert str(target) in record.get('file_hashes', {})


def test_cli_hash_file_rejects_directory(tmp_path):
    """--hash-file rejects a directory before the subprocess runs."""
    with pytest.raises(SystemExit) as exc:
        main(['--mixin', 'file-hash', '--hash-file', str(tmp_path), '--', 'echo'])
    assert exc.value.code != 0


def test_cli_hash_file_rejects_nonexistent():
    """--hash-file rejects a path that does not exist."""
    with pytest.raises(SystemExit) as exc:
        main(['--mixin', 'file-hash', '--hash-file', 'no_such_file.txt', '--', 'echo'])
    assert exc.value.code != 0


def test_cli_git_repo_rejects_nonexistent():
    """--git-repo rejects a path that does not exist."""
    with pytest.raises(SystemExit) as exc:
        main(['--mixin', 'git-info', '--git-repo', '/no/such/dir', '--', 'echo'])
    assert exc.value.code != 0


def _fake_git_output(cmd, **kwargs):
    """Mock for subprocess.check_output that returns minimal valid git output."""
    cwd = kwargs.get('cwd') or os.getcwd()
    if 'rev-parse' in cmd:
        return (cwd + '\n').encode()
    # git status --porcelain=v2 --branch
    return b'# branch.oid abc123\n# branch.head main\n'


def test_cli_git_repo_explicit(tmp_path):
    """--git-repo passes the given directory to git."""
    with patch('subprocess.check_output', side_effect=_fake_git_output) as mock_co:
        _, record, _ = _run_main(
            ['--mixin', 'git-info', '--git-repo', str(tmp_path), '--', 'true']
        )
    assert record.get('git', {}).get('repo') == str(tmp_path)
    for call in mock_co.call_args_list:
        assert call.kwargs.get('cwd') == str(tmp_path)


def test_cli_git_repo_default_cwd():
    """git-info defaults to the current working directory when --git-repo is omitted."""
    with patch('subprocess.check_output', side_effect=_fake_git_output):
        _, record, _ = _run_main(['--mixin', 'git-info', '--', 'true'])
    assert record.get('git', {}).get('repo') == os.getcwd()


def test_cli_hash_file_explicit(tmp_path):
    """--hash-file hashes the specified file and records it."""
    target = tmp_path / 'data.txt'
    target.write_bytes(b'hello')
    _, record, _ = _run_main(
        ['--mixin', 'file-hash', '--hash-file', str(target), '--', 'true']
    )
    assert str(target) in record.get('file_hashes', {})


def test_cli_hash_file_default_cmd(tmp_path):
    """file-hash defaults to hashing cmd[0] when --hash-file is not given."""
    target = tmp_path / 'script.sh'
    target.write_bytes(b'#!/bin/sh')
    _, record, _ = _run_main(['--mixin', 'file-hash', '--', str(target)])
    assert str(target) in record.get('file_hashes', {})


def test_cli_hash_file_default_resolves_bare_command(tmp_path):
    """file-hash resolves bare command names via PATH for the default hash target."""
    fake_bin = tmp_path / 'myapp'
    fake_bin.write_bytes(b'#!/bin/sh')
    with patch('shutil.which', return_value=str(fake_bin)):
        _, record, _ = _run_main(['--mixin', 'file-hash', '--', 'myapp'])
    assert str(fake_bin) in record.get('file_hashes', {})


def test_cli_hash_file_default_unresolvable_cmd():
    """file-hash records empty file_hashes without error when cmd cannot be resolved."""
    with patch('shutil.which', return_value=None):
        _, record, _ = _run_main(['--mixin', 'file-hash', '--', 'ghost_cmd'])
    assert 'capture_errors' not in record.get('call', {})
    assert record.get('file_hashes') == {}


def test_cli_hash_algorithm(tmp_path):
    """--hash-algorithm changes the digest algorithm used by file-hash."""
    target = tmp_path / 'data.txt'
    target.write_bytes(b'hello')
    _, r256, _ = _run_main(
        ['--mixin', 'file-hash', '--hash-file', str(target), '--', 'true']
    )
    _, rmd5, _ = _run_main(
        [
            '--mixin',
            'file-hash',
            '--hash-file',
            str(target),
            '--hash-algorithm',
            'md5',
            '--',
            'true',
        ]
    )
    sha256_hex = r256['file_hashes'][str(target)]
    md5_hex = rmd5['file_hashes'][str(target)]
    assert len(sha256_hex) == 64  # sha256 produces a 64-char hex digest
    assert len(md5_hex) == 32  # md5 produces a 32-char hex digest
    assert sha256_hex != md5_hex


def test_cli_hash_file_default_includes_arg_files(tmp_path):
    """file-hash default scans cmd[1:] and hashes arguments that are files."""
    script = tmp_path / 'script.sh'
    script.write_bytes(b'#!/bin/sh')
    input_file = tmp_path / 'input.csv'
    input_file.write_bytes(b'a,b,c\n1,2,3\n')
    config = tmp_path / 'params.yaml'
    config.write_bytes(b'lr: 0.001\n')

    _, record, _ = _run_main(
        [
            '--mixin',
            'file-hash',
            '--',
            str(script),
            str(input_file),
            '--flag',
            str(config),
        ]
    )
    hashes = record.get('file_hashes', {})
    assert str(script) in hashes
    assert str(input_file) in hashes
    assert str(config) in hashes


def test_cli_hash_file_default_arg_skips_nonexistent(tmp_path):
    """file-hash default ignores cmd[1:] tokens that are not existing files."""
    script = tmp_path / 'script.sh'
    script.write_bytes(b'#!/bin/sh')

    _, record, _ = _run_main(
        ['--mixin', 'file-hash', '--', str(script), 'no_such_file.csv']
    )
    hashes = record.get('file_hashes', {})
    assert str(script) in hashes
    assert 'no_such_file.csv' not in hashes
    assert 'capture_errors' not in record.get('call', {})


def test_cli_hash_file_default_arg_skips_flags(tmp_path):
    """file-hash default does not attempt to hash flag-like arguments."""
    script = tmp_path / 'script.sh'
    script.write_bytes(b'#!/bin/sh')

    _, record, _ = _run_main(
        [
            '--mixin',
            'file-hash',
            '--',
            str(script),
            '--verbose',
            '-n',
            '10',
        ]
    )
    hashes = record.get('file_hashes', {})
    assert str(script) in hashes
    # Flag tokens should not appear as hash keys
    assert '--verbose' not in hashes
    assert '-n' not in hashes
    assert '10' not in hashes


def test_cli_hash_file_default_arg_skips_directories(tmp_path):
    """file-hash default does not hash directory paths passed as arguments."""
    script = tmp_path / 'script.sh'
    script.write_bytes(b'#!/bin/sh')
    subdir = tmp_path / 'output_dir'
    subdir.mkdir()

    _, record, _ = _run_main(['--mixin', 'file-hash', '--', str(script), str(subdir)])
    hashes = record.get('file_hashes', {})
    assert str(script) in hashes
    assert str(subdir) not in hashes


def test_cli_hash_file_explicit_overrides_arg_scan(tmp_path):
    """--hash-file overrides the default entirely; argument files are not scanned."""
    script = tmp_path / 'script.sh'
    script.write_bytes(b'#!/bin/sh')
    input_file = tmp_path / 'input.csv'
    input_file.write_bytes(b'data\n')
    explicit = tmp_path / 'specific.dat'
    explicit.write_bytes(b'specific\n')

    _, record, _ = _run_main(
        [
            '--mixin',
            'file-hash',
            '--hash-file',
            str(explicit),
            '--',
            str(script),
            str(input_file),
        ]
    )
    hashes = record.get('file_hashes', {})
    # Only the explicitly named file should appear
    assert str(explicit) in hashes
    assert str(script) not in hashes
    assert str(input_file) not in hashes


def test_cli_hash_file_default_arg_duplicate_file(tmp_path):
    """file-hash handles the same file appearing multiple times in args."""
    script = tmp_path / 'script.sh'
    script.write_bytes(b'#!/bin/sh')
    data = tmp_path / 'data.csv'
    data.write_bytes(b'x\n')

    _, record, _ = _run_main(
        [
            '--mixin',
            'file-hash',
            '--',
            str(script),
            str(data),
            str(data),  # duplicated
        ]
    )
    hashes = record.get('file_hashes', {})
    assert str(script) in hashes
    # dict assignment means the second write is idempotent; key appears once
    assert str(data) in hashes
    assert 'capture_errors' not in record.get('call', {})


def test_cli_timeout_grace_period_requires_timeout():
    """--timeout-grace-period without --timeout is an error."""
    with pytest.raises(SystemExit) as exc:
        main(['--timeout-grace-period', '10', '--', 'sleep', '1'])
    assert exc.value.code != 0


def test_cli_timeout_not_exceeded():
    """--timeout that does not fire produces a normal record with no timed_out field."""
    mock_proc = _make_mock_popen()
    mock_proc.returncode = 0

    buf = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_success(mock_proc):
            with patch('sys.stdout', buf):
                with pytest.raises(SystemExit) as exc:
                    main(['--no-mixin', '--timeout', '30', '--', 'sleep', '1'])
    assert exc.value.code == 0
    record = json.loads(buf.getvalue())
    assert 'timed_out' not in record['call']
    assert record['call']['returncode'] == [0]


@pytest.mark.skipif(
    sys.platform == 'win32', reason='os.wait4() timeout handling is POSIX-only'
)
def test_cli_timeout_sigterm_sufficient():
    """--timeout: process exits after SIGTERM; SIGKILL is not sent."""
    mock_proc = _make_mock_popen()
    mock_proc.returncode = -15  # killed by SIGTERM

    buf = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_sleep(mock_proc, 0.05, status=15):
            with patch('sys.stdout', buf):
                with pytest.raises(SystemExit):
                    main(['--no-mixin', '--timeout', '0.001', '--', 'sleep', '100'])
    record = json.loads(buf.getvalue())
    assert record['call']['timed_out'] is True
    mock_proc.terminate.assert_called_once()
    mock_proc.kill.assert_not_called()


@pytest.mark.skipif(
    sys.platform == 'win32', reason='os.wait4() timeout handling is POSIX-only'
)
def test_cli_timeout_sigkill_required():
    """--timeout: SIGKILL sent when process ignores SIGTERM past the grace period."""
    mock_proc = _make_mock_popen()
    mock_proc.returncode = -9  # killed by SIGKILL

    buf = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_sleep(mock_proc, 0.05, status=9):
            with patch('sys.stdout', buf):
                with pytest.raises(SystemExit):
                    main(
                        [
                            '--no-mixin',
                            '--timeout',
                            '0.001',
                            '--timeout-grace-period',
                            '0.001',
                            '--',
                            'sleep',
                            '100',
                        ]
                    )
    record = json.loads(buf.getvalue())
    assert record['call']['timed_out'] is True
    mock_proc.terminate.assert_called_once()
    mock_proc.kill.assert_called_once()


def test_cli_timeout_during_warmup_does_not_set_timed_out():
    """A timeout in warmup is discarded along with other warmup-only state."""
    warmup_proc = _make_mock_popen()
    warmup_proc.returncode = -15

    timed_proc = _make_mock_popen()
    timed_proc.returncode = 0

    def warmup_wait4(pid, options):
        import time

        time.sleep(0.05)
        return (warmup_proc.pid, 15, _FakeRusage())

    buf = io.StringIO()
    with patch('subprocess.Popen', side_effect=[warmup_proc, timed_proc]):
        with _patch_wait4_sequence(
            warmup_wait4,
            (timed_proc.pid, 0, _FakeRusage()),
        ):
            with patch('sys.stdout', buf):
                with pytest.raises(SystemExit) as exc:
                    main(
                        [
                            '--no-mixin',
                            '--warmup',
                            '1',
                            '--timeout',
                            '0.001',
                            '--',
                            'sleep',
                            '100',
                        ]
                    )

    assert exc.value.code == 0
    record = json.loads(buf.getvalue())
    assert record['call']['returncode'] == [0]
    assert 'timed_out' not in record['call']


@pytest.mark.skipif(
    sys.platform == 'win32', reason='os.wait4() is not available on Windows'
)
def test_cli_keyboard_interrupt_kills_child():
    """KeyboardInterrupt during wait4 join causes proc.kill() and re-raises."""
    mock_proc = _make_mock_popen()

    def _wait4_interrupt(pid, options):
        raise KeyboardInterrupt

    with patch('subprocess.Popen', return_value=mock_proc):
        with patch('os.wait4', side_effect=_wait4_interrupt):
            with pytest.raises(KeyboardInterrupt):
                main(['--no-mixin', '--', 'sleep', '100'])

    mock_proc.kill.assert_called()
    mock_proc.wait.assert_called()


def test_cli_pipe_fds_closed_after_run():
    """stdout and stderr pipe FDs are closed after a normal run."""
    mock_proc = _make_mock_popen(
        returncode=0,
        stdout_lines=[b'out\n'],
        stderr_lines=[b'err\n'],
    )

    buf = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with _patch_wait4_success(mock_proc):
            with patch('sys.stdout', buf):
                with patch('sys.__stdout__', io.StringIO()):
                    with patch('sys.__stderr__', io.StringIO()):
                        with pytest.raises(SystemExit):
                            main(['--stdout', '--stderr', '--', 'cmd'])

    assert mock_proc.stdout.closed
    assert mock_proc.stderr.closed


def test_cli_version(capsys):
    """--version prints the package version and exits 0."""
    with pytest.raises(SystemExit) as exc:
        main(['--version'])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


# ---------------------------------------------------------------------------
# --dry-run
# ---------------------------------------------------------------------------


def test_cli_dry_run_exits_zero(capsys):
    """--dry-run exits 0 and does not write a JSONL record."""
    with pytest.raises(SystemExit) as exc:
        main(['--dry-run', '--', 'sleep', '1'])
    assert exc.value.code == 0


def test_cli_dry_run_no_subprocess(capsys):
    """--dry-run does not execute the command."""
    with patch('subprocess.run') as mock_run:
        with patch('subprocess.Popen') as mock_popen:
            with pytest.raises(SystemExit):
                main(['--dry-run', '--', 'sleep', '1'])
    mock_run.assert_not_called()
    mock_popen.assert_not_called()


def test_cli_dry_run_shows_command(capsys):
    """--dry-run output includes the command."""
    with pytest.raises(SystemExit):
        main(['--dry-run', '--', 'sleep', '1'])
    assert 'sleep 1' in capsys.readouterr().out


def test_cli_dry_run_shows_mixins(capsys):
    """--dry-run output lists the active mixins."""
    with pytest.raises(SystemExit):
        main(['--dry-run', '--mixin', 'host-info', 'python-info', '--', 'true'])
    out = capsys.readouterr().out
    assert 'host-info' in out
    assert 'python-info' in out


def test_cli_dry_run_no_mixin(capsys):
    """--dry-run with --no-mixin shows 'none' for mixins."""
    with pytest.raises(SystemExit):
        main(['--dry-run', '--no-mixin', '--', 'true'])
    assert 'none' in capsys.readouterr().out


def test_cli_dry_run_shows_iterations(capsys):
    """--dry-run output includes iteration and warmup counts."""
    with pytest.raises(SystemExit):
        main(['--dry-run', '--iterations', '5', '--warmup', '2', '--', 'true'])
    out = capsys.readouterr().out
    assert '5' in out
    assert '2' in out


def test_cli_dry_run_shows_output_file(capsys, tmp_path):
    """--dry-run output includes the output file path."""
    outfile = str(tmp_path / 'results.jsonl')
    with pytest.raises(SystemExit):
        main(['--dry-run', '--outfile', outfile, '--', 'true'])
    assert outfile in capsys.readouterr().out


def test_cli_dry_run_shows_timeout(capsys):
    """--dry-run output includes timeout settings."""
    with pytest.raises(SystemExit):
        main(
            [
                '--dry-run',
                '--timeout',
                '60',
                '--timeout-grace-period',
                '10',
                '--',
                'true',
            ]
        )
    out = capsys.readouterr().out
    assert '60' in out
    assert '10' in out


def test_cli_dry_run_shows_mixin_specific_args(capsys):
    """--dry-run shows mixin-specific flags that were explicitly set."""
    with patch('subprocess.check_output'):
        with pytest.raises(SystemExit):
            main(
                [
                    '--dry-run',
                    '--mixin',
                    'nvidia-smi',
                    '--nvidia-attributes',
                    'gpu_name',
                    'power.draw',
                    '--',
                    'true',
                ]
            )
    out = capsys.readouterr().out
    assert '--nvidia-attributes' in out
    assert 'gpu_name' in out
    assert 'power.draw' in out


def test_cli_dry_run_validates_args(capsys):
    """--dry-run validates arguments; --timeout-grace-period requires --timeout."""
    with pytest.raises(SystemExit) as exc:
        main(['--dry-run', '--timeout-grace-period', '10', '--', 'true'])
    assert exc.value.code != 0


def test_cli_dry_run_shows_fields(capsys):
    """--dry-run output includes --field values."""
    with pytest.raises(SystemExit):
        main(['--dry-run', '--field', 'experiment=run-1', '--', 'true'])
    assert 'experiment=run-1' in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Mixin CLI args: MBNvidiaSmi
# ---------------------------------------------------------------------------

_FAKE_NVIDIA_DEFAULT = b'GPU-abc123, Tesla T4, 16160 MiB\n'
_FAKE_NVIDIA_SINGLE_ATTR = b'GPU-abc123, Tesla T4\n'
_FAKE_NVIDIA_TWO_ATTR = b'GPU-abc123, Tesla T4, 300.00 W\n'


def test_cli_nvidia_attributes_default():
    """nvidia-smi uses default attributes when --nvidia-attributes is absent."""
    with patch('subprocess.check_output', return_value=_FAKE_NVIDIA_DEFAULT) as mock_co:
        _, record, _ = _run_main(['--mixin', 'nvidia-smi', '--', 'true'])
    cmd = mock_co.call_args[0][0]
    assert '--query-gpu=uuid,gpu_name,memory.total' in cmd


def test_cli_nvidia_attributes_custom():
    """--nvidia-attributes changes the attributes queried from nvidia-smi."""
    with patch(
        'subprocess.check_output', return_value=_FAKE_NVIDIA_SINGLE_ATTR
    ) as mock_co:
        _, record, _ = _run_main(
            ['--mixin', 'nvidia-smi', '--nvidia-attributes', 'gpu_name', '--', 'true']
        )
    cmd = mock_co.call_args[0][0]
    assert '--query-gpu=uuid,gpu_name' in cmd
    assert not any('memory.total' in arg for arg in cmd)


def test_cli_nvidia_attributes_multiple():
    """--nvidia-attributes accepts multiple space-separated attribute names."""
    with patch(
        'subprocess.check_output', return_value=_FAKE_NVIDIA_TWO_ATTR
    ) as mock_co:
        _, record, _ = _run_main(
            [
                '--mixin',
                'nvidia-smi',
                '--nvidia-attributes',
                'gpu_name',
                'power.draw',
                '--',
                'true',
            ]
        )
    cmd = mock_co.call_args[0][0]
    assert '--query-gpu=uuid,gpu_name,power.draw' in cmd


def test_cli_nvidia_gpus_filters_devices():
    """--nvidia-gpus passes the -i flag to nvidia-smi."""
    with patch('subprocess.check_output', return_value=_FAKE_NVIDIA_DEFAULT) as mock_co:
        _, record, _ = _run_main(
            ['--mixin', 'nvidia-smi', '--nvidia-gpus', '0', '--', 'true']
        )
    cmd = mock_co.call_args[0][0]
    assert '-i' in cmd
    assert cmd[cmd.index('-i') + 1] == '0'


def test_cli_nvidia_gpus_multiple_devices():
    """--nvidia-gpus with multiple IDs joins them with commas."""
    with patch('subprocess.check_output', return_value=_FAKE_NVIDIA_DEFAULT) as mock_co:
        _, record, _ = _run_main(
            ['--mixin', 'nvidia-smi', '--nvidia-gpus', '0', '1', '--', 'true']
        )
    cmd = mock_co.call_args[0][0]
    assert '-i' in cmd
    assert cmd[cmd.index('-i') + 1] == '0,1'


def test_cli_nvidia_gpus_invalid_rejected():
    """--nvidia-gpus rejects an ID containing whitespace."""
    with pytest.raises(SystemExit) as exc:
        main(['--mixin', 'nvidia-smi', '--nvidia-gpus', 'invalid id', '--', 'true'])
    assert exc.value.code != 0


def test_cli_nvidia_attributes_without_mixin_errors():
    """--nvidia-attributes without the nvidia-smi mixin is an error."""
    with pytest.raises(SystemExit) as exc:
        main(['--mixin', 'host-info', '--nvidia-attributes', 'gpu_name', '--', 'true'])
    assert exc.value.code != 0


def test_cli_nvidia_gpus_without_mixin_errors():
    """--nvidia-gpus without the nvidia-smi mixin is an error."""
    with pytest.raises(SystemExit) as exc:
        main(['--mixin', 'host-info', '--nvidia-gpus', '0', '--', 'true'])
    assert exc.value.code != 0


def test_cli_show_mixins_includes_nvidia_flags():
    """--show-mixins lists --nvidia-attributes and --nvidia-gpus under nvidia-smi."""
    buf = io.StringIO()
    with patch('sys.stdout', buf):
        with pytest.raises(SystemExit):
            main(['--show-mixins'])
    output = buf.getvalue()
    assert '--nvidia-attributes' in output
    assert '--nvidia-gpus' in output


# ---------------------------------------------------------------------------
# MBResourceUsage — CLI tests
# ---------------------------------------------------------------------------

_RUSAGE_FIELDS = frozenset(
    {
        'utime',
        'stime',
        'maxrss',
        'minflt',
        'majflt',
        'inblock',
        'oublock',
        'nvcsw',
        'nivcsw',
    }
)


def test_cli_resource_usage_in_defaults():
    """resource-usage is included in the default mixin set."""
    _, record, _ = _run_main(['--', 'true'])
    assert 'resource_usage' in record


@pytest.mark.skipif(
    sys.platform == 'win32', reason='resource module not available on Windows'
)
def test_cli_resource_usage_fields_present():
    """resource-usage records all expected fields."""
    _, record, _ = _run_main(['--mixin', 'resource-usage', '--', 'true'])
    ru_list = record.get('resource_usage', [])
    assert isinstance(ru_list, list)
    assert len(ru_list) == 1
    assert set(ru_list[0].keys()) == _RUSAGE_FIELDS


@pytest.mark.skipif(
    sys.platform == 'win32', reason='resource module not available on Windows'
)
def test_cli_resource_usage_values_are_numeric():
    """resource-usage field values are all numbers (int or float)."""
    _, record, _ = _run_main(['--mixin', 'resource-usage', '--', 'true'])
    ru_list = record.get('resource_usage', [])
    assert len(ru_list) == 1
    for field, value in ru_list[0].items():
        assert isinstance(value, int | float), (
            f'{field}: expected number, got {type(value)}'
        )


def test_cli_resource_usage_no_mixins_omits_field():
    """--no-mixin produces a record without resource_usage."""
    _, record, _ = _run_main(['--no-mixin', '--', 'true'])
    assert 'resource_usage' not in record


def test_cli_show_mixins_includes_resource_usage():
    """--show-mixins lists resource-usage with a default marker."""
    buf = io.StringIO()
    with patch('sys.stdout', buf):
        with pytest.raises(SystemExit):
            main(['--show-mixins'])
    output = buf.getvalue()
    assert 'resource-usage' in output
    # resource-usage is a default mixin — should be starred
    lines = [line for line in output.splitlines() if 'resource-usage' in line]
    assert lines, 'resource-usage not found in --show-mixins output'
    assert lines[0].startswith('  *'), 'resource-usage should be marked as default (*)'


@pytest.mark.skipif(
    sys.platform == 'win32', reason='resource module not available on Windows'
)
def test_cli_resource_usage_real_subprocess_maxrss():
    """resource-usage records a positive maxrss from a real subprocess."""
    buf = io.StringIO()
    with patch('sys.stdout', buf):
        with pytest.raises(SystemExit):
            main(['--mixin', 'resource-usage', '--', sys.executable, '-c', 'pass'])
    record = json.loads(buf.getvalue())
    ru_list = record.get('resource_usage', [])
    assert isinstance(ru_list, list)
    assert len(ru_list) == 1
    ru = ru_list[0]
    assert set(ru.keys()) == _RUSAGE_FIELDS
    assert ru['maxrss'] > 0, (
        'maxrss should be positive after running a Python subprocess'
    )


@pytest.mark.skipif(
    sys.platform == 'win32', reason='resource module not available on Windows'
)
def test_cli_resource_usage_real_subprocess_cpu_nonnegative():
    """utime and stime are non-negative after a real subprocess."""
    buf = io.StringIO()
    with patch('sys.stdout', buf):
        with pytest.raises(SystemExit):
            main(['--mixin', 'resource-usage', '--', sys.executable, '-c', 'pass'])
    record = json.loads(buf.getvalue())
    ru = record['resource_usage'][0]
    assert ru['utime'] >= 0.0
    assert ru['stime'] >= 0.0


@pytest.mark.skipif(
    sys.platform == 'win32', reason='resource module not available on Windows'
)
def test_cli_resource_usage_real_subprocess_counts_nonnegative():
    """All integer count fields are non-negative after a real subprocess."""
    buf = io.StringIO()
    with patch('sys.stdout', buf):
        with pytest.raises(SystemExit):
            main(['--mixin', 'resource-usage', '--', sys.executable, '-c', 'pass'])
    record = json.loads(buf.getvalue())
    ru = record['resource_usage'][0]
    for field in ('minflt', 'majflt', 'inblock', 'oublock', 'nvcsw', 'nivcsw'):
        assert ru[field] >= 0, f'{field} should be non-negative'
