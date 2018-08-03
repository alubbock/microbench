# Microbench

Microbench is a small Python package for benchmarking Python functions, and 
optionally capturing extra runtime/environment information. It can be run in 
clustered/distributed environments, and is designed to be extensible with new
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

## Examine results

The simplest way to examine results is to load them into a
[pandas](https://pandas.pydata.org/) dataframe:

```python
import pandas
results = pandas.read_json('/home/user/my-benchmarks', lines=True)
```

## Extending microbench

Microbench includes a few mixins for basic functionality: function call
information (name and arguments), Python version, host information (host name
and OS). You can add extra functions to your benchmark suite to capture
extra information at runtime. These functions must be prefixed with `capture_`
for them to run automatically after the function has completed. They take
a single argument, `bm_data`, a dictionary to be extended with extra values.
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
