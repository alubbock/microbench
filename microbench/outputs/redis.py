"""RedisOutput — write benchmark results to a Redis list."""

import io
import json

try:
    import pandas
except ImportError:
    pandas = None

from .base import Output
from .utils import _flatten_dict


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
