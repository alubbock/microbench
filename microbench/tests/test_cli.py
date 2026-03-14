import io
import json
from unittest.mock import MagicMock, patch

import pytest

from microbench.__main__ import main


def _run_main(argv, mock_returncode=0):
    """Run main() with a mocked subprocess and captured stdout."""
    mock_result = MagicMock()
    mock_result.returncode = mock_returncode

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
    assert record['returncode'] == 0
    assert 'start_time' in record
    assert 'finish_time' in record
    assert 'run_durations' in record
    assert record['function_name'] == 'sleep'


def test_cli_nonzero_returncode():
    """CLI exits with the subprocess returncode."""
    code, record, _ = _run_main(['--', 'false'], mock_returncode=1)

    assert code == 1
    assert record['returncode'] == 1


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


def test_cli_explicit_mixin_replaces_defaults():
    """Specifying --mixin replaces the default mixin set."""
    _, record, _ = _run_main(['--mixin', 'MBPythonVersion', '--', 'true'])

    assert 'python_version' in record
    # Default mixins should not be present
    assert 'hostname' not in record
    assert 'slurm' not in record


def test_cli_outfile(tmp_path):
    """--outfile writes JSONL to the specified file."""
    outfile = tmp_path / 'results.jsonl'
    mock_result = MagicMock()
    mock_result.returncode = 0

    with patch('subprocess.run', return_value=mock_result):
        with pytest.raises(SystemExit):
            main(['--outfile', str(outfile), '--', 'true'])

    record = json.loads(outfile.read_text())
    assert record['command'] == ['true']
    assert record['returncode'] == 0


def test_cli_no_command_exits_with_error():
    """Omitting the command prints an error and exits non-zero."""
    with pytest.raises(SystemExit) as exc:
        main([])
    assert exc.value.code != 0


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


def test_cli_warmup():
    """--warmup N runs the command N extra times before timing begins."""
    _, record, mock_run = _run_main(['--warmup', '2', '--', 'true'])

    # 2 warmup calls + 1 timed call
    assert mock_run.call_count == 3
    assert len(record['run_durations']) == 1


def test_cli_iterations_and_warmup():
    """--iterations and --warmup together produce the right call count."""
    _, record, mock_run = _run_main(
        ['--iterations', '4', '--warmup', '2', '--', 'true']
    )

    assert mock_run.call_count == 6
    assert len(record['run_durations']) == 4
