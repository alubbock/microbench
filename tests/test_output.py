import datetime
import io
import json
import os
import socket
import tempfile
import urllib.error
import urllib.request
import warnings
from unittest.mock import MagicMock, patch

import numpy
import pytest

from microbench import (
    _UNENCODABLE_PLACEHOLDER_VALUE,
    FileOutput,
    HttpOutput,
    JSONEncoder,
    JSONEncodeWarning,
    MBFunctionCall,
    MBReturnValue,
    MicroBench,
    Output,
    RedisOutput,
    summary,
)
from microbench.outputs.utils import _flatten_dict


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
        results = bench.get_results()
        assert results[0]['call']['name'] == 'noop'
    finally:
        os.unlink(tmppath)


def test_get_results_without_pandas():
    """get_results(format='df') raises ImportError when pandas is unavailable."""
    import microbench.outputs.file

    bench = MicroBench()

    @bench
    def noop():
        pass

    noop()

    with patch.object(microbench.outputs.file, 'pandas', None):
        # Default format='dict' works without pandas
        results = bench.get_results()
        assert isinstance(results, list)
        assert results[0]['call']['name'] == 'noop'

        # format='df' raises ImportError
        with pytest.raises(ImportError, match='pandas'):
            bench.get_results(format='df')


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
    assert all(r['call']['name'] == 'noop' for r in results)


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
        assert results[0]['call']['name'] == 'noop'
        assert 'start_time' in results[0]['call']
        assert 'finish_time' in results[0]['call']

        mock_redis_client.rpush.assert_called_once()
        assert mock_redis_client.rpush.call_args[0][0] == 'test:bench'


def test_redis_output_get_results_without_pandas():
    """RedisOutput.get_results() raises ImportError without pandas."""
    import microbench.outputs.redis

    redis_store = []
    mock_redis, _ = _make_mock_redis(redis_store)

    with patch.dict('sys.modules', {'redis': mock_redis}):
        bench = MicroBench(outputs=[RedisOutput('test:bench')])

        with patch.object(microbench.outputs.redis, 'pandas', None):
            with pytest.raises(ImportError, match='pandas'):
                bench.get_results(format='df')


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
        assert [r['call']['name'] for r in results] == ['func_a', 'func_b']


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
    assert results[0]['call']['args'] == [_UNENCODABLE_PLACEHOLDER_VALUE]
    assert results[0]['call']['kwargs'] == {'arg2': _UNENCODABLE_PLACEHOLDER_VALUE}
    assert results[0]['call']['return_value'] == _UNENCODABLE_PLACEHOLDER_VALUE


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
    assert results[0]['call']['return_value'] == str(obj)


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


# ---------------------------------------------------------------------------
# get_results format and flat tests
# ---------------------------------------------------------------------------


def test_get_results_default_returns_list_of_dicts():
    """get_results() default returns a list of dicts without requiring pandas."""
    bench = MicroBench()

    @bench
    def noop():
        pass

    noop()
    noop()

    results = bench.get_results()
    assert isinstance(results, list)
    assert len(results) == 2
    assert all(isinstance(r, dict) for r in results)
    assert results[0]['call']['name'] == 'noop'


def test_get_results_format_df_returns_dataframe():
    """get_results(format='df') returns a pandas DataFrame."""
    bench = MicroBench()

    @bench
    def noop():
        pass

    noop()

    results = bench.get_results(format='df')
    assert hasattr(results, 'columns')  # DataFrame duck-type check
    assert results['call'][0]['name'] == 'noop'


def test_get_results_invalid_format_raises():
    """get_results() raises ValueError for an unrecognised format."""
    bench = MicroBench()

    @bench
    def noop():
        pass

    noop()

    with pytest.raises(ValueError, match='format'):
        bench.get_results(format='csv')


def test_flatten_dict_basic():
    """_flatten_dict flattens nested dicts with dot-notation keys."""
    d = {'a': {'b': 1, 'c': {'d': 2}}, 'e': 3}
    assert _flatten_dict(d) == {'a.b': 1, 'a.c.d': 2, 'e': 3}


def test_flatten_dict_non_dict_values_unchanged():
    """_flatten_dict leaves non-dict values (lists, scalars) intact."""
    d = {'a': [1, 2, 3], 'b': {'c': 'hello'}}
    assert _flatten_dict(d) == {'a': [1, 2, 3], 'b.c': 'hello'}


def test_get_results_flat_dict():
    """get_results(flat=True) flattens nested fields into dot-notation keys."""
    import unittest.mock

    from microbench import MBSlurmInfo

    class Bench(MicroBench, MBSlurmInfo):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    with unittest.mock.patch.dict(
        os.environ, {'SLURM_JOB_ID': '42', 'SLURM_CPUS_ON_NODE': '8'}
    ):
        noop()

    results = bench.get_results(flat=True)
    assert isinstance(results, list)
    # MBSlurmInfo strips SLURM_ prefix and lowercases; nested dict should be flattened
    assert 'slurm.job_id' in results[0]
    assert results[0]['slurm.job_id'] == '42'
    assert 'slurm' not in results[0]


def test_get_results_flat_df():
    """get_results(format='df', flat=True) returns a flattened DataFrame."""
    import unittest.mock

    from microbench import MBSlurmInfo

    class Bench(MicroBench, MBSlurmInfo):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    with unittest.mock.patch.dict(os.environ, {'SLURM_JOB_ID': '99'}):
        noop()

    results = bench.get_results(format='df', flat=True)
    assert 'slurm.job_id' in results.columns
    assert results['slurm.job_id'][0] == '99'


# ---------------------------------------------------------------------------
# summary tests
# ---------------------------------------------------------------------------


def test_summary_function_prints(capsys):
    """summary() prints min/mean/median/max/stdev of call.durations."""
    bench = MicroBench()

    @bench
    def noop():
        pass

    noop()
    noop()

    summary(bench.get_results())
    out = capsys.readouterr().out
    assert 'n=2' in out
    assert 'min=' in out
    assert 'mean=' in out
    assert 'median=' in out
    assert 'max=' in out
    assert 'stdev=' in out


def test_summary_function_no_results(capsys):
    """summary() prints a message when there are no call.durations."""
    summary([{'call': {'name': 'noop'}}])
    out = capsys.readouterr().out
    assert 'No' in out


def test_summary_single_result_no_stdev(capsys):
    """summary() prints nan for stdev when there is only one duration."""
    summary([{'call': {'durations': [0.5]}}])
    out = capsys.readouterr().out
    assert 'n=1' in out
    assert 'stdev=nan' in out


def test_bench_summary_method(capsys):
    """bench.summary() is a convenience wrapper around summary()."""
    bench = MicroBench()

    @bench
    def noop():
        pass

    noop()

    bench.summary()
    out = capsys.readouterr().out
    assert 'n=1' in out


# ---------------------------------------------------------------------------
# HttpOutput tests
# ---------------------------------------------------------------------------

_HTTP_URL = 'https://example.com/webhook'


def _make_urlopen_mock(status=200):
    """Return a mock for urllib.request.urlopen that returns *status*."""
    mock_response = MagicMock()
    mock_response.status = status
    mock_response.__enter__ = lambda s: s
    mock_response.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=mock_response)


def _make_http_error(code):
    """Return a urllib.error.HTTPError with the given status code."""
    return urllib.error.HTTPError(
        url=_HTTP_URL,
        code=code,
        msg=f'HTTP {code}',
        hdrs=None,
        fp=io.BytesIO(b''),
    )


def test_http_output_posts_json():
    """write() POSTs a valid JSON body with Content-Type application/json."""
    mock_urlopen = _make_urlopen_mock()
    output = HttpOutput(_HTTP_URL)

    with patch('urllib.request.urlopen', mock_urlopen):
        output.write('{"call": {"name": "noop"}}')

    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    assert req.get_full_url() == _HTTP_URL
    assert req.get_header('Content-type') == 'application/json'
    body = json.loads(req.data)
    assert body['call']['name'] == 'noop'


def test_http_output_posts_to_correct_url():
    """write() sends the request to exactly the URL given at construction."""
    target = 'https://hooks.example.org/events'
    mock_urlopen = _make_urlopen_mock()
    output = HttpOutput(target)

    with patch('urllib.request.urlopen', mock_urlopen):
        output.write('{"x": 1}')

    req = mock_urlopen.call_args[0][0]
    assert req.get_full_url() == target


def test_http_output_default_method_is_post():
    """HttpOutput uses POST by default."""
    mock_urlopen = _make_urlopen_mock()
    output = HttpOutput(_HTTP_URL)

    with patch('urllib.request.urlopen', mock_urlopen):
        output.write('{}')

    req = mock_urlopen.call_args[0][0]
    assert req.get_method() == 'POST'


def test_http_output_custom_method():
    """method='PUT' is used when specified."""
    mock_urlopen = _make_urlopen_mock()
    output = HttpOutput(_HTTP_URL, method='PUT')

    with patch('urllib.request.urlopen', mock_urlopen):
        output.write('{}')

    req = mock_urlopen.call_args[0][0]
    assert req.get_method() == 'PUT'


def test_http_output_custom_headers():
    """Extra headers= dict is merged and sent."""
    mock_urlopen = _make_urlopen_mock()
    output = HttpOutput(
        _HTTP_URL,
        headers={'Authorization': 'Bearer tok', 'X-Custom': 'value'},
    )

    with patch('urllib.request.urlopen', mock_urlopen):
        output.write('{}')

    req = mock_urlopen.call_args[0][0]
    assert req.get_header('Authorization') == 'Bearer tok'
    assert req.get_header('X-custom') == 'value'


def test_http_output_custom_headers_override_default():
    """A caller-supplied Content-Type wins over the default."""
    mock_urlopen = _make_urlopen_mock()
    output = HttpOutput(_HTTP_URL, headers={'Content-type': 'text/plain'})

    with patch('urllib.request.urlopen', mock_urlopen):
        output.write('{}')

    req = mock_urlopen.call_args[0][0]
    assert req.get_header('Content-type') == 'text/plain'


def test_http_output_custom_timeout():
    """Custom timeout= float is forwarded to urlopen."""
    mock_urlopen = _make_urlopen_mock()
    output = HttpOutput(_HTTP_URL, timeout=60.0)

    with patch('urllib.request.urlopen', mock_urlopen):
        output.write('{}')

    _, kwargs = mock_urlopen.call_args
    assert kwargs.get('timeout') == 60.0


def test_http_output_default_timeout():
    """Default timeout is 30.0 seconds."""
    mock_urlopen = _make_urlopen_mock()
    output = HttpOutput(_HTTP_URL)

    with patch('urllib.request.urlopen', mock_urlopen):
        output.write('{}')

    _, kwargs = mock_urlopen.call_args
    assert kwargs.get('timeout') == 30.0


def test_http_output_bearer_token():
    """Authorization header with bearer token is sent correctly."""
    mock_urlopen = _make_urlopen_mock()
    output = HttpOutput(_HTTP_URL, headers={'Authorization': 'Bearer secret-token'})

    with patch('urllib.request.urlopen', mock_urlopen):
        output.write('{}')

    req = mock_urlopen.call_args[0][0]
    assert req.get_header('Authorization') == 'Bearer secret-token'


def test_http_output_format_payload_str_encoded():
    """format_payload returning a str is encoded to UTF-8 bytes before sending."""
    mock_urlopen = _make_urlopen_mock()

    class StrOutput(HttpOutput):
        def format_payload(self, record):
            return 'hello'

    output = StrOutput(_HTTP_URL)

    with patch('urllib.request.urlopen', mock_urlopen):
        output.write('{}')

    req = mock_urlopen.call_args[0][0]
    assert req.data == b'hello'


def test_http_output_format_payload_override():
    """Subclass overriding format_payload shapes the body correctly."""
    mock_urlopen = _make_urlopen_mock()

    class SlackOutput(HttpOutput):
        def format_payload(self, record):
            name = record.get('call', {}).get('name', '?')
            return json.dumps({'text': f'Done: {name}'}).encode()

    output = SlackOutput(_HTTP_URL)

    with patch('urllib.request.urlopen', mock_urlopen):
        output.write('{"call": {"name": "my_func"}}')

    req = mock_urlopen.call_args[0][0]
    body = json.loads(req.data)
    assert body == {'text': 'Done: my_func'}


@pytest.mark.parametrize('status_code', [400, 403, 404, 422])
def test_http_output_raises_on_4xx(status_code):
    """Non-2xx 4xx responses raise urllib.error.HTTPError."""
    output = HttpOutput(_HTTP_URL)

    with patch('urllib.request.urlopen', side_effect=_make_http_error(status_code)):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            output.write('{}')
    assert exc_info.value.code == status_code


@pytest.mark.parametrize('status_code', [500, 502, 503])
def test_http_output_raises_on_5xx(status_code):
    """Server error 5xx responses raise urllib.error.HTTPError."""
    output = HttpOutput(_HTTP_URL)

    with patch('urllib.request.urlopen', side_effect=_make_http_error(status_code)):
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            output.write('{}')
    assert exc_info.value.code == status_code


def test_http_output_raises_on_network_error():
    """URLError (DNS failure / connection refused) propagates to the caller."""
    output = HttpOutput(_HTTP_URL)
    url_error = urllib.error.URLError(reason='[Errno -2] Name or service not known')

    with patch('urllib.request.urlopen', side_effect=url_error):
        with pytest.raises(urllib.error.URLError):
            output.write('{}')


def test_http_output_raises_on_timeout():
    """socket.timeout propagates to the caller."""
    output = HttpOutput(_HTTP_URL)

    with patch('urllib.request.urlopen', side_effect=TimeoutError('timed out')):
        with pytest.raises(socket.timeout):
            output.write('{}')


def test_http_output_get_results_raises():
    """get_results() raises NotImplementedError — HTTP is write-only."""
    output = HttpOutput(_HTTP_URL)
    with pytest.raises(NotImplementedError):
        output.get_results()


def test_http_output_slack_formatter_example():
    """Slack envelope shape produced by format_payload subclass is correct."""
    mock_urlopen = _make_urlopen_mock()

    class SlackOutput(HttpOutput):
        def format_payload(self, record):
            name = record.get('call', {}).get('name', '?')
            return json.dumps({'text': f'Benchmark `{name}` finished.'}).encode()

    output = SlackOutput('https://hooks.slack.com/services/T00/B00/xxx')

    with patch('urllib.request.urlopen', mock_urlopen):
        output.write('{"call": {"name": "train_model"}}')

    req = mock_urlopen.call_args[0][0]
    body = json.loads(req.data)
    assert body['text'] == 'Benchmark `train_model` finished.'


def test_http_output_via_microbench():
    """MicroBench routes records through HttpOutput.write()."""
    mock_urlopen = _make_urlopen_mock()
    output = HttpOutput(_HTTP_URL)

    bench = MicroBench(outputs=[output])

    @bench
    def noop():
        pass

    with patch('urllib.request.urlopen', mock_urlopen):
        noop()

    mock_urlopen.assert_called_once()
    req = mock_urlopen.call_args[0][0]
    body = json.loads(req.data)
    assert body['call']['name'] == 'noop'


def test_http_output_multiple_writes():
    """Each benchmark call produces a separate HTTP request."""
    mock_urlopen = _make_urlopen_mock()
    output = HttpOutput(_HTTP_URL)

    bench = MicroBench(outputs=[output])

    @bench
    def noop():
        pass

    with patch('urllib.request.urlopen', mock_urlopen):
        noop()
        noop()
        noop()

    assert mock_urlopen.call_count == 3
