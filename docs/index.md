# microbench

![Microbench: Benchmarking and reproducibility metadata capture for Python](https://raw.githubusercontent.com/alubbock/microbench/master/microbench.png)

Microbench is a small Python package for benchmarking Python functions and
capturing reproducibility metadata. It is most useful in clustered and
distributed environments where the same function runs across different
machines, and is designed to be extended with new functionality through
mixins.

## Key features

- **Zero-config timing** — decorate a function and get start/finish timestamps and run durations immediately, with no setup
- **Command-line interface** — wrap any shell command or compiled executable with `python -m microbench -- COMMAND` and capture host metadata alongside timing without writing Python code; ideal for SLURM jobs
- **Extensible via mixins** — mix in exactly what you need: Python version, hostname, CPU/RAM specs, conda/pip packages, NVIDIA GPU info, line-level profiling, and more
- **Cluster and HPC ready** — capture SLURM environment variables, psutil resource metrics, and run IDs for correlating results across nodes
- **JSONL output** — one JSON object per call; load directly into pandas with `read_json(..., lines=True)`; no schema lock-in
- **Automatic run correlation** — `mb.run_id` is a UUID generated once per process; all bench suites in the same run share it, enabling `groupby('mb.run_id')` across independent suites
- **Flexible output** — write to a local file, an in-memory buffer, or Redis; concurrent writers safe via `O_APPEND`

## Installation

```
pip install microbench
```

## Requirements

Microbench has no required dependencies outside the Python standard library.
[pandas](https://pandas.pydata.org/) is recommended for analysing results.
Some mixins have optional requirements:

| Mixin / feature | Requires |
|---|---|
| `MBHostCpuCores`, `MBHostRamTotal`, periodic monitoring | [psutil](https://pypi.org/project/psutil/) |
| `MBLineProfiler` | [line_profiler](https://github.com/rkern/line_profiler) |
| `MBNvidiaSmi` | `nvidia-smi` on `PATH` (ships with NVIDIA drivers) |
| `MBCondaPackages` | `conda` on `PATH` |
| `RedisOutput` | [redis-py](https://github.com/andymccurdy/redis-py) |
| `LiveStream` | [python-dateutil](https://pypi.org/project/python-dateutil/) |
| `envdiff` | [IPython](https://ipython.org/) |

## Quick example

```python
from microbench import MicroBench

bench = MicroBench(outfile='/home/user/results.jsonl', experiment='baseline')

@bench
def my_function(n):
    return sum(range(n))

my_function(1_000_000)

results = bench.get_results()
```

Each call produces one record. With `get_results(flat=True)` the record looks
like:

```
   mb.run_id                             mb.version  call.name   call.durations  experiment
0  3f2a1b4c-8d9e-4f2a-b1c3-d4e5f6a7b8c9  2.0.0      my_function  [0.049823]     baseline
```

The underlying JSON for a single record looks like:

```json
{
  "mb": {
    "run_id": "3f2a1b4c-8d9e-4f2a-b1c3-d4e5f6a7b8c9",
    "version": "2.0.0",
    "timezone": "UTC",
    "duration_counter": "perf_counter"
  },
  "call": {
    "invocation": "Python",
    "name": "my_function",
    "start_time": "2024-01-15T10:30:00.123456+00:00",
    "finish_time": "2024-01-15T10:30:00.172279+00:00",
    "durations": [0.049823]
  },
  "python": {
    "version": "3.12.4",
    "prefix": "/opt/conda/envs/myenv",
    "executable": "/opt/conda/envs/myenv/bin/python"
  },
  "experiment": "baseline"
}
```

See [Getting started](getting-started.md) for a full walkthrough.
