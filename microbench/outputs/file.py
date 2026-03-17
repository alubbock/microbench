"""FileOutput — write benchmark results to a file or StringIO buffer."""

import io
import json

try:
    import pandas
except ImportError:
    pandas = None

from .base import Output
from .utils import _flatten_dict


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
