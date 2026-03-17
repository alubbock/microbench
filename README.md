# Microbench

![Microbench: Benchmarking and reproducibility metadata capture for Python](https://raw.githubusercontent.com/alubbock/microbench/master/microbench.png)

Microbench benchmarks Python functions and automatically records the context
alongside the timings: Python version, package versions, hostname, hardware,
environment variables, and more. When performance varies across machines, runs,
or environments, the metadata tells you why — and when you need to reproduce a
result, the metadata shows exactly what was running.

## Key features

- **Zero-config timing** — decorate a function, get timestamps and run
  durations immediately, no setup required
- **Command-line interface** — wrap any shell command, script, or compiled
  executable with `python -m microbench -- COMMAND` and capture host
  metadata alongside timing without writing Python code; ideal for SLURM
  jobs; use `--monitor-interval` to record CPU and memory usage over time
- **Extensible via _mixins_** — capture Python version, hostname, CPU/RAM
  specs, conda/pip package versions, NVIDIA GPU info, line-level profiles,
  peak memory usage, and more by adding mixin classes
- **Cluster and HPC ready** — capture SLURM environment variables, psutil
  resource metrics, and per-process run IDs for correlating results across
  nodes
- **JSONL output** — one JSON object per call; load into pandas with
  `read_json(..., lines=True)`; flexibility to add any extra fields you
  need
- **Flexible output** — write to a local file, in-memory buffer, Redis, HTTP
  endpoint, or custom destinations; file writes are safe for simultaneous
  writes from multiple processes
- **Sub-timings** — label named phases inside a single record with
  `bench.time(name)`; all phases share one metadata capture pass and results
  accumulate in `call.timings` in call order
- **Context managers** — `bench.record(name)` and `bench.record_on_exit(name)`
  for timing code blocks without decorators
- **Async support** — native `async def` decorator support and `bench.arecord()`
  async context manager
- **Quick stats** — `bench.summary()` prints min/mean/median/max/stdev with no
  extra dependencies

## Installation

```
pip install microbench
```

## Quick start — CLI

The fastest way to use microbench is from the command line. Wrap any command
and capture host metadata alongside timing, with no Python code required:

```bash
microbench --outfile results.jsonl -- ./run_simulation.sh --steps 1000
```

This records one JSONL record per invocation with timing, hostname, Python
version, SLURM variables, and more. Use `--monitor-interval` to sample CPU
and memory usage over time:

```bash
microbench --outfile results.jsonl --monitor-interval 30 -- ./train_model.py
```

Add `--field` to tag runs with custom metadata:

```bash
microbench --outfile results.jsonl --field experiment=run-42 -- ./run.sh
```

See the [CLI documentation](https://alubbock.github.io/microbench/cli/) for the
full option reference.

## Quick start — Python API

For Python-specific use cases, decorate functions directly:

```python
from microbench import MicroBench

bench = MicroBench(outfile='/home/user/results.jsonl', experiment='baseline')

@bench
def my_function(n):
    return sum(range(n))

my_function(1_000_000)

# list of dicts — no extra dependencies:
results = bench.get_results()

# pandas DataFrame:
results = bench.get_results(format='df')

# quick stats printout — no dependencies:
bench.summary()
```

Each call produces one record. With `get_results(flat=True)` the record looks
like:

```
   mb.run_id                             mb.version  call.name   call.durations  experiment
0  3f2a1b4c-8d9e-4f2a-b1c3-d4e5f6a7b8c9  2.0.0      my_function  [0.049823]     baseline
```

## CLI vs Python API

| Use case | Recommended | Why |
|---|---|---|
| Benchmarking shell scripts, compiled executables, or non-Python programs | CLI | Works with any language; no code changes needed |
| SLURM jobs or batch scripts | CLI | Drop-in wrapper; captures SLURM metadata automatically |
| One-off timing with host metadata | CLI | Zero setup |
| Python functions with sub-timings (`bench.time()`) | Python API | Sub-timings require the `@bench` decorator or `bench.record()` context manager |
| Custom capture logic (subclassing mixins) | Python API | Mixins are Python classes |
| Capturing loaded Python package versions | Python API | `capture_versions` inspects live Python module versions, not just installed |
| Async Python functions | Python API | Requires `@bench` async decorator or `bench.arecord()` |

## Extended example

```python
from microbench import MicroBench, MBFunctionCall, \
  MBHostInfo, MBSlurmInfo
import numpy, pandas, time

class MyBench(MicroBench, MBFunctionCall, MBHostInfo, MBSlurmInfo):
    outfile = '/home/user/my-benchmarks.jsonl'
    capture_versions = (numpy, pandas)
    env_vars = ('CUDA_VISIBLE_DEVICES',)

benchmark = MyBench(experiment='run-1', iterations=3,
                    duration_counter=time.monotonic)

@benchmark
def myfunction(arg1, arg2):
    ...

myfunction(x, y)
```

Mixins used:
- `MBFunctionCall` records the supplied arguments `x` and `y`.
- `MBHostInfo` captures `host.hostname` and `host.os`.
- `MBSlurmInfo` captures all `SLURM_` environment variables
  (used by the [SLURM](https://slurm.schedmd.com/overview.html) cluster system).

Class variables:
- `outfile` saves results to a file (one JSON object per line).
- `capture_versions` records the versions of specified packages.
- `env_vars` captures environment variables as `env.<NAME>` fields.

Constructor arguments:
- `iterations=3` runs the function three times, recording all three durations.
- `duration_counter` overrides the timer function, if you need precise timing.
- `experiment='run-1'` adds a custom `experiment` field to every record.

Note: `MBPythonInfo` is included in `MicroBench` by default, so it does not
need to be listed explicitly.

## Documentation

Full documentation, including a getting-started guide, mixin reference, and
API docs, is at **https://alubbock.github.io/microbench/**.

## Citing microbench

If you use microbench in your research, please cite:

> Lubbock, A.L.R. and Lopez, C.F. (2022). Microbench: automated metadata
> management for systems biology benchmarking and reproducibility in Python.
> *Bioinformatics*, 38(20), 4823–4825.
> https://doi.org/10.1093/bioinformatics/btac580

Although the paper was written in the context of systems biology, microbench
is a general-purpose benchmarking tool applicable to any Python workload.

## Feedback

Bug reports and feature requests are welcome in
[GitHub issues](https://github.com/alubbock/microbench/issues).
