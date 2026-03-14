import asyncio
import atexit as _atexit
import datetime
import io
import signal as _signal
import sys
import threading
import time
import warnings
from unittest.mock import patch

import pandas
import pytest

from microbench import (
    MBFunctionCall,
    MBHostInfo,
    MBLineProfiler,
    MBPythonVersion,
    MBReturnValue,
    MicroBench,
    Output,
)


def test_mb_run_id_and_version():
    """Every record contains mb_run_id (UUID) and mb_version."""
    import re

    import microbench

    bench = MicroBench()

    @bench
    def noop():
        pass

    noop()
    noop()

    results = bench.get_results()

    # mb_run_id is a valid UUID and consistent across calls
    uuid_re = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
    )
    assert results['mb_run_id'].nunique() == 1
    assert uuid_re.match(results['mb_run_id'][0])

    # mb_version matches the installed package version
    assert (results['mb_version'] == microbench.__version__).all()


def test_mb_run_id_shared_across_instances():
    """All MicroBench instances in the same process share the same mb_run_id."""
    bench_a = MicroBench()
    bench_b = MicroBench()

    @bench_a
    def func_a():
        pass

    @bench_b
    def func_b():
        pass

    func_a()
    func_b()

    run_id_a = bench_a.get_results()['mb_run_id'][0]
    run_id_b = bench_b.get_results()['mb_run_id'][0]
    assert run_id_a == run_id_b


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

    signal.signal() can only be called from the main thread; _MonitorThread
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


def test_monitor_multiple_samples():
    """_MonitorThread collects more than one sample for a long-running function."""

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


# ---------------------------------------------------------------------------
# bench.record() context manager
# ---------------------------------------------------------------------------


def test_record_standard_fields():
    """bench.record() produces a record with all standard timing fields."""
    bench = MicroBench()

    with bench.record('my_block'):
        pass

    results = bench.get_results()
    assert len(results) == 1
    row = results.iloc[0]
    assert row['function_name'] == 'my_block'
    assert 'start_time' in results.columns
    assert 'finish_time' in results.columns
    assert len(row['run_durations']) == 1
    assert 'mb_run_id' in results.columns
    assert 'mb_version' in results.columns


def test_record_no_name_defaults():
    """bench.record() with no name sets function_name to '<record>'."""
    bench = MicroBench()

    with bench.record():
        pass

    results = bench.get_results()
    assert results.iloc[0]['function_name'] == '<record>'


def test_record_static_fields():
    """Static fields passed to MicroBench() appear in bench.record() output."""
    bench = MicroBench(experiment='run-1', trial=3)

    with bench.record('block'):
        pass

    results = bench.get_results()
    assert results.iloc[0]['experiment'] == 'run-1'
    assert results.iloc[0]['trial'] == 3


def test_record_mixin_fields():
    """Mixin capture methods run during bench.record()."""

    class Bench(MicroBench, MBHostInfo):
        pass

    bench = Bench()

    with bench.record('block'):
        pass

    results = bench.get_results()
    assert 'hostname' in results.columns
    assert 'operating_system' in results.columns


def test_record_multiple_records():
    """Each bench.record() call appends a separate record."""
    bench = MicroBench()

    with bench.record('first'):
        pass
    with bench.record('second'):
        pass

    results = bench.get_results()
    assert len(results) == 2
    assert list(results['function_name']) == ['first', 'second']


def test_record_exception_captured_and_reraised():
    """Exceptions inside bench.record() are recorded then re-raised."""
    bench = MicroBench()

    with pytest.raises(ValueError, match='oops'):
        with bench.record('block'):
            raise ValueError('oops')

    results = bench.get_results()
    assert len(results) == 1
    exc = results.iloc[0]['exception']
    assert exc['type'] == 'ValueError'
    assert exc['message'] == 'oops'


def test_record_no_exception_field_on_success():
    """No 'exception' field is present when the block completes normally."""
    bench = MicroBench()

    with bench.record('block'):
        pass

    results = bench.get_results()
    assert 'exception' not in results.columns


def test_record_coexists_with_decorator():
    """bench.record() and @bench decorator write to the same output sink."""
    bench = MicroBench()

    with bench.record('ctx'):
        pass

    @bench
    def decorated():
        pass

    decorated()

    results = bench.get_results()
    assert len(results) == 2
    assert set(results['function_name']) == {'ctx', 'decorated'}


# ---------------------------------------------------------------------------
# Exception capture — decorator
# ---------------------------------------------------------------------------


def test_decorator_exception_captured_and_reraised():
    """Exceptions from @bench functions are recorded then re-raised."""
    bench = MicroBench()

    @bench
    def failing():
        raise RuntimeError('boom')

    with pytest.raises(RuntimeError, match='boom'):
        failing()

    results = bench.get_results()
    assert len(results) == 1
    exc = results.iloc[0]['exception']
    assert exc['type'] == 'RuntimeError'
    assert exc['message'] == 'boom'


def test_decorator_no_exception_field_on_success():
    """No 'exception' field when the decorated function returns normally."""
    bench = MicroBench()

    @bench
    def ok():
        pass

    ok()

    results = bench.get_results()
    assert 'exception' not in results.columns


def test_decorator_exception_stops_iterations():
    """An exception on iteration 2 stops the loop; only 2 durations recorded."""
    call_count = 0

    bench = MicroBench(iterations=5)

    @bench
    def sometimes_fails():
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise ValueError('fail on second')

    with pytest.raises(ValueError):
        sometimes_fails()

    results = bench.get_results()
    assert call_count == 2
    assert len(results.iloc[0]['run_durations']) == 2


def test_decorator_return_value_mixin_skipped_on_exception():
    """MBReturnValue does not set return_value when the function raised."""

    class Bench(MicroBench, MBReturnValue):
        pass

    bench = Bench()

    @bench
    def failing():
        raise TypeError('no return')

    with pytest.raises(TypeError):
        failing()

    results = bench.get_results()
    assert 'return_value' not in results.columns


# ---------------------------------------------------------------------------
# Mixin behaviour with bench.record()
# ---------------------------------------------------------------------------


def test_record_mbfunctioncall_produces_empty_args():
    """MBFunctionCall with bench.record() records args=[] kwargs={} (no callable)."""

    class Bench(MicroBench, MBFunctionCall):
        pass

    bench = Bench()

    with bench.record('block'):
        pass

    results = bench.get_results()
    assert results.iloc[0]['args'] == []
    assert results.iloc[0]['kwargs'] == {}


def test_record_mbreturnvalue_ignored():
    """MBReturnValue is silently a no-op with bench.record() (no return value)."""

    class Bench(MicroBench, MBReturnValue):
        pass

    bench = Bench()

    with bench.record('block'):
        pass

    results = bench.get_results()
    assert 'return_value' not in results.columns


# ---------------------------------------------------------------------------
# bench.record_on_exit()
# ---------------------------------------------------------------------------


def _invoke_record_on_exit(bench):
    """Directly call the registered exit handler and return its results."""
    bench._record_on_exit_handler()
    return bench.get_results()


def test_record_on_exit_standard_fields():
    """record_on_exit() produces a record with all standard timing fields."""
    bench = MicroBench()
    orig_excepthook = sys.excepthook
    try:
        bench.record_on_exit('simulation')
        results = _invoke_record_on_exit(bench)
    finally:
        sys.excepthook = orig_excepthook
        _atexit.unregister(bench._record_on_exit_handler)

    assert len(results) == 1
    row = results.iloc[0]
    assert row['function_name'] == 'simulation'
    assert len(row['run_durations']) == 1
    assert row['run_durations'][0] >= 0
    assert 'start_time' in results.columns
    assert 'finish_time' in results.columns
    assert 'mb_run_id' in results.columns
    assert 'mb_version' in results.columns


def test_record_on_exit_default_name():
    """record_on_exit() with no name sets function_name to '<process>'."""
    bench = MicroBench()
    orig_excepthook = sys.excepthook
    try:
        bench.record_on_exit()
        results = _invoke_record_on_exit(bench)
    finally:
        sys.excepthook = orig_excepthook
        _atexit.unregister(bench._record_on_exit_handler)

    assert results.iloc[0]['function_name'] == '<process>'


def test_record_on_exit_static_fields():
    """Static fields from MicroBench() constructor appear in the record."""
    bench = MicroBench(experiment='run-1', trial=7)
    orig_excepthook = sys.excepthook
    try:
        bench.record_on_exit('sim')
        results = _invoke_record_on_exit(bench)
    finally:
        sys.excepthook = orig_excepthook
        _atexit.unregister(bench._record_on_exit_handler)

    assert results.iloc[0]['experiment'] == 'run-1'
    assert results.iloc[0]['trial'] == 7


def test_record_on_exit_mixin_fields():
    """Mixin capture methods run in the exit handler."""

    class Bench(MicroBench, MBHostInfo):
        pass

    bench = Bench()
    orig_excepthook = sys.excepthook
    try:
        bench.record_on_exit('sim')
        results = _invoke_record_on_exit(bench)
    finally:
        sys.excepthook = orig_excepthook
        _atexit.unregister(bench._record_on_exit_handler)

    assert 'hostname' in results.columns
    assert 'operating_system' in results.columns


def test_record_on_exit_exception_capture():
    """Unhandled exceptions are captured via sys.excepthook."""
    bench = MicroBench()
    orig_excepthook = sys.excepthook
    try:
        bench.record_on_exit('sim')
        # Simulate Python calling sys.excepthook for an unhandled exception.
        exc = RuntimeError('something broke')
        sys.excepthook(type(exc), exc, None)
        results = _invoke_record_on_exit(bench)
    finally:
        sys.excepthook = orig_excepthook
        _atexit.unregister(bench._record_on_exit_handler)

    assert len(results) == 1
    exc_field = results.iloc[0]['exception']
    assert exc_field['type'] == 'RuntimeError'
    assert exc_field['message'] == 'something broke'


def test_record_on_exit_no_exception_field_on_clean_exit():
    """No 'exception' field when the process exits cleanly."""
    bench = MicroBench()
    orig_excepthook = sys.excepthook
    try:
        bench.record_on_exit('sim')
        results = _invoke_record_on_exit(bench)
    finally:
        sys.excepthook = orig_excepthook
        _atexit.unregister(bench._record_on_exit_handler)

    assert 'exception' not in results.columns


def test_record_on_exit_sigterm_writes_record():
    """The SIGTERM handler writes the record with exit_signal='SIGTERM'."""
    bench = MicroBench()
    orig_excepthook = sys.excepthook
    orig_sigterm = _signal.getsignal(_signal.SIGTERM)
    try:
        bench.record_on_exit('sim', handle_sigterm=True)
        handler = _signal.getsignal(_signal.SIGTERM)
        assert callable(handler)
        # Invoke the handler but prevent it from re-killing the process.
        with patch('os.kill'), patch('signal.signal'):
            handler(_signal.SIGTERM, None)
        results = bench.get_results()
    finally:
        sys.excepthook = orig_excepthook
        _signal.signal(_signal.SIGTERM, orig_sigterm)
        _atexit.unregister(bench._record_on_exit_handler)

    assert len(results) == 1
    assert results.iloc[0]['exit_signal'] == 'SIGTERM'


def test_record_on_exit_handle_sigterm_false():
    """handle_sigterm=False leaves the SIGTERM handler unchanged."""
    bench = MicroBench()
    orig_excepthook = sys.excepthook
    orig_sigterm = _signal.getsignal(_signal.SIGTERM)
    try:
        bench.record_on_exit('sim', handle_sigterm=False)
        assert _signal.getsignal(_signal.SIGTERM) is orig_sigterm
    finally:
        sys.excepthook = orig_excepthook
        _atexit.unregister(bench._record_on_exit_handler)


def test_record_on_exit_double_fire_prevention():
    """Calling the exit handler twice writes only one record."""
    bench = MicroBench()
    orig_excepthook = sys.excepthook
    try:
        bench.record_on_exit('sim')
        bench._record_on_exit_handler()
        bench._record_on_exit_handler()
        results = bench.get_results()
    finally:
        sys.excepthook = orig_excepthook
        _atexit.unregister(bench._record_on_exit_handler)

    assert len(results) == 1


def test_record_on_exit_re_registration_replaces_first():
    """A second record_on_exit() call replaces the first registration."""
    bench = MicroBench()
    orig_excepthook = sys.excepthook
    try:
        bench.record_on_exit('first')
        first_handler = bench._record_on_exit_handler
        bench.record_on_exit('second')
        second_handler = bench._record_on_exit_handler

        # Old handler should be deregistered; calling it is now a no-op
        # because it is no longer in the atexit list — but it would still
        # run if called directly. The key check is that they are distinct.
        assert first_handler is not second_handler

        second_handler()
        results = bench.get_results()
    finally:
        sys.excepthook = orig_excepthook
        _atexit.unregister(bench._record_on_exit_handler)

    assert len(results) == 1
    assert results.iloc[0]['function_name'] == 'second'


def test_record_on_exit_non_main_thread_warns():
    """record_on_exit() warns when called from a non-main thread."""
    bench = MicroBench()
    orig_excepthook = sys.excepthook
    orig_sigterm = _signal.getsignal(_signal.SIGTERM)
    warning_holder = []

    def run():
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter('always')
            bench.record_on_exit('sim', handle_sigterm=True)
            warning_holder.extend(w)

    t = threading.Thread(target=run)
    t.start()
    t.join()
    try:
        assert any(issubclass(w.category, RuntimeWarning) for w in warning_holder)
        assert _signal.getsignal(_signal.SIGTERM) is orig_sigterm
    finally:
        sys.excepthook = orig_excepthook
        _atexit.unregister(bench._record_on_exit_handler)


def test_record_on_exit_output_fallback_to_stderr(capsys):
    """When output_result raises, the record is written to stderr."""

    class BrokenOutput(Output):
        def write(self, bm_json_str):
            raise OSError('disk full')

    bench = MicroBench(outputs=[BrokenOutput()])
    orig_excepthook = sys.excepthook
    try:
        bench.record_on_exit('sim')
        bench._record_on_exit_handler()
    finally:
        sys.excepthook = orig_excepthook
        _atexit.unregister(bench._record_on_exit_handler)

    captured = capsys.readouterr()
    import json as _json

    record = _json.loads(captured.err.strip())
    assert record['function_name'] == 'sim'


# ---------------------------------------------------------------------------
# Async decorator and arecord() context manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_decorator_standard_fields():
    """@bench on an async def function can be awaited and produces standard fields."""
    bench = MicroBench()

    @bench
    async def async_noop():
        await asyncio.sleep(0)

    await async_noop()

    results = bench.get_results()
    assert len(results) == 1
    assert results.iloc[0]['function_name'] == 'async_noop'
    assert 'start_time' in results.columns
    assert 'finish_time' in results.columns
    assert len(results.iloc[0]['run_durations']) == 1
    assert results.iloc[0]['run_durations'][0] >= 0


@pytest.mark.asyncio
async def test_async_decorator_iterations():
    """iterations=N on an async function produces N run_durations."""
    bench = MicroBench(iterations=3)

    @bench
    async def async_noop():
        await asyncio.sleep(0)

    await async_noop()

    results = bench.get_results()
    assert len(results.iloc[0]['run_durations']) == 3


@pytest.mark.asyncio
async def test_async_decorator_warmup():
    """warmup=N runs N unrecorded calls before timing begins."""
    call_count = 0

    bench = MicroBench(warmup=2, iterations=3)

    @bench
    async def async_fn():
        nonlocal call_count
        call_count += 1

    await async_fn()

    # 2 warmup + 3 recorded = 5 total
    assert call_count == 5
    results = bench.get_results()
    assert len(results.iloc[0]['run_durations']) == 3


@pytest.mark.asyncio
async def test_async_decorator_exception():
    """Exception in async function is captured in the record and re-raised."""
    bench = MicroBench()

    @bench
    async def async_fail():
        raise ValueError('async boom')

    with pytest.raises(ValueError, match='async boom'):
        await async_fail()

    results = bench.get_results()
    assert len(results) == 1
    exc = results.iloc[0]['exception']
    assert exc['type'] == 'ValueError'
    assert exc['message'] == 'async boom'


@pytest.mark.asyncio
async def test_async_decorator_return_value():
    """MBReturnValue captures the return value from an async function."""

    class Bench(MicroBench, MBReturnValue):
        pass

    bench = Bench()

    @bench
    async def async_compute():
        return 42

    result = await async_compute()

    assert result == 42
    results = bench.get_results()
    assert results.iloc[0]['return_value'] == 42


@pytest.mark.asyncio
async def test_async_decorator_functioncall():
    """MBFunctionCall captures args and kwargs from an async function."""

    class Bench(MicroBench, MBFunctionCall):
        pass

    bench = Bench()

    @bench
    async def async_fn(x, y=10):
        pass

    await async_fn(1, y=2)

    results = bench.get_results()
    assert results.iloc[0]['args'] == [1]
    assert results.iloc[0]['kwargs'] == {'y': 2}


@pytest.mark.asyncio
async def test_async_arecord_standard_fields():
    """bench.arecord() works as an async context manager with standard fields."""
    bench = MicroBench()

    async with bench.arecord('my_block'):
        await asyncio.sleep(0)

    results = bench.get_results()
    assert len(results) == 1
    row = results.iloc[0]
    assert row['function_name'] == 'my_block'
    assert 'start_time' in results.columns
    assert 'finish_time' in results.columns
    assert len(row['run_durations']) == 1


@pytest.mark.asyncio
async def test_async_arecord_no_name_defaults():
    """bench.arecord() with no name sets function_name to '<record>'."""
    bench = MicroBench()

    async with bench.arecord():
        pass

    results = bench.get_results()
    assert results.iloc[0]['function_name'] == '<record>'


@pytest.mark.asyncio
async def test_async_arecord_exception():
    """Exceptions inside bench.arecord() are recorded then re-raised."""
    bench = MicroBench()

    with pytest.raises(RuntimeError, match='async oops'):
        async with bench.arecord('block'):
            raise RuntimeError('async oops')

    results = bench.get_results()
    assert len(results) == 1
    exc = results.iloc[0]['exception']
    assert exc['type'] == 'RuntimeError'
    assert exc['message'] == 'async oops'


def test_async_lineprofiler_raises():
    """MBLineProfiler raises NotImplementedError at decoration time for async funcs."""

    class Bench(MicroBench, MBLineProfiler):
        pass

    bench = Bench()

    with pytest.raises(NotImplementedError, match='MBLineProfiler'):

        @bench
        async def async_fn():
            pass


@pytest.mark.asyncio
async def test_async_monitor_thread():
    """Monitor thread works correctly during async function execution."""

    class MonitorBench(MicroBench):
        @staticmethod
        def monitor(process):
            return {'rss': process.memory_info().rss}

    monitor_bench = MonitorBench()

    @monitor_bench
    async def async_noop():
        await asyncio.sleep(0)

    await async_noop()

    assert not monitor_bench._monitor_thread.is_alive()
    results = monitor_bench.get_results()
    assert len(results['monitor'][0]) > 0


@pytest.mark.asyncio
async def test_monitor_with_arecord():
    """Monitor thread starts and stops correctly with bench.arecord()."""

    class MonitorBench(MicroBench):
        @staticmethod
        def monitor(process):
            return {'rss': process.memory_info().rss}

    bench = MonitorBench()

    async with bench.arecord('block'):
        await asyncio.sleep(0)

    assert not bench._monitor_thread.is_alive()
    results = bench.get_results()
    assert len(results) == 1
    assert len(results.iloc[0]['monitor']) > 0


# ---------------------------------------------------------------------------
# monitor + record_on_exit() — monitor spans process lifetime
# ---------------------------------------------------------------------------


def test_monitor_record_on_exit_samples_span_lifetime():
    """Monitor samples are collected from record_on_exit() call time, not exit.

    Before the fix, the monitor thread started inside _exit_handler, so it
    collected at most one sample (from the exit instant).  After the fix it
    starts at record_on_exit() call time and accumulates samples throughout
    the process lifetime.
    """

    class MonitorBench(MicroBench):
        monitor_interval = 0.05

        @staticmethod
        def monitor(process):
            return {'rss': process.memory_info().rss}

    bench = MonitorBench()
    orig_excepthook = sys.excepthook
    try:
        bench.record_on_exit('sim')
        time.sleep(0.25)  # long enough for several monitor samples
        results = _invoke_record_on_exit(bench)
    finally:
        sys.excepthook = orig_excepthook
        _atexit.unregister(bench._record_on_exit_handler)

    assert len(results) == 1
    monitor_data = results.iloc[0]['monitor']
    assert len(monitor_data) >= 2, (
        f'Expected >=2 monitor samples across process lifetime, got {len(monitor_data)}'
    )


def test_monitor_record_on_exit_re_registration_terminates_old_thread():
    """Re-calling record_on_exit() terminates the previous monitor thread."""

    class MonitorBench(MicroBench):
        monitor_interval = 60  # long interval — thread should not sample again

        @staticmethod
        def monitor(process):
            return {'rss': process.memory_info().rss}

    bench = MonitorBench()
    orig_excepthook = sys.excepthook
    try:
        bench.record_on_exit('first')
        first_thread = bench._record_on_exit_monitor_thread
        assert first_thread.is_alive()

        bench.record_on_exit('second')
        # Give the first thread time to notice the terminate signal
        first_thread.join(timeout=2.0)
        assert not first_thread.is_alive(), 'Old monitor thread should be stopped'

        results = _invoke_record_on_exit(bench)
    finally:
        sys.excepthook = orig_excepthook
        _atexit.unregister(bench._record_on_exit_handler)

    assert results.iloc[0]['function_name'] == 'second'
