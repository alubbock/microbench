from microbench import MicroBench, MBGlobalPackages
import pandas  # Imported just to test capturing the version

# Define this in a separate file to make sure we are capturing globals when
# globals_bench is called, not here


class GlobalsBench(MicroBench, MBGlobalPackages):
    pass


globals_bench = GlobalsBench()
