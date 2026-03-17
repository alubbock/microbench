"""Abstract base class for benchmark output sinks."""


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
