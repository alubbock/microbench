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
  jobs
- **Extensible via _mixins_** — capture Python version, hostname, CPU/RAM
  specs, conda/pip package versions, NVIDIA GPU info, line-level profiles,
  peak memory usage, and more by adding mixin classes
- **Cluster and HPC ready** — capture SLURM environment variables, psutil
  resource metrics, and per-process run IDs for correlating results across
  nodes
- **JSONL output** — one JSON object per call; load into pandas with
  `read_json(..., lines=True)`; flexibility to add any extra fields you
  need
- **Flexible output** — write to a local file, in-memory buffer, Redis, or
  custom destinations; file writes are safe for simultaneous writes from
  multiple processes
- **Sub-timings** — label named phases inside a single record with
  `bench.time(name)`; all phases share one metadata capture pass and results
  accumulate in `mb_timings` in call order

## Installation

```
pip install microbench
```

## Quick start

Microbench works by adding a Python decorator `@bench` to the function you want to
benchmark. Assuming you have `my_function`, you create the benchmark suite `bench`,
add the decorator to your function, and simply call it as normal:

```python
from microbench import MicroBench

bench = MicroBench(outfile='/home/user/results.jsonl', experiment='baseline')

@bench
def my_function(n):
    return sum(range(n))

my_function(1_000_000)
results = bench.get_results()
```

Each call produces one record. `results` is a pandas DataFrame:

```
   mb_run_id                             mb_version  function_name  run_durations  experiment
0  3f2a1b4c-8d9e-4f2a-b1c3-d4e5f6a7b8c9  2.0.0      my_function    [0.049823]     baseline
```

## Extended example

Here's an extended example to give you an idea of real-world usage.

```python
from microbench import MicroBench, MBFunctionCall, MBPythonVersion, \
  MBHostInfo, MBSlurmInfo
import numpy, pandas, time

class MyBench(MicroBench, MBFunctionCall, MBPythonVersion, MBHostInfo, MBSlurmInfo):
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
- `MBPythonVersion` captures the Python version.
- `MBHostInfo` captures `hostname` and `operating_system`.
- `MBSlurmInfo` captures all `SLURM_` environment variables
  (used by the [SLURM](https://slurm.schedmd.com/overview.html) cluster system).

Class variables:
- `outfile` saves results to a file (one JSON object per line).
- `capture_versions` records the versions of specified packages.
- `env_vars` captures environment variables as `env_<NAME>` fields.

Constructor arguments:
- `iterations=3` runs the function three times, recording all three durations.
- `duration_counter` overrides the timer function, if you need precise timing.
- `experiment='run-1'` adds a custom `experiment` field to every record.

## Command-line interface

Microbench can also wrap any external command and record metadata alongside
timing, without writing Python code:

```bash
python -m microbench --outfile results.jsonl -- ./run_simulation.sh --steps 1000
```

This is useful for SLURM jobs, shell scripts, and compiled executables. Host
info and SLURM variables are captured by default. Use `--mixin`, `--field`,
`--iterations`, and `--warmup` to customise the run.

See the [CLI documentation](https://alubbock.github.io/microbench/cli/) for
the full option reference.

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
