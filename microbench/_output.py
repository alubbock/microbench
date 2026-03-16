import io
import json
import urllib.error
import urllib.request

try:
    import pandas
except ImportError:
    pandas = None


def _flatten_dict(d, sep='.', _prefix=''):
    """Recursively flatten a nested dict using dot-notation keys.

    Example::

        >>> _flatten_dict({'a': {'b': 1}, 'c': 2})
        {'a.b': 1, 'c': 2}
    """
    out = {}
    for k, v in d.items():
        key = f'{_prefix}{sep}{k}' if _prefix else k
        if isinstance(v, dict):
            out.update(_flatten_dict(v, sep=sep, _prefix=key))
        else:
            out[key] = v
    return out


class Output:
    """Abstract base class for benchmark output sinks.

    Subclass this to implement custom output destinations.
    Must implement :meth:`write`. May optionally implement
    :meth:`get_results` to allow reading back stored results.

    Example::

        class MyOutput(Output):
            def write(self, bm_json_str):
                send_somewhere(bm_json_str)
    """

    def write(self, bm_json_str):
        """Write a single JSON-encoded benchmark result.

        Args:
            bm_json_str (str): JSON string (without trailing newline).
        """
        raise NotImplementedError

    def get_results(self, format='dict', flat=False):
        """Return all stored results.

        Args:
            format (str): ``'dict'`` (default) returns a list of dicts;
                ``'df'`` returns a pandas DataFrame (requires pandas).
            flat (bool): If *True*, flatten nested dict fields into
                dot-notation keys (e.g. ``slurm.job_id``). Works for
                both formats and does not require pandas.

        Raises:
            NotImplementedError: If this sink does not support reading results.
            ImportError: If *format* is ``'df'`` and pandas is not installed.
            ValueError: If *format* is not ``'dict'`` or ``'df'``.
        """
        raise NotImplementedError(
            f'{type(self).__name__} does not support get_results()'
        )


class FileOutput(Output):
    """Write benchmark results to a file path or file-like object (JSONL format).

    Each result is written as a single JSON line. When *outfile* is a path
    string, each write opens the file in append mode (POSIX ``O_APPEND``),
    which is safe for concurrent writers on the same filesystem. When
    *outfile* is a file-like object it is written to directly.

    When no *outfile* is given an :class:`io.StringIO` buffer is used,
    which allows results to be read back via :meth:`get_results`.

    Args:
        outfile (str or file-like, optional): Destination file path or
            file-like object. Defaults to a fresh :class:`io.StringIO`.
    """

    def __init__(self, outfile=None):
        if outfile is None:
            outfile = io.StringIO()
        self.outfile = outfile

    def write(self, bm_json_str):
        bm_str = bm_json_str + '\n'
        if isinstance(self.outfile, str):
            with open(self.outfile, 'a') as f:
                f.write(bm_str)
        else:
            self.outfile.write(bm_str)

    def get_results(self, format='dict', flat=False):
        if format not in ('dict', 'df'):
            raise ValueError(f"format must be 'dict' or 'df', got {format!r}")
        if format == 'df' and not pandas:
            raise ImportError('This functionality requires the "pandas" package')

        if hasattr(self.outfile, 'seek'):
            self.outfile.seek(0)
            content = self.outfile.read()
        else:
            with open(self.outfile) as f:
                content = f.read()

        if format == 'df' and not flat:
            return pandas.read_json(io.StringIO(content), lines=True)

        lines = [line for line in content.splitlines() if line.strip()]
        records = [json.loads(line) for line in lines]

        if flat:
            records = [_flatten_dict(r) for r in records]

        if format == 'dict':
            return records
        else:  # format == 'df' and flat
            return pandas.DataFrame(records)


class RedisOutput(Output):
    """Write benchmark results to a Redis list (one JSON string per record).

    Results are appended using ``RPUSH`` and can be read back via
    :meth:`get_results` using ``LRANGE``.

    Args:
        redis_key (str): Redis key for the result list.
        **redis_connection: Keyword arguments forwarded to
            ``redis.StrictRedis()`` (e.g. ``host``, ``port``).

    Example::

        from microbench import MicroBench, RedisOutput

        bench = MicroBench(outputs=[RedisOutput('microbench:mykey',
                                                host='localhost', port=6379)])
    """

    def __init__(self, redis_key, **redis_connection):
        import redis as _redis

        self.rclient = _redis.StrictRedis(**redis_connection)
        self.redis_key = redis_key

    def write(self, bm_json_str):
        self.rclient.rpush(self.redis_key, bm_json_str)

    def get_results(self, format='dict', flat=False):
        if format not in ('dict', 'df'):
            raise ValueError(f"format must be 'dict' or 'df', got {format!r}")
        if format == 'df' and not pandas:
            raise ImportError('This functionality requires the "pandas" package')

        redis_data = self.rclient.lrange(self.redis_key, 0, -1)
        lines = [r.decode('utf8') for r in redis_data]

        if format == 'df' and not flat:
            json_data = '\n'.join(lines)
            return pandas.read_json(io.StringIO(json_data), lines=True)

        records = [json.loads(line) for line in lines]

        if flat:
            records = [_flatten_dict(r) for r in records]

        if format == 'dict':
            return records
        else:  # format == 'df' and flat
            return pandas.DataFrame(records)


class HttpOutput(Output):
    """POST each benchmark result to an HTTP/HTTPS endpoint.

    Designed for webhooks and real-time notifications (e.g. Slack, Teams,
    custom event endpoints). Not intended for bulk storage — there is no
    :meth:`get_results` support.

    Uses only the Python standard library (``urllib``). Raises on non-2xx
    responses or network failures — no silent dropping, no automatic retry.

    By default the record dict is JSON-encoded and sent with
    ``Content-Type: application/json``. Override :meth:`format_payload` in a
    subclass to produce any body shape required by the target provider (e.g.
    a Slack ``{"text": ...}`` envelope).

    Args:
        url (str): Endpoint URL. Must be ``http://`` or ``https://``.
        headers (dict, optional): Extra HTTP headers merged with the defaults.
            Caller-supplied keys win on collision (case-sensitive). Use this
            for authentication (e.g. ``{'Authorization': 'Bearer <token>'}``).
            Defaults to ``None``.
        timeout (float, optional): Request timeout in seconds passed to
            :func:`urllib.request.urlopen`. Defaults to ``30.0``.
        method (str, optional): HTTP method. Defaults to ``'POST'``.

    Raises:
        urllib.error.HTTPError: If the server returns a non-2xx status code.
        urllib.error.URLError: If a network-level error occurs (DNS failure,
            connection refused, etc.).

    Example — basic usage::

        from microbench import MicroBench, HttpOutput

        bench = MicroBench(outputs=[HttpOutput('https://example.com/events')])

    Example — bearer token authentication::

        from microbench import MicroBench, HttpOutput

        bench = MicroBench(outputs=[HttpOutput(
            'https://api.example.com/benchmarks',
            headers={'Authorization': 'Bearer my-secret-token'},
        )])

    Example — Slack webhook via subclass::

        import json
        from microbench import MicroBench, HttpOutput

        class SlackOutput(HttpOutput):
            def format_payload(self, record):
                name = record.get('call', {}).get('name', '?')
                return json.dumps({'text': f'Benchmark `{name}` finished.'}).encode()

        bench = MicroBench(outputs=[SlackOutput('https://hooks.slack.com/services/...')])
    """

    def __init__(self, url, *, headers=None, timeout=30.0, method='POST'):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self.method = method.upper()

    def format_payload(self, record):
        """Encode *record* as the HTTP request body.

        The default implementation JSON-encodes the record dict and returns
        UTF-8 bytes. Subclasses may override this to produce any body shape
        required by the target provider.

        Args:
            record (dict): Decoded benchmark result dict.

        Returns:
            bytes: Request body.
        """
        return json.dumps(record).encode('utf-8')

    def _build_request(self, record):
        body = self.format_payload(record)
        if isinstance(body, str):
            body = body.encode('utf-8')
        default_headers = {'Content-Type': 'application/json'}
        merged_headers = {**default_headers, **self.headers}
        return urllib.request.Request(
            self.url,
            data=body,
            headers=merged_headers,
            method=self.method,
        )

    def write(self, bm_json_str):
        """POST *bm_json_str* to the configured URL.

        Args:
            bm_json_str (str): JSON-encoded benchmark record, as produced by
                :meth:`MicroBenchBase.to_json`.

        Raises:
            urllib.error.HTTPError: On a non-2xx HTTP response.
            urllib.error.URLError: On a network-level error.
        """
        record = json.loads(bm_json_str)
        request = self._build_request(record)
        with urllib.request.urlopen(request, timeout=self.timeout):
            pass
