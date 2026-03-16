import io
import json
import os
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from microbench.__main__ import main


def _make_mock_popen(returncode=0, stdout_lines=None, stderr_lines=None):
    """Create a mock Popen process for --stdout/--stderr capture tests."""
    mock_proc = MagicMock()
    mock_proc.__enter__.return_value = mock_proc
    mock_proc.__exit__.return_value = False
    mock_proc.returncode = returncode
    mock_proc.stdout = iter(stdout_lines) if stdout_lines is not None else None
    mock_proc.stderr = iter(stderr_lines) if stderr_lines is not None else None
    return mock_proc


def _run_main(argv, mock_returncode=0):
    """Run main() with a mocked subprocess and captured stdout."""
    mock_result = MagicMock()
    mock_result.returncode = mock_returncode
    mock_result.stdout = None
    mock_result.stderr = None

    buf = io.StringIO()
    with patch('subprocess.run', return_value=mock_result) as mock_run:
        with patch('sys.stdout', buf):
            with pytest.raises(SystemExit) as exc:
                main(argv)
    return exc.value.code, json.loads(buf.getvalue()), mock_run


def test_cli_records_command_and_timing():
    """CLI records command list, returncode, and standard timing fields."""
    code, record, _ = _run_main(['--', 'sleep', '1'])

    assert code == 0
    assert record['command'] == ['sleep', '1']
    assert record['returncode'] == [0]
    assert 'start_time' in record
    assert 'finish_time' in record
    assert 'run_durations' in record
    assert record['function_name'] == 'sleep'


def test_cli_nonzero_returncode():
    """CLI exits with the subprocess returncode."""
    code, record, _ = _run_main(['--', 'false'], mock_returncode=1)

    assert code == 1
    assert record['returncode'] == [1]


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

    assert 'hostname' in record
    assert 'operating_system' in record


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

    assert 'working_dir' in record
    assert record['working_dir'] == os.getcwd()


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
    assert 'hostname' not in record
    assert 'slurm' not in record


def test_cli_outfile(tmp_path):
    """--outfile writes JSONL to the specified file."""
    outfile = tmp_path / 'results.jsonl'
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = None
    mock_result.stderr = None

    with patch('subprocess.run', return_value=mock_result):
        with pytest.raises(SystemExit):
            main(['--outfile', str(outfile), '--', 'true'])

    record = json.loads(outfile.read_text())
    assert record['command'] == ['true']
    assert record['returncode'] == [0]


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
    assert 'python-version' in output
    assert '--hash-file' in output  # mixin-specific arg shown under file-hash
    assert '--git-repo' in output  # mixin-specific arg shown under git-info


def test_cli_capture_optional_on_by_default():
    """Capture failures are recorded in mb_capture_errors, not raised."""

    def bad_capture(self, bm_data):
        raise RuntimeError('simulated capture failure')

    from microbench import MBHostInfo

    with patch.object(MBHostInfo, 'capture_hostname', bad_capture):
        _, record, _ = _run_main(['--mixin', 'MBHostInfo', '--', 'true'])

    assert 'mb_capture_errors' in record
    assert any('capture_hostname' in e['method'] for e in record['mb_capture_errors'])


def test_cli_all_flag_includes_all_mixins():
    """--all includes every cli_compatible mixin."""
    from microbench.__main__ import _get_mixin_map

    all_names = set(_get_mixin_map())

    # Patch every mixin's capture methods to no-ops to avoid external calls
    with patch('subprocess.run', return_value=MagicMock(returncode=0)):
        buf = io.StringIO()
        with patch('sys.stdout', buf):
            with pytest.raises(SystemExit):
                with patch('subprocess.check_output', side_effect=Exception('skip')):
                    main(['--all', '--', 'true'])

    # At minimum the record should be written (even with capture_optional errors)
    record = json.loads(buf.getvalue())
    assert 'command' in record
    assert len(all_names) > 2  # sanity: more than just defaults


def test_cli_includes_mb_run_id_and_version():
    """CLI records mb_run_id and mb_version in every record."""
    import re

    import microbench

    _, record, _ = _run_main(['--', 'true'])

    uuid_re = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    )
    assert uuid_re.match(record['mb_run_id'])
    assert record['mb_version'] == microbench.__version__


def test_cli_double_dash_separator():
    """-- separator is stripped before passing the command to subprocess."""
    _, _, mock_run = _run_main(['--', 'echo', 'hello'])

    mock_run.assert_called_once()
    called_cmd = mock_run.call_args[0][0]
    assert called_cmd == ['echo', 'hello']


def test_cli_iterations():
    """--iterations N runs the command N times and produces N run_durations entries."""
    _, record, mock_run = _run_main(['--iterations', '3', '--', 'true'])

    assert mock_run.call_count == 3
    assert len(record['run_durations']) == 3
    assert len(record['returncode']) == 3


def test_cli_warmup():
    """--warmup N runs the command N extra times before timing begins."""
    _, record, mock_run = _run_main(['--warmup', '2', '--', 'true'])

    # 2 warmup calls + 1 timed call
    assert mock_run.call_count == 3
    assert len(record['run_durations']) == 1
    assert len(record['returncode']) == 1


def test_cli_iterations_and_warmup():
    """--iterations and --warmup together produce the right call count."""
    _, record, mock_run = _run_main(
        ['--iterations', '4', '--warmup', '2', '--', 'true']
    )

    assert mock_run.call_count == 6
    assert len(record['run_durations']) == 4
    assert len(record['returncode']) == 4


def test_cli_returncode_is_max_across_iterations():
    """Process exits with the highest returncode seen across all iterations."""
    mock_results = [
        MagicMock(returncode=0, stdout=None, stderr=None),
        MagicMock(returncode=2, stdout=None, stderr=None),
        MagicMock(returncode=1, stdout=None, stderr=None),
    ]
    buf = io.StringIO()
    with patch('subprocess.run', side_effect=mock_results):
        with patch('sys.stdout', buf):
            with pytest.raises(SystemExit) as exc:
                main(['--iterations', '3', '--', 'true'])

    assert exc.value.code == 2
    assert json.loads(buf.getvalue())['returncode'] == [0, 2, 1]


def test_cli_multiple_mixins():
    """Multiple space-separated mixins all take effect."""
    _, record, _ = _run_main(['--mixin', 'MBHostInfo', 'MBPythonVersion', '--', 'true'])

    assert 'hostname' in record
    assert 'python_version' in record


def test_cli_all_overrides_mixin():
    """--all takes precedence over --mixin."""
    with patch('subprocess.run', return_value=MagicMock(returncode=0)):
        buf = io.StringIO()
        with patch('sys.stdout', buf):
            with pytest.raises(SystemExit):
                with patch('subprocess.check_output', side_effect=Exception('skip')):
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

    assert 'stdout' not in record
    assert 'stderr' not in record


def test_cli_capture_stdout_records_output():
    """--stdout records subprocess stdout as a list and re-prints to terminal."""
    mock_proc = _make_mock_popen(returncode=0, stdout_lines=[b'hello\n'])

    buf = io.StringIO()
    terminal = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc) as mock_popen:
        with patch('sys.stdout', buf):
            with patch('sys.__stdout__', terminal):
                with pytest.raises(SystemExit):
                    main(['--stdout', '--', 'echo', 'hello'])

    record = json.loads(buf.getvalue())
    assert record['stdout'] == ['hello\n']
    assert 'stderr' not in record
    assert terminal.getvalue() == 'hello\n'
    assert mock_popen.call_args[1].get('stdout') == subprocess.PIPE


def test_cli_capture_stdout_suppress():
    """--stdout=suppress records output without re-printing to terminal."""
    mock_proc = _make_mock_popen(returncode=0, stdout_lines=[b'hello\n'])

    buf = io.StringIO()
    terminal = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with patch('sys.stdout', buf):
            with patch('sys.__stdout__', terminal):
                with pytest.raises(SystemExit):
                    main(['--stdout=suppress', '--', 'echo', 'hello'])

    record = json.loads(buf.getvalue())
    assert record['stdout'] == ['hello\n']
    assert terminal.getvalue() == ''  # nothing re-printed


def test_cli_capture_stderr_records_output():
    """--stderr records subprocess stderr as a list and re-prints to terminal."""
    mock_proc = _make_mock_popen(returncode=0, stderr_lines=[b'warning\n'])

    buf = io.StringIO()
    terminal_err = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with patch('sys.stdout', buf):
            with patch('sys.__stderr__', terminal_err):
                with pytest.raises(SystemExit):
                    main(['--stderr', '--', 'cmd'])

    record = json.loads(buf.getvalue())
    assert record['stderr'] == ['warning\n']
    assert 'stdout' not in record
    assert terminal_err.getvalue() == 'warning\n'


def test_cli_capture_stderr_suppress():
    """--stderr=suppress records stderr without re-printing."""
    mock_proc = _make_mock_popen(returncode=0, stderr_lines=[b'warning\n'])

    buf = io.StringIO()
    terminal_err = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with patch('sys.stdout', buf):
            with patch('sys.__stderr__', terminal_err):
                with pytest.raises(SystemExit):
                    main(['--stderr=suppress', '--', 'cmd'])

    record = json.loads(buf.getvalue())
    assert record['stderr'] == ['warning\n']
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
        with patch('sys.stdout', buf):
            with patch('sys.__stdout__', io.StringIO()):
                with pytest.raises(SystemExit):
                    main(
                        ['--stdout', '--warmup', '1', '--iterations', '3', '--', 'cmd']
                    )

    record = json.loads(buf.getvalue())
    assert record['stdout'] == ['run1\n', 'run2\n', 'run3\n']
    assert len(record['stdout']) == len(record['run_durations'])


def test_cli_capture_stdout_and_stderr():
    """--stdout and --stderr can be used together."""
    mock_proc = _make_mock_popen(
        returncode=0, stdout_lines=[b'out\n'], stderr_lines=[b'err\n']
    )

    buf = io.StringIO()
    with patch('subprocess.Popen', return_value=mock_proc):
        with patch('sys.stdout', buf):
            with patch('sys.__stdout__', io.StringIO()):
                with patch('sys.__stderr__', io.StringIO()):
                    with pytest.raises(SystemExit):
                        main(['--stdout', '--stderr', '--', 'cmd'])

    record = json.loads(buf.getvalue())
    assert record['stdout'] == ['out\n']
    assert record['stderr'] == ['err\n']


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

    assert 'hostname' not in record
    assert 'slurm' not in record
    assert 'python_version' not in record
    # Core fields still present
    assert 'command' in record
    assert 'returncode' in record
    assert 'run_durations' in record


def test_cli_no_mixin_overrides_mixin():
    """--no-mixin takes precedence over --mixin."""
    _, record, _ = _run_main(['--no-mixin', '--mixin', 'MBHostInfo', '--', 'true'])

    assert 'hostname' not in record


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
    with patch('microbench.__main__._SubprocessMonitorThread') as MockThread:
        mock_thread = MagicMock()
        mock_thread.samples = fake_samples
        MockThread.return_value = mock_thread

        buf = io.StringIO()
        with patch('subprocess.Popen', return_value=mock_proc):
            with patch('sys.stdout', buf):
                with pytest.raises(SystemExit):
                    main(argv)

    return json.loads(buf.getvalue()), MockThread, mock_thread


def test_cli_monitor_interval_absent_by_default():
    """subprocess_monitor is absent when --monitor-interval is not given."""
    _, record, _ = _run_main(['--no-mixin', '--', 'true'])

    assert 'subprocess_monitor' not in record


def test_cli_monitor_interval_creates_field():
    """--monitor-interval produces a subprocess_monitor field with samples."""
    record, MockThread, mock_thread = _run_main_with_monitor(
        ['--no-mixin', '--monitor-interval', '5', '--', 'sleep', '10']
    )

    assert 'subprocess_monitor' in record
    assert len(record['subprocess_monitor']) == 1  # one iteration
    assert record['subprocess_monitor'][0][0]['cpu_percent'] == 12.5
    assert record['subprocess_monitor'][0][0]['rss_bytes'] == 1048576


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
    """subprocess_monitor field is absent when no samples were collected."""
    # A very fast process may exit before the first sample interval fires.
    record, _, _ = _run_main_with_monitor(
        ['--no-mixin', '--monitor-interval', '60', '--', 'true'],
        fake_samples=[],
    )

    # Empty per-iteration lists → outer list is [[]], which is falsy per-element
    # but the field should still be absent (no data to report).
    assert 'subprocess_monitor' not in record


def test_cli_monitor_interval_multiple_iterations():
    """With --iterations N, subprocess_monitor has N inner lists."""
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
    with patch('microbench.__main__._SubprocessMonitorThread', side_effect=make_thread):
        with patch('subprocess.Popen', return_value=mock_proc):
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
    assert len(record['subprocess_monitor']) == 3
    assert record['subprocess_monitor'][0][0]['cpu_percent'] == 10.0
    assert record['subprocess_monitor'][1][0]['cpu_percent'] == 20.0
    assert record['subprocess_monitor'][2][0]['cpu_percent'] == 30.0


def test_cli_monitor_interval_warmup_excluded():
    """Warmup iterations not monitored; subprocess_monitor length == --iterations."""
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
    with patch('microbench.__main__._SubprocessMonitorThread', side_effect=make_thread):
        with patch('subprocess.Popen', return_value=mock_proc):
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
    assert len(record['subprocess_monitor']) == 2
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
    mock_proc.stdout = iter([b'hello\n'])
    mock_proc.stderr = None
    fake_samples = [{'timestamp': 'T', 'cpu_percent': 8.0, 'rss_bytes': 2048}]

    buf = io.StringIO()
    with patch('microbench.__main__._SubprocessMonitorThread') as MockThread:
        mock_thread = MagicMock()
        mock_thread.samples = fake_samples
        MockThread.return_value = mock_thread
        with patch('subprocess.Popen', return_value=mock_proc):
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
    assert record['stdout'] == ['hello\n']
    assert record['subprocess_monitor'][0][0]['cpu_percent'] == 8.0


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
    assert record.get('git_info', {}).get('repo') == str(tmp_path)
    for call in mock_co.call_args_list:
        assert call.kwargs.get('cwd') == str(tmp_path)


def test_cli_git_repo_default_cwd():
    """git-info defaults to the current working directory when --git-repo is omitted."""
    with patch('subprocess.check_output', side_effect=_fake_git_output):
        _, record, _ = _run_main(['--mixin', 'git-info', '--', 'true'])
    assert record.get('git_info', {}).get('repo') == os.getcwd()


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
    assert 'mb_capture_errors' not in record
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
