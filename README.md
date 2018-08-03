# Microbench

Microbench is a small Python package for benchmarking Python functions, and 
optionally capturing extra runtime/environment information. It is most useful in
clustered/distributed environments, where the same function runs under different
environments, and is designed to be extensible with new
functionality. In addition to benchmarking, this can help reproducibility by
e.g. logging the versions of key Python packages.

## Requirements

Microbench has no dependencies outside of the Python standard library, although 
[pandas](https://pandas.pydata.org/) is recommended to examine results.

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
`outfile`. See the **Examine results** section for information on reading
the results.

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
    capture_versions = (numpy, pandas)
    
benchmark = MyBench(some_info=123)
```

 Mixin                 | Fields captured
-----------------------|----------------
*(default)*            | `start_time`<br>`finish_time`<br>`function_name`
MBFunctionCall         | `args` (positional arguments)<br>`kwargs` (keyword arguments)
MBPythonVersion        | `python_version` (e.g. 3.6.0)
MBHostInfo             | `hostname`<br>`operating_system`

The `capture_versions` option from the example creates fields like
`<package name>_version`, e.g. `numpy_version`. This is captured from the
package's `__name__` attribute, or left as `null` where not available.

## Examine results

Each result is a [JSON](https://en.wikipedia.org/wiki/JSON) object. When using
the `outfile` option, a JSON object for each `@benchmark` call is stored on a
separate line in the file.

The simplest way to examine results is to load them into a
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
