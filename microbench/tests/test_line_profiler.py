from microbench import MicroBench, MBLineProfiler
import pandas


def test_line_profiler():
    class LineProfilerBench(MicroBench, MBLineProfiler):
        pass

    lpbench = LineProfilerBench()

    @lpbench
    def my_function():
        """ Inefficient function for line profiler """
        acc = 0
        for i in range(1000000):
            acc += i

        return acc

    for _ in range(3):
        assert my_function() == 499999500000

    results = pandas.read_json(lpbench.outfile.getvalue(), lines=True)
    lp = MBLineProfiler.decode_line_profile(results['line_profiler'][0])
    assert lp.__class__.__name__ == 'LineStats'
    MBLineProfiler.print_line_profile(results['line_profiler'][0])
    assert not all(len(v) == 0 for v in lp.timings.values()), "No timings present"
