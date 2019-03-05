# Microbench

Microbench is a small Python package for benchmarking Python functions, and 
optionally capturing extra runtime/environment information. It is most useful in
clustered/distributed environments, where the same function runs under different
environments, and is designed to be extensible with new
functionality. In addition to benchmarking, this can help reproducibility by
e.g. logging the versions of key Python packages, or even all packages loaded
into the global environment.

## Requirements

Microbench has no dependencies outside of the Python standard library, although 
[pandas](https://pandas.pydata.org/) is recommended to examine results. The
[line_profiler](https://github.com/rkern/line_profiler) package needs to be
installed for line-by-line code benchmarking (described in a later section).

## Installation

To install using `pip`:

```
pip install microbench
```

## Usage

Microbench is designed for benchmarking Python functions. These examples will
assume you have already defined a Python function `myfunction` that you wish to
benchmark:

```python
def myfunction(arg1, arg2, ...):
    ...
```

### Minimal example

First, create a benchmark suite, which specifies the configuration and
information to capture. By default, 
benchmarks are appended to a file in JSON format (one record per line) to a
filename specified by `outfile`. 

Here's a minimal, complete example:

```python
from microbench import MicroBench

class BasicBench(MicroBench):
    outfile = '/home/user/my-benchmarks'
    
basic_bench = BasicBench()
```

To attach the benchmark to your function, simply use `basic_bench` as a
decorator, like this:

```python
@basic_bench
def myfunction(arg1, arg2, ...):
    ...
```

That's it! Benchmark information will be appended to the file specified in
`outfile`. This example captures the fields `start_time`, `finish_time` and
`function_name`. See the **Examine results** section for further information.

### Extended example

Here's a more complete example using mixins (the `MB` prefixed class 
names) to extend functionality. Note that keyword arguments can be supplied
to the constructor (in this case `some_info=123`) to specify additional
information to capture.

```python
from microbench import *
import numpy, pandas

class MyBench(MicroBench, MBFunctionCall, MBPythonVersion, MBHostInfo):
    outfile = '/home/user/my-benchmarks'
    capture_versions = (numpy, pandas)  # Or use MBGlobalPackages
    env_vars = ('SLURM_ARRAY_TASK_ID', )
    
benchmark = MyBench(some_info=123)
```

To capture package versions, you can either specify them individually (as above), or you can capture the versions of
every package in the global environment. In the following example, we would capture the versions of `microbench`,
`numpy`, and `pandas` automatically.

```python
from microbench import *
import numpy, pandas

class Bench2(MicroBench, MBGlobalPackages):
    outfile = '/home/user/bench2'

bench2 = Bench2()
```

 Mixin                 | Fields captured
-----------------------|----------------
*(default)*            | `start_time`<br>`finish_time`<br>`function_name`
MBGlobalPackages       | `<package>_version` for every `<package>` in the global environment
MBFunctionCall         | `args` (positional arguments)<br>`kwargs` (keyword arguments)
MBPythonVersion        | `python_version` (e.g. 3.6.0)
MBHostInfo             | `hostname`<br>`operating_system`
MBLineProfiler         | `line_profiler` containing line-by-line profile (see section below)

The `capture_versions` option from the example creates fields like
`<package name>_version`, e.g. `numpy_version`. This is captured from the
package's `__name__` attribute, or left as `null` where not available.

The `env_vars` option from the example above specifies a list of environment
variables to capture as `env_<variable name>`. In this example,
the [slurm](https://slurm.schedmd.com) array task ID will be stored as
`env_SLURM_ARRAY_TASK_ID`. Where the environment variable is not set, the
value will be `null`.

## Examine results

Each result is a [JSON](https://en.wikipedia.org/wiki/JSON) object. When using
the `outfile` option, a JSON object for each `@benchmark` call is stored on a
separate line in the file. The output from the minimal example above for a
single run will look similar to the following:

```json
{"start_time": "2018-08-06T10:28:24.806493", "finish_time": "2018-08-06T10:28:24.867456", "function_name": "my_function"}
```

The simplest way to examine results in detail is to load them into a
[pandas](https://pandas.pydata.org/) dataframe:

```python
import pandas
results = pandas.read_json('/home/user/my-benchmarks', lines=True)
```

Pandas has powerful data manipulation capabilities. For example, to calculate
the average runtime by Python version:

```python
# Calculate runtime for each run
results['runtime'] = results['finish_time'] - results['start_time']

# Average runtime by Python version
results.groupby('python_version')['runtime'].mean()
```

Many more advanced operations are available. The
[pandas tutorial](https://pandas.pydata.org/pandas-docs/stable/tutorials.html)
is recommended.

## Interactive usage

Microbench can be used in scripts, packages, or interactively from the Python prompt, IPython prompt, or a Jupyter
Notebook. When using the package interactively, you may not want to write the results to a file. In that case, you can
use `io.StringIO` to capture the output as a string:

```python
from microbench import *
import io

class MyBench(MicroBench):
    outfile = io.stringIO()

my_bench = MyBench()

# Dummy function for testing
@my_bench
def test():
    pass

# Call the dummy function twice
# (triggering benchmark capture both times)
test()
test()

# Read the benchmark results
import pandas
results = pandas.read_json(my_bench.outfile.getvalue(), lines=True)

# results is a Pandas DataFrame containing captured metadata

```

## Line profiler support

Microbench also has support for [line_profiler](https://github.com/rkern/line_profiler), which shows the execution time
of each line of Python code. Note that this will slow down your code, so only use it if needed, but it's useful for
discovering bottlenecks within a function. Requires the `line_profiler` package to be installed
(e.g. `pip install line_profiler`).

```python
from microbench import MicroBench, MBLineProfiler
import io
import pandas

# Create our benchmark suite using the MBLineProfiler mixin
class LineProfilerBench(MicroBench, MBLineProfiler):
    outfile = io.StringIO()

lpbench = LineProfilerBench()

# Decorate our function with the benchmark suite
@lpbench
def my_function():
    """ Inefficient function for line profiler """
    acc = 0
    for i in range(1000000):
        acc += i

    return acc

# Call the function as normal
my_function()

# Read the results into a Pandas DataFrame
results = pandas.read_json(lpbench.outfile.getvalue(), lines=True)

# Get the line profiler report as an object
lp = MBLineProfiler.decode_line_profile(results['line_profiler'][0])

# Print the line profiler report
MBLineProfiler.print_line_profile(results['line_profiler'][0])
```

The last line of the previous example will print the line profiler report, showing the execution time of each line of
code. Example:

```
Timer unit: 1e-06 s

Total time: 0.476723 s
File: /home/user/my_test.py
Function: my_function at line 12

Line #      Hits         Time  Per Hit   % Time  Line Contents
==============================================================
    12                                               @lpbench
    13                                               def my_function():
    14                                                   """ Inefficient function for line profiler """
    15         1          2.0      2.0      0.0          acc = 0
    16   1000001     217874.0      0.2     45.7          for i in range(1000000):
    17   1000000     258846.0      0.3     54.3              acc += i
    18
    19         1          1.0      1.0      0.0          return acc
```

## Extending microbench

Microbench includes a few mixins for basic functionality as described in the
extended example, above.

You can add functions to your benchmark suite to capture
extra information at runtime. These functions must be prefixed with `capture_`
for them to run automatically after the function has completed. They take
a single argument, `bm_data`, a dictionary to be extended with extra data.
Care should be taken to avoid overwriting existing key names.

Here's an example to capture the machine type (`i386`, `x86_64` etc.):

```python
from microbench import MicroBench
import platform

class Bench(MicroBench):
    outfile = '/home/user/my-benchmarks'

    def capture_machine_platform(self, bm_data):
        bm_data['platform'] = platform.machine()
        
benchmark = Bench()
```

## Redis support

By default, microbench appends output to a file, but output can be directed
elsewhere, e.g. [redis](https://redis.io) - an in-memory, networked data source.
This option is useful when a shared filesystem is not available.

Redis support requires [redis-py](https://github.com/andymccurdy/redis-py).

To use this feature, inherit from `MicroBenchRedis` instead of `MicroBench`,
and specify the redis connection and key name as in the following example:

```python
from microbench import MicroBenchRedis

class RedisBench(MicroBenchRedis):
    # redis_connection contains arguments for redis.StrictClient()
    redis_connection = {'host': 'localhost', 'port': 6379}
    redis_key = 'microbench:mykey'

benchmark = RedisBench()
```

To retrieve results, the `redis` package can be used directly:

```python
import redis
import pandas

# Establish the connection to redis
rconn = redis.StrictRedis(host=..., port=...)

# Read the redis data from 'myrediskey' into a list of byte arrays
redis_data = redis.lrange('myrediskey', 0, -1)

# Convert the list into a single string
json_data = '\n'.join(r.decode('utf8') for r in redis_data)

# Read the string into a pandas dataframe
results = pandas.read_json(json_data, lines=True)
```

## Feedback

Please note this is a recently created, experimental package. Please let me know
your feedback or feature requests in Github issues.
