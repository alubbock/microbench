"""Profiling mixins: MBPeakMemory, MBLineProfiler."""

import base64
import pickle

try:
    import line_profiler
except ImportError:
    line_profiler = None


class MBPeakMemory:
    """Capture peak Python memory allocation during the benchmarked function.

    Uses :mod:`tracemalloc` from the Python standard library (no extra
    dependencies). Records the peak memory allocated in bytes across all
    iterations as ``call.peak_memory_bytes``.

    Note:
        ``tracemalloc`` tracks memory that goes through Python's allocator,
        which covers Python objects and most C-extension allocations. Memory
        allocated directly via ``malloc`` in C extensions (e.g. some large
        NumPy arrays) is not tracked.

        CLI compatible.
    """

    def capture_peak_memory(self, bm_data):
        import tracemalloc

        self._tracemalloc_was_tracing = tracemalloc.is_tracing()
        if self._tracemalloc_was_tracing:
            tracemalloc.reset_peak()
        else:
            tracemalloc.start()

    def capturepost_peak_memory(self, bm_data):
        import tracemalloc

        _, peak = tracemalloc.get_traced_memory()
        bm_data.setdefault('call', {})['peak_memory_bytes'] = peak
        if not self._tracemalloc_was_tracing:
            tracemalloc.stop()


class MBLineProfiler:
    """
    Run the line profiler on the selected function

    Requires the line_profiler package. This will generate a benchmark which
    times the execution of each line of Python code in your function. This will
    slightly slow down the execution of your function, so it's not recommended
    in production.

    Results are stored in ``call.line_profiler`` as a base64-encoded pickled
    ``LineStats`` object.
    """

    def capturepost_line_profile(self, bm_data):
        bm_data.setdefault('call', {})['line_profiler'] = base64.b64encode(
            pickle.dumps(self._line_profiler.get_stats())
        ).decode('utf8')

    @staticmethod
    def decode_line_profile(line_profile_pickled):
        """Decode a base64-encoded pickled line profiler result.

        Security note: This uses pickle.loads, which can execute arbitrary
        code. Only call this on data from a trusted source (e.g. your own
        benchmark output files). Do not decode line profile data received
        over a network or from an untrusted file.
        """
        return pickle.loads(base64.b64decode(line_profile_pickled))

    @classmethod
    def print_line_profile(cls, line_profile_pickled, **kwargs):
        lp_data = cls.decode_line_profile(line_profile_pickled)
        line_profiler.show_text(lp_data.timings, lp_data.unit, **kwargs)
