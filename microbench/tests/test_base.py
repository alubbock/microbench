import datetime
import io
import os
import tempfile
import threading
import time
import warnings
from unittest.mock import MagicMock, patch

import numpy
import pandas
import pytest

from microbench import (
    _UNENCODABLE_PLACEHOLDER_VALUE,
    FileOutput,
    JSONEncoder,
    JSONEncodeWarning,
    MBFunctionCall,
    MBHostInfo,
    MBInstalledPackages,
    MBPeakMemory,
    MBPythonVersion,
    MBReturnValue,
    MBSlurmInfo,
    MicroBench,
    Output,
    RedisOutput,
)
from microbench import __version__ as microbench_version

from .globals_capture import globals_bench


def test_function():
    class MyBench(MicroBench, MBFunctionCall, MBPythonVersion, MBHostInfo):
        capture_versions = (pandas, io)
        env_vars = ('TEST_NON_EXISTENT', 'HOME')

    benchmark = MyBench(some_info='123')

    @benchmark
    def my_function():
        """Inefficient function for testing"""
        acc = 0
        for i in range(1000000):
            acc += i

        return acc

    for _ in range(3):
        assert my_function() == 499999500000

    results = benchmark.get_results()
    assert (results['function_name'] == 'my_function').all()
    assert results['package_versions'][0]['pandas'] == pandas.__version__
    runtimes = results['finish_time'] - results['start_time']
    assert (runtimes > datetime.timedelta(0)).all()

    assert results['timestamp_tz'][0] == 'UTC'
    assert results['duration_counter'][0] == 'perf_counter'


def test_multi_iterations():
    class MyBench(MicroBench):
        pass

    tz = datetime.timezone(datetime.timedelta(hours=10))
    iterations = 3
    benchmark = MyBench(iterations=iterations, tz=tz)

    @benchmark
    def my_function():
        pass

    # call the function
    my_function()

    results = benchmark.get_results()
    assert (results['function_name'] == 'my_function').all()
    runtimes = results['finish_time'] - results['start_time']
    assert (runtimes >= datetime.timedelta(0)).all()
    assert results['timestamp_tz'][0] == str(tz)
    # Verify the timezone is actually applied to the timestamps, not just recorded
    assert results['start_time'][0].utcoffset() == datetime.timedelta(hours=10)
    assert results['finish_time'][0].utcoffset() == datetime.timedelta(hours=10)

    assert len(results['run_durations'][0]) == iterations
    assert all(dur >= 0 for dur in results['run_durations'][0])


def test_capture_optional_records_errors():
    """capture_optional=True catches failing captures, records in mb_capture_errors."""

    class BrokenCapture(MicroBench):
        capture_optional = True

        def capture_will_fail(self, bm_data):
            raise RuntimeError('simulated failure')

    bench = BrokenCapture()

    @bench
    def noop():
        pass

    noop()

    results = bench.get_results()
    errors = results['mb_capture_errors'][0]
    assert len(errors) == 1
    assert errors[0]['method'] == 'capture_will_fail'
    assert 'RuntimeError' in errors[0]['error']
    assert 'simulated failure' in errors[0]['error']


def test_capture_optional_no_errors_no_field():
    """When no captures fail, mb_capture_errors is absent from the record."""

    class Bench(MicroBench):
        capture_optional = True

    bench = Bench()

    @bench
    def noop():
        pass

    noop()

    results = bench.get_results()
    assert 'mb_capture_errors' not in results.columns


def test_capture_optional_false_raises():
    """Without capture_optional, a failing capture propagates the exception."""

    class BrokenCapture(MicroBench):
        def capture_will_fail(self, bm_data):
            raise RuntimeError('simulated failure')

    bench = BrokenCapture()

    @bench
    def noop():
        pass

    with pytest.raises(RuntimeError, match='simulated failure'):
        noop()


def test_capture_optional_capturepost():
    """capture_optional also protects capturepost_ methods."""

    class BrokenPost(MicroBench):
        capture_optional = True

        def capturepost_will_fail(self, bm_data):
            raise ValueError('post failure')

    bench = BrokenPost()

    @bench
    def noop():
        pass

    noop()

    results = bench.get_results()
    errors = results['mb_capture_errors'][0]
    assert any(e['method'] == 'capturepost_will_fail' for e in errors)


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


def test_warmup():
    call_count = 0

    bench = MicroBench(warmup=3, iterations=2)

    @bench
    def my_function():
        nonlocal call_count
        call_count += 1

    my_function()

    # 3 warmup + 2 recorded iterations = 5 total calls
    assert call_count == 5

    results = bench.get_results()
    # Only one record (one decorated call), with 2 run_durations
    assert len(results) == 1
    assert len(results['run_durations'][0]) == 2


def test_local_timezone():
    """Verify README example syntax: tz=datetime.datetime.now().astimezone().tzinfo.

    This is a smoke test that the expression produces a valid timezone accepted
    by MicroBench, and that the stored offset matches whatever was passed in.
    On UTC machines the offset is timedelta(0) — identical to the default — so
    this test does not discriminate between 'tz= applied' and 'tz= ignored'.
    test_multi_iterations covers the non-UTC case with a hardcoded UTC+10 offset.
    """

    class MyBench(MicroBench):
        pass

    local_tz = datetime.datetime.now().astimezone().tzinfo
    benchmark = MyBench(tz=local_tz)

    @benchmark
    def noop():
        pass

    noop()

    results = benchmark.get_results()
    expected_offset = datetime.datetime.now().astimezone().utcoffset()
    assert results['start_time'][0].utcoffset() == expected_offset
    assert results['finish_time'][0].utcoffset() == expected_offset
    assert results['timestamp_tz'][0] == str(local_tz)


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


def test_monitor():
    class MonitorBench(MicroBench):
        @staticmethod
        def monitor(process):
            return process.memory_full_info()._asdict()

    monitor_bench = MonitorBench()

    @monitor_bench
    def noop():
        pass

    noop()

    # Check monitor thread completed
    assert not monitor_bench._monitor_thread.is_alive()

    # Check some monitor data was captured
    results = monitor_bench.get_results()
    assert len(results['monitor']) > 0


def test_monitor_from_non_main_thread():
    """Monitor must not crash when started from a non-main thread (B6 fix).

    signal.signal() can only be called from the main thread; MonitorThread
    should skip signal registration and emit a RuntimeWarning instead.
    """

    class MonitorBench(MicroBench):
        @staticmethod
        def monitor(process):
            return {'rss': process.memory_info().rss}

    monitor_bench = MonitorBench()

    @monitor_bench
    def noop():
        pass

    errors = []
    caught_warnings = []

    def run_from_thread():
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            try:
                noop()
            except Exception as exc:
                errors.append(exc)
            caught_warnings.extend(w)

    t = threading.Thread(target=run_from_thread)
    t.start()
    t.join()

    assert not errors, f'Unexpected exception from non-main thread: {errors[0]}'
    assert any(issubclass(w.category, RuntimeWarning) for w in caught_warnings), (
        'Expected a RuntimeWarning about signal registration being skipped'
    )


def test_functioncall_args_not_double_encoded():
    """MBFunctionCall must store raw values, not JSON strings (B5 fix).

    Before the fix, self.to_json(v) stored a JSON string which then got
    re-serialized, turning e.g. {'k': 1} into the string '{"k": 1}'.
    """

    class Bench(MicroBench, MBFunctionCall):
        pass

    bench = Bench()

    @bench
    def dummy(pos_int, pos_dict, kw_str='default'):
        pass

    dummy(42, {'key': 'value'}, kw_str='hello')

    results = bench.get_results()
    args = results['args'][0]
    kwargs = results['kwargs'][0]

    # Values must be their native Python types, not JSON-encoded strings
    assert args[0] == 42, f'Expected int 42, got {args[0]!r}'
    assert args[1] == {'key': 'value'}, f'Expected dict, got {args[1]!r}'
    assert kwargs['kw_str'] == 'hello', f'Expected str hello, got {kwargs["kw_str"]!r}'


def test_unjsonencodable_arg_kwarg_retval():
    class Bench(MicroBench, MBFunctionCall, MBReturnValue):
        pass

    bench = Bench()

    @bench
    def dummy(arg1, arg2):
        return object()

    with warnings.catch_warnings(record=True) as w:
        # Run a function with unencodable arg, kwarg, return value
        dummy(object(), arg2=object())

        # Check that we get three warnings - one each for args,
        # kwargs, return value
        assert len(w) == 3
        assert all(issubclass(w_.category, JSONEncodeWarning) for w_ in w)

    results = bench.get_results()
    assert results['args'][0] == [_UNENCODABLE_PLACEHOLDER_VALUE]
    assert results['kwargs'][0] == {'arg2': _UNENCODABLE_PLACEHOLDER_VALUE}
    assert results['return_value'][0] == _UNENCODABLE_PLACEHOLDER_VALUE


def test_custom_jsonencoder():
    # A custom class which can't be encoded to JSON by default
    class MyCustomClass:
        def __init__(self, message):
            self.message = message

        def __str__(self):
            return f'<MyCustomClass "{self.message}">'

    # Implement JSON encoding for objects of the above class
    class CustomJSONEncoder(JSONEncoder):
        def default(self, o):
            if isinstance(o, MyCustomClass):
                return str(o)

            return super().default(o)

    class Bench(MicroBench, MBReturnValue):
        pass

    # Create a benchmark suite with custom JSON encoder
    bench = Bench(json_encoder=CustomJSONEncoder)

    # Custom object which requires special handling for JSONEncoder
    obj = MyCustomClass('test message')

    @bench
    def dummy():
        return obj

    dummy()

    results = bench.get_results()
    assert results['return_value'][0] == str(obj)


def test_jsonencoder_numpy_types():
    """JSONEncoder handles numpy integer, float, and ndarray natively."""
    encoder = JSONEncoder()
    assert encoder.default(numpy.int64(7)) == 7
    assert encoder.default(numpy.float32(3.14)) == pytest.approx(3.14, abs=1e-5)
    assert encoder.default(numpy.array([1, 2, 3])) == [1, 2, 3]


def test_jsonencoder_timedelta_and_timezone():
    """JSONEncoder serialises timedelta as total seconds and timezone as string."""
    encoder = JSONEncoder()
    assert encoder.default(datetime.timedelta(seconds=90)) == 90.0
    tz = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    tz_str = encoder.default(tz)
    assert '05:30' in tz_str


def test_positional_args_raises():
    """MicroBench constructor rejects extra positional arguments.

    The *args guard is primarily designed for subclasses that forward *args
    via super().__init__(*args, **kwargs). Triggering it directly requires
    saturating the seven named positional parameters first.
    """
    with pytest.raises(ValueError, match='keyword'):
        MicroBench(None, JSONEncoder, datetime.timezone.utc, 1, 0, None, None, 'extra')


def test_outfile_and_outputs_raises():
    """Passing both outfile and outputs raises ValueError."""
    with pytest.raises(ValueError, match='mutually exclusive'):
        MicroBench(outfile='/tmp/x.json', outputs=[FileOutput()])


def test_outfile_string_path():
    """Results are written to and read from a file-system path."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        tmppath = f.name

    try:
        bench = MicroBench(outfile=tmppath)

        @bench
        def noop():
            pass

        noop()

        assert os.path.getsize(tmppath) > 0
        results = pandas.read_json(tmppath, lines=True)
        assert results['function_name'][0] == 'noop'
    finally:
        os.unlink(tmppath)


def test_env_vars_not_iterable():
    """env_vars must be iterable; a non-iterable raises ValueError."""

    class BadBench(MicroBench):
        env_vars = 42  # not iterable

    bench = BadBench()

    @bench
    def noop():
        pass

    with pytest.raises(ValueError, match='env_vars'):
        noop()


def test_capture_versions_not_iterable():
    """capture_versions must be iterable; a non-iterable raises ValueError."""

    class BadBench(MicroBench):
        capture_versions = 42  # not iterable

    bench = BadBench()

    @bench
    def noop():
        pass

    with pytest.raises(ValueError, match='capture_versions'):
        noop()


def test_get_results_without_pandas():
    """get_results raises ImportError when pandas is unavailable."""
    import microbench

    bench = MicroBench()

    with patch.object(microbench, 'pandas', None):
        with pytest.raises(ImportError, match='pandas'):
            bench.get_results()


def test_monitor_multiple_samples():
    """MonitorThread collects more than one sample for a long-running function."""

    class MonitorBench(MicroBench):
        monitor_interval = 0.05

        @staticmethod
        def monitor(process):
            return {'rss': process.memory_info().rss}

    monitor_bench = MonitorBench()

    @monitor_bench
    def slow_function():
        time.sleep(0.25)

    slow_function()

    results = monitor_bench.get_results()
    assert len(results['monitor'][0]) >= 2, 'Expected at least 2 monitor samples'


def test_multi_sink_output():
    """Results are written to all configured output sinks."""

    class RecordingOutput(Output):
        def __init__(self):
            self.records = []

        def write(self, bm_json_str):
            self.records.append(bm_json_str)

    sink_a = RecordingOutput()
    sink_b = FileOutput()

    bench = MicroBench(outputs=[sink_a, sink_b])

    @bench
    def noop():
        pass

    noop()
    noop()

    assert len(sink_a.records) == 2
    results = sink_b.get_results()
    assert len(results) == 2
    assert (results['function_name'] == 'noop').all()


def test_output_base_get_results_raises():
    """Output.get_results() raises NotImplementedError by default."""
    with pytest.raises(NotImplementedError):
        Output().get_results()


def test_no_supporting_sink_raises():
    """get_results() raises RuntimeError when no sink supports it."""

    class SinkOnly(Output):
        def write(self, bm_json_str):
            pass

    bench = MicroBench(outputs=[SinkOnly()])

    @bench
    def noop():
        pass

    noop()

    with pytest.raises(RuntimeError, match='get_results'):
        bench.get_results()


def _make_mock_redis(redis_store):
    """Return a mock redis module wired to the given list as a backing store."""
    mock_redis_client = MagicMock()
    mock_redis_client.rpush.side_effect = lambda key, val: redis_store.append(
        val.encode('utf8') if isinstance(val, str) else val
    )
    mock_redis_client.lrange.side_effect = lambda key, start, end: redis_store
    mock_redis = MagicMock()
    mock_redis.StrictRedis.return_value = mock_redis_client
    return mock_redis, mock_redis_client


def test_redis_output_get_results():
    """RedisOutput.get_results() reads results back from Redis."""
    redis_store = []
    mock_redis, mock_redis_client = _make_mock_redis(redis_store)

    with patch.dict('sys.modules', {'redis': mock_redis}):
        bench = MicroBench(outputs=[RedisOutput('test:bench')])

        @bench
        def noop():
            pass

        noop()

        results = bench.get_results()
        assert results['function_name'][0] == 'noop'
        assert 'start_time' in results.columns
        assert 'finish_time' in results.columns

        mock_redis_client.rpush.assert_called_once()
        assert mock_redis_client.rpush.call_args[0][0] == 'test:bench'


def test_redis_output_get_results_without_pandas():
    """RedisOutput.get_results() raises ImportError without pandas."""
    import microbench

    redis_store = []
    mock_redis, _ = _make_mock_redis(redis_store)

    with patch.dict('sys.modules', {'redis': mock_redis}):
        bench = MicroBench(outputs=[RedisOutput('test:bench')])

        with patch.object(microbench, 'pandas', None):
            with pytest.raises(ImportError, match='pandas'):
                bench.get_results()


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


def test_redis_output_multiple_results():
    """RedisOutput.get_results() returns all stored results."""
    redis_store = []
    mock_redis, _ = _make_mock_redis(redis_store)

    with patch.dict('sys.modules', {'redis': mock_redis}):
        bench = MicroBench(outputs=[RedisOutput('test:bench')])

        @bench
        def func_a():
            pass

        @bench
        def func_b():
            pass

        func_a()
        func_b()

        results = bench.get_results()
        assert len(results) == 2
        assert list(results['function_name']) == ['func_a', 'func_b']
