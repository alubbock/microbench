# Microbench

![Microbench: Benchmarking and reproducibility metadata capture for Python](https://raw.githubusercontent.com/alubbock/microbench/master/microbench.png)

Running the same script on a laptop, cloud VM, or cluster can produce
different results. Maybe some nodes have different GPUs, or you're running
a different git commit without realising it.

Microbench records the context alongside your timings: Python version,
package versions, hostname, hardware, environment variables, git commit,
and more. When performance varies across machines or runs, the metadata
tells you why. When you need to reproduce a result, it shows exactly what
was running.

Unlike other benchmarking tools, Microbench focuses on **reproducibility
metadata** — capturing these details is cheap and routine, so you can do
it for every run, not just when something goes wrong.

## Two ways to use it

Microbench has two modes:

- **CLI** — wraps any command (Python or not) with a single line; no code
  changes required. Ideal for SLURM jobs and shell scripts.
- **Python API** — decorates functions or wraps code blocks for richer
  capture: sub-timings, return values, live package versions, async support.

Results are saved to a JSONL file, Redis, or an HTTP endpoint. File writes
use `O_APPEND` and are safe for concurrent writes from multiple processes.

See [CLI vs Python API](#cli-vs-python-api) below to help decide which to use.

## What metadata can be captured?

Metadata are captured through _mixins_ — small, composable modules that can
be enabled from the CLI or mixed into a Python class. A sensible default set
is active out of the box.

| Metadata | CLI flag | Python mixin |
|---|---|---|
| Run ID, version, timezone, duration(s), start/finish times, invocation method | _(default)_ | _(default)_ |
| Python version, prefix, and executable | _(default)_ | _(default: included in `MicroBench`)_ |
| Hostname, OS; CPU core count and total RAM (requires psutil) | _(default)_ | `MBHostInfo` |
| All `SLURM_*` environment variables | _(default)_ | `MBSlurmInfo` |
| Loaded Environment Modules / Lmod stack | _(default)_ | `MBLoadedModules` |
| Current working directory | _(default)_ | `MBWorkingDir` |
| Git repo, commit hash, branch, dirty flag | `--mixin git-info` | `MBGitInfo` |
| SHA-256 (or other) hash of specified files | `--mixin file-hash` | `MBFileHash` |
| Installed Python packages and versions | `--mixin installed-packages` | `MBInstalledPackages` |
| Installed Conda packages and versions | `--mixin conda-packages` | `MBCondaPackages` |
| NVIDIA GPU names, memory, and attributes | `--mixin nvidia-smi` | `MBNvidiaSmi` |
| Cgroup CPU/RAM limits (containers, Linux only) | `--mixin cgroup-limits` | `MBCgroupLimits` |
| Function call arguments | — | `MBFunctionCall` |
| Function return value | — | `MBReturnValue` |
| Peak memory over a function call via `tracemalloc` | — | `MBPeakMemory` |
| Python packages loaded into the caller's globals | — | `MBGlobalPackages` |
| Line-by-line performance profile | — | `MBLineProfiler` |

## Installation

Requires Python 3.10+. No mandatory dependencies outside the standard library.

```
pip install microbench
```

## Quick start — CLI

Wrap any command and capture host metadata alongside timing, with no code
changes required:

```bash
microbench --outfile results.jsonl -- ./run_simulation.sh --steps 1000
```

This records one JSONL record per invocation. By default it captures timing,
hostname, Python version, SLURM variables, loaded modules, and working
directory. Add `--monitor-interval` to sample CPU and RSS memory over time:

```bash
microbench --outfile results.jsonl --monitor-interval 30 -- python train_model.py
```

Tag runs with custom fields:

```bash
microbench --outfile results.jsonl --field experiment=run-42 -- ./run.sh
```

Run `microbench --help` or `microbench --show-mixins` to see all options.

### Example output

```bash
microbench -- echo "hello"
```

Output (written to stdout when `--outfile` is omitted):

```json
{
  "mb": {
    "run_id": "8a3d213a-d7c2-44cb-a42f-1b68e6e0180e",
    "version": "2.0.0",
    "timezone": "UTC",
    "duration_counter": "perf_counter"
  },
  "call": {
    "invocation": "CLI",
    "name": "echo",
    "working_dir": "/home/user",
    "command": ["echo", "hello"],
    "durations": [0.004],
    "start_time": "2026-03-17T14:36:08.140607+00:00",
    "finish_time": "2026-03-17T14:36:08.144707+00:00",
    "returncode": [0]
  },
  "host": {
    "hostname": "cluster-node-04",
    "os": "linux",
    "cpu_cores_logical": 32,
    "cpu_cores_physical": 16,
    "ram_total": 137438953472
  },
  "python": {
    "version": "3.13.1",
    "prefix": "/opt/conda/envs/myenv",
    "executable": "/opt/conda/envs/myenv/bin/python3.13"
  },
  "slurm": {},
  "loaded_modules": {}
}
```

The CLI supports additional options, including capturing stdout/stderr, setting timeouts,
and repeat iterations for benchmarking. See the
[CLI documentation](https://alubbock.github.io/microbench/cli/) for the full option reference.

## Quick start — Python API

For Python-specific use cases, decorate functions directly:

```python
from microbench import MicroBench

bench = MicroBench(outfile='/home/user/results.jsonl', experiment='baseline')

@bench
def my_function(n):
    return sum(range(n))

my_function(1_000_000)

results = bench.get_results()              # list of dicts — no extra dependencies
results = bench.get_results(format='df')  # pandas DataFrame
bench.summary()                           # quick stats printout
```

Each call produces one record. With `get_results(flat=True)` the record looks
like:

```
   mb.run_id                             mb.version  call.name   call.durations  experiment
0  3f2a1b4c-8d9e-4f2a-b1c3-d4e5f6a7b8c9  2.0.0      my_function  [0.049823]     baseline
```

## CLI vs Python API

| Use case | Recommended |
|---|---|
| Shell scripts, compiled executables, or non-Python programs | CLI |
| SLURM jobs or batch scripts | CLI |
| One-off timing with host metadata, no code changes | CLI |
| Python functions needing sub-timings (`bench.time()`), return-value capture, or line-by-line profiling | Python API |
| Custom capture logic (subclassing mixins) | Python API |
| Capturing live Python module versions (not just what's installed) | Python API |
| Async Python functions | Python API |

## Python API — extended example

```python
from microbench import MicroBench, MBFunctionCall, MBHostInfo, MBSlurmInfo
import numpy, pandas, time

class MyBench(MicroBench, MBFunctionCall, MBHostInfo, MBSlurmInfo):
    outfile = '/home/user/my-benchmarks.jsonl'
    capture_versions = (numpy, pandas)   # record live module versions
    env_vars = ('CUDA_VISIBLE_DEVICES',) # capture env vars as env.<NAME>

benchmark = MyBench(experiment='run-1', iterations=3,
                    duration_counter=time.monotonic)

@benchmark
def myfunction(arg1, arg2):
    ...

myfunction(x, y)
```

Mixins added here:
- `MBFunctionCall` records the arguments `arg1` and `arg2`.
- `MBHostInfo` captures `host.hostname`, `host.os`, CPU cores, and RAM.
- `MBSlurmInfo` captures all `SLURM_*` environment variables.

`MBPythonInfo` is included in `MicroBench` by default — no need to list it
explicitly.

See the [full documentation](https://alubbock.github.io/microbench/) for
context managers, async support, sub-timings, output sinks, and more.

## Documentation

Full documentation, including a getting-started guide, mixin reference, and
API reference, is at **https://alubbock.github.io/microbench/**.

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
