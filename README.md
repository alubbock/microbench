# Microbench

![Microbench: Benchmarking and reproducibility metadata capture for Python](https://raw.githubusercontent.com/alubbock/microbench/master/microbench.png)

Microbench is a small Python package for benchmarking Python functions, and 
optionally capturing extra runtime/environment information. It is most useful in
clustered/distributed environments, where the same function runs under different
environments, and is designed to be extensible with new
functionality. In addition to benchmarking, this can help reproducibility by
e.g. logging the versions of key Python packages, or even all packages loaded
into the global environment. Other captured metadata can include CPU and RAM
usage, environment variables, and hardware specifications.

## Requirements

Microbench by default has no dependencies outside of the Python standard
library, although [pandas](https://pandas.pydata.org/) is recommended to
examine results. However, some mixins (extensions) have specific requirements:

* The [line_profiler](https://github.com/rkern/line_profiler)
  package needs to be installed for line-by-line code benchmarking.
* `MBInstalledPackages` requires `setuptools`, which is not a part of the
  standard library, but is usually available. 
* The CPU cores, total RAM, and telemetry extensions require
  [psutil](https://pypi.org/project/psutil/).
* The NVIDIA GPU plugin requires the
  [nvidia-smi](https://developer.nvidia.com/nvidia-system-management-interface)
  utility, which usually ships with the NVIDIA graphics card drivers. It needs
  to be on your `PATH`.

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
information to capture.

Here's a minimal, complete example:

```python
from microbench import MicroBench
    
basic_bench = MicroBench()
```

To attach the benchmark to your function, simply use `basic_bench` as a
decorator, like this:

```python
@basic_bench
def myfunction(arg1, arg2, ...):
    ...
```

That's it! When `myfunction()` is called, metadata will be captured
into a `io.StringIO()` buffer, which can be read as follows
(using the `pandas` library):

```python
import pandas as pd
results = pd.read_json(basic_bench.outfile.getvalue(), lines=True)
```

The above example captures the fields `start_time`, `finish_time` and
`function_name`. Microbench can capture many other types of metadata
from the environment, resource usage, and hardware,
which are covered below.

### Extended examples

Here's a more complete example using mixins (the `MB` prefixed class 
names) to extend functionality. Note that keyword arguments can be supplied
to the constructor (in this case `some_info=123`) to specify additional
information to capture. This example also specifies the `outfile` option,
which appends metadata to a file on disk.

```python
from microbench import *
import numpy, pandas

class MyBench(MicroBench, MBFunctionCall, MBPythonVersion, MBHostInfo):
    outfile = '/home/user/my-benchmarks'
    capture_versions = (numpy, pandas)  # Or use MBGlobalPackages/MBInstalledPackages
    env_vars = ('SLURM_ARRAY_TASK_ID', )
    
benchmark = MyBench(some_info=123)
```

The `env_vars` option from the example above specifies a list of environment
variables to capture as `env_<variable name>`. In this example,
the [slurm](https://slurm.schedmd.com) array task ID will be stored as
`env_SLURM_ARRAY_TASK_ID`. Where the environment variable is not set, the
value will be `null`.

To capture package versions, you can either specify them individually (as
above), or you can capture the versions of every package in the global
environment. In the following example, we would capture the versions of
`microbench`, `numpy`, and `pandas` automatically.

```python
from microbench import *
import numpy, pandas

class Bench2(MicroBench, MBGlobalPackages):
    outfile = '/home/user/bench2'

bench2 = Bench2()
```

If you want to go even further, and capture the version of every package
available for import, there's a mixin for that:

```python
from microbench import *

class Bench3(MicroBench, MBInstalledPackages):
    pass
    
bench3 = Bench3()
``` 

 Mixin                 | Fields captured
-----------------------|----------------
*(default)*            | `start_time`<br>`finish_time`<br>`function_name`
MBGlobalPackages       | `package_versions`, with entry for every package in the global environment
MBInstalledPackages    | `package_versions`, with entry for every package available for import
MBCondaPackages        | `conda_versions`, with entry for every conda package in the environment
MBFunctionCall         | `args` (positional arguments)<br>`kwargs` (keyword arguments)
MBReturnValue          | Wrapped function's return value
MBPythonVersion        | `python_version` (e.g. 3.6.0) and `python_executable` (e.g. `/usr/bin/python`, which should indicate any active virtual environment)
MBHostInfo             | `hostname`<br>`operating_system`
MBHostCpuCores         | `cpu_cores_logical` (number of cores, requires `psutil`)
MBHostRamTotal         | `ram_total` (total RAM in bytes, requires `psutil`)
MBNvidiaSmi            | Various NVIDIA GPU fields, detailed in a later section
MBLineProfiler         | `line_profiler` containing line-by-line profile (see section below)

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

## Line profiler support

Microbench also has support for [line_profiler](https://github.com/rkern/line_profiler), which shows the execution time
of each line of Python code. Note that this will slow down your code, so only use it if needed, but it's useful for
discovering bottlenecks within a function. Requires the `line_profiler` package to be installed
(e.g. `pip install line_profiler`).

```python
from microbench import MicroBench, MBLineProfiler
import pandas

# Create our benchmark suite using the MBLineProfiler mixin
class LineProfilerBench(MicroBench, MBLineProfiler):
    pass

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

## NVIDIA GPU support

Attributes about NVIDIA GPUs can be captured using the `MBNvidiaSmi` plugin.
This requires the `nvidia-smi` utility to be available in the current `PATH`.

By default, the `gpu_name` (model number) and `memory.total` attributes are
captured. Extra attributes can be specified using the class or object-level
variable `nvidia_attributes`. To see which attributes are available, run
`nvidia-smi --help-query-gpu`.

By default, all installed GPUs will be polled. To limit to a specific GPU,
specify the `nvidia_gpus` attribute as a tuple of GPU IDs, which can be
zero-based GPU indexes (can change between reboots, not recommended),
GPU UUIDs, or PCI bus IDs. You can find out GPU UUIDs by running
`nvidia-smi -L`.

Here's an example specifying the optional `nvidia_attributes` and
`nvidia_gpus` fields:

```python
from microbench import MicroBench, MBNvidiaSmi

class GpuBench(MicroBench, MBNvidiaSmi):
    outfile = '/home/user/gpu-benchmarks'
    nvidia_attributes = ('gpu_name', 'memory.total', 'pcie.link.width.max')
    nvidia_gpus = (0, )  # Usually better to specify GPU UUIDs here instead

gpu_bench = GpuBench()
```

## Telemetry support

We use the term "telemetry" to refer to metadata which is captured periodically
during the execution of a function by a thread which runs in parallel. For
example, this may be useful to see how memory usage changes over time.

Telemetry support requires the `psutil` library.

Microbench launches and cleans up the monitoring thread automatically.
The end user only needs to define a `telemetry` static method, which accepts
a [psutil.Process](https://psutil.readthedocs.io/en/latest/#psutil.Process)
object and returns the telemetry data as a dictionary.

The default telemetry collection interval is every 60 seconds, which can be
customized if needed using the `telemetry_interval` class variable.

A minimal example to capture memory usage every 90 seconds is shown below:

```python
from microbench import MicroBench

class TelemBench(MicroBench):
    telemetry_interval = 90

    @staticmethod
    def telemetry(process):
        return process.memory_full_info()._asdict()

telem_bench = TelemBench()
```

## Extending microbench

Microbench includes a few mixins for basic functionality as described in the
extended example, above.

You can also add functions to your benchmark suite to capture
extra information at runtime. These functions must be prefixed with `capture_`
for them to run automatically before the function starts. They take
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

## Extending JSONEncoder

Microbench encodes data in JSON, but sometimes Microbench will
encounter data types (like custom objects or classes)
that are not encodable as JSON by default (usually meaning they
don't have a way to be represented as a string, list, or
dictionary). For example, when using the `MBFunctionCall` and
`MBReturnValue`, a warning will be shown if any argument or
return value (respectively) is not encodable as JSON, and the
value will be replaced with a placeholder to allow the metadata
capture to continue, and a warning will be shown.

If you wish to actually capture those values, you will need to
specify a way to convert the object to JSON. This is done using
by extending `microbench.JSONEncoder` with a test for the object
type and implementing a conversion to a string, list, or dict.

For example, to capture a `Graph` object from the `igraph`
package using `str(graph)` as the representation, we could
do the following (note that we could use any representation
we want, e.g. if we wanted to capture the object in a more
or less detailed way):

```
import microbench as mb
from igraph import Graph

# Extend the JSONEncoder to encode Graph objects
class CustomJSONEncoder(mb.JSONEncoder):
    def default(self, o):
        # Encode igraph.Graph objects as strings
        if isinstance(o, Graph):
            return str(o)

        # Add further isinstance(o, ...) cases here
        # if needed

        # Make sure to call super() to handle
        # default cases
        return super().default(o)

# Define your benchmark class as normal
class Bench(mb.MicroBench, mb.MBReturnValue):
    pass

# Create a benchmark suite with the custom JSON
# encoder from above
bench = Bench(json_encoder=CustomJSONEncoder)

# Attach the benchmark suite to our function
@bench
def return_a_graph():
    return Graph(2, ((0, 1), (0, 2)))

# This should now work without warnings or errors
return_a_graph()
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

## Runtime impact considerations

The runtime impact varies depending on what information is captured and by platform.
Broadly, capturing environment variables, Python package versions, and timing
information for a function has a negligible impact. Capturing telemetry and
invoking external programs (like `nvidia-smi` for GPU information) has a larger impact,
although the latter is a one-off per invocation and typically less than one second.
Telemetry capture intervals should be kept relatively infrequent (e.g., every minute
or two, rather than every second) to avoid significant runtime impacts.

## Feedback

Please note this is a recently created, experimental package. Please let me know
your feedback or feature requests in Github issues.
