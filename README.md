# Microbench

![Microbench: Benchmarking and reproducibility metadata capture for Python](https://raw.githubusercontent.com/alubbock/microbench/master/microbench.png)

Microbench is a small Python package for benchmarking Python functions and
capturing reproducibility metadata — designed for clustered and distributed
environments where the same code runs across many machines.

## Key features

- **Zero-config timing** — decorate a function, get timestamps and run
  durations immediately, no setup required
- **Extensible via mixins** — capture Python version, hostname, CPU/RAM
  specs, conda/pip package versions, NVIDIA GPU info, line-level profiles,
  and more by adding mixin classes
- **Cluster and HPC ready** — capture SLURM environment variables, psutil
  resource metrics, and per-process run IDs for correlating results across
  nodes
- **JSONL output** — one JSON object per call; load into pandas with
  `read_json(..., lines=True)`; no schema lock-in, add any extra fields you
  need
- **Flexible output** — write to a local file, in-memory buffer, or Redis;
  file writes use `O_APPEND` for safe concurrent access on shared filesystems

## Installation

```
pip install microbench
```

## Quick start

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
0  3f2a1b4c-8d9e-4f2a-b1c3-d4e5f6a7b8c9  1.1.0      my_function    [0.049823]     baseline
```

## Documentation

Full documentation, including a getting-started guide, mixin reference, and
API docs, is at **https://alubbock.github.io/microbench/**.

## Feedback

Bug reports and feature requests are welcome in
[GitHub issues](https://github.com/alubbock/microbench/issues).
