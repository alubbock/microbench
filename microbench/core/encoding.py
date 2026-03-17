"""JSON encoding utilities for microbench.

Provides a JSONEncoder that handles datetime, timedelta, timezone,
and numpy scalar/array types, plus a warning class and placeholder
value for unencodable objects.
"""

import json
from datetime import datetime, timedelta, timezone

try:
    import numpy
except ImportError:
    numpy = None


class JSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, timedelta):
            return o.total_seconds()
        if isinstance(o, timezone):
            return str(o)
        if numpy:
            if isinstance(o, numpy.integer):
                return int(o)
            elif isinstance(o, numpy.floating):
                return float(o)
            elif isinstance(o, numpy.ndarray):
                return o.tolist()

        return super().default(o)


class JSONEncodeWarning(Warning):
    """Warning used when JSON encoding fails"""

    pass


_UNENCODABLE_PLACEHOLDER_VALUE = '__unencodable_as_json__'
