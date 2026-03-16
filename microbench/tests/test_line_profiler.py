from unittest.mock import patch

import pytest

import microbench
from microbench import MBLineProfiler, MicroBench


def test_line_profiler_missing_package():
    """MBLineProfiler raises ImportError when line_profiler is not installed."""

    class Bench(MicroBench, MBLineProfiler):
        pass

    bench = Bench()

    @bench
    def noop():
        pass

    with patch.object(microbench, 'line_profiler', None):
        with pytest.raises(ImportError, match='line_profiler'):
            noop()


def test_line_profiler():
    class LineProfilerBench(MicroBench, MBLineProfiler):
        pass

    lpbench = LineProfilerBench()

    @lpbench
    def my_function():
        """Inefficient function for line profiler"""
        acc = 0
        for i in range(1000000):
            acc += i

        return acc

    for _ in range(3):
        assert my_function() == 499999500000

    results = lpbench.get_results()
    lp = MBLineProfiler.decode_line_profile(results[0]['call']['line_profiler'])
    assert lp.__class__.__name__ == 'LineStats'
    MBLineProfiler.print_line_profile(results[0]['call']['line_profiler'])
    assert not all(len(v) == 0 for v in lp.timings.values()), 'No timings present'
