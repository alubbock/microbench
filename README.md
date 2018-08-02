# Microbench

Microbench is a small Python package for benchmarking Python functions, and 
optionally capturing extra runtime/environment information. It can be run in 
clustered/distributed environments, and is designed to be extensible with new
functionality.

## Feedback

Please note this is a recently created, experimental package. Please let me know
your feedback or feature requests in Github issues.

## Requirements

Microbench has no dependencies outside of the Python standard library, although 
[pandas](https://pandas.pydata.org/) is recommended to examine results.

## Installation

To install using `pip`:

```
pip install microbench
```

## Usage

### 1. Create a benchmark suite

First, create a benchmark suite, which specifies the configuration and
information to capture. By default, 
benchmarks are appended to a file in JSON format (one record per line) to a
filename specified by `outfile`. 

Here's a minimalist example:

```python
from microbench import MicroBench

class MyBasicBench(MicroBench):
    outfile = '/home/user/my-benchmarks'
    
basic_bench = MyBasicBench()
```

Here's a more complete example using mixins (the `MB` prefixed class 
names) to extend functionality. Note that keyword arguments can be supplied
to the constructor (in this case `some_info=123` to specify additional
information to capture).

```python
from microbench import *

class MyBench(MicroBench, MBFunctionCall, MBPythonVersion, MBHostInfo):
    outfile = '/home/user/my-benchmarks'
    
benchmark = MyBench(some_info=123)
```

### 2. Decorate functions with @benchmark

To use the benchmark suite, simply use `benchmark`, defined above, as a
decorator on the function you wish to benchmark:

```python
@benchmark
def myfunction():
    # Some inefficient function for test purposes
    result = 0
    for i in range(1000):
         result *= i
     return result
```

That's it! You'll now get start and end time, function call information,
Python version information, and host info logged to the file specified in
`outfile`.

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

Here's an example to capture the numpy version:

```python
from microbench import MicroBench

class NumpyBench(MicroBench):
    outfile = '/home/user/my-benchmarks'
    
    def capture_numpy_version(self, bm_data):
        import numpy
        bm_data['numpy_version'] = numpy.__version__ 
        
numpy_bench = NumpyBench()
```
