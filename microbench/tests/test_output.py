import datetime
import os
import tempfile
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
    MBReturnValue,
    MicroBench,
    Output,
    RedisOutput,
)


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


def test_get_results_without_pandas():
    """get_results raises ImportError when pandas is unavailable."""
    import microbench._output

    bench = MicroBench()

    with patch.object(microbench._output, 'pandas', None):
        with pytest.raises(ImportError, match='pandas'):
            bench.get_results()


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
    import microbench._output

    redis_store = []
    mock_redis, _ = _make_mock_redis(redis_store)

    with patch.dict('sys.modules', {'redis': mock_redis}):
        bench = MicroBench(outputs=[RedisOutput('test:bench')])

        with patch.object(microbench._output, 'pandas', None):
            with pytest.raises(ImportError, match='pandas'):
                bench.get_results()


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
