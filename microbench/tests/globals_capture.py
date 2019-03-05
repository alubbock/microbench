from microbench import MicroBench, MBGlobalPackages
import io


# Define this in a separate file to make sure we are capturing globals when
# globals_bench is called, not here

class GlobalsBench(MicroBench, MBGlobalPackages):
    outfile = io.StringIO()


globals_bench = GlobalsBench()
