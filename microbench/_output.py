import io

try:
    import pandas
except ImportError:
    pandas = None


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

    def get_results(self):
        """Return all stored results as a pandas DataFrame.

        Raises:
            NotImplementedError: If this sink does not support reading results.
            ImportError: If pandas is not installed.
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

    def get_results(self):
        if not pandas:
            raise ImportError('This functionality requires the "pandas" package')
        if hasattr(self.outfile, 'seek'):
            self.outfile.seek(0)
        return pandas.read_json(self.outfile, lines=True)


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

    def get_results(self):
        if not pandas:
            raise ImportError('This functionality requires the "pandas" package')
        redis_data = self.rclient.lrange(self.redis_key, 0, -1)
        json_data = '\n'.join(r.decode('utf8') for r in redis_data)
        return pandas.read_json(io.StringIO(json_data), lines=True)
