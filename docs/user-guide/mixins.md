# Mixins

Mixins are classes that add metadata capture to a benchmark suite via
multiple inheritance. Combine any number of mixins with `MicroBench`:

```python
from microbench import MicroBench, MBPythonVersion, MBHostInfo, MBHostCpuCores

class MyBench(MicroBench, MBPythonVersion, MBHostInfo, MBHostCpuCores):
    pass
```

Python resolves method calls across multiple base classes using the **Method
Resolution Order (MRO)** — a deterministic left-to-right search that ensures
each class in the hierarchy is visited exactly once. This means you can
combine any number of microbench mixins without conflicts, and their
`capture_*` methods will all be called.

## Reference

| Mixin | Fields captured | Extra requirements |
|---|---|---|
| *(none)* | `mb_run_id`, `mb_version`, `start_time`, `finish_time`, `run_durations`, `function_name`, `timestamp_tz`, `duration_counter` | — |
| `MBFunctionCall` | `args`, `kwargs` | — |
| `MBReturnValue` | `return_value` | — |
| `MBPythonVersion` | `python_version`, `python_executable` | — |
| `MBHostInfo` | `hostname`, `operating_system` | — |
| `MBHostCpuCores` | `cpu_cores_logical`, `cpu_cores_physical` | psutil |
| `MBHostRamTotal` | `ram_total` (bytes) | psutil |
| `MBPeakMemory` | `peak_memory_bytes` | — |
| `MBSlurmInfo` | `slurm` dict of all `SLURM_*` env vars (empty dict if not in a SLURM job) | — |
| `MBGitInfo` | `git_info` dict with `repo`, `commit`, `branch`, `dirty` | `git` ≥ 2.11 on PATH |
| `MBGlobalPackages` | `package_versions` for every package in the caller's global scope | — |
| `MBInstalledPackages` | `package_versions` for every installed package | — |
| `MBCondaPackages` | `conda_versions` for every package in the active conda environment | `conda` on PATH |
| `MBNvidiaSmi` | `nvidia_<attr>` per GPU (see below) | `nvidia-smi` on PATH |
| `MBLineProfiler` | `line_profiler` (base64-encoded profile, see below) | line_profiler |
| `MBFileHash` | `file_hashes` — SHA-256 checksum of each specified file | — |

## Function calls and return values

### `MBFunctionCall`

Captures the positional and keyword arguments passed to the decorated
function as `args` (list) and `kwargs` (dict):

```python
from microbench import MicroBench, MBFunctionCall

class Bench(MicroBench, MBFunctionCall):
    pass

bench = Bench()

@bench
def add(a, b):
    return a + b

add(1, b=2)
# record contains: {"args": [1], "kwargs": {"b": 2}, ...}
```

### `MBReturnValue`

Captures the return value of the decorated function as `return_value`:

```python
from microbench import MicroBench, MBReturnValue

class Bench(MicroBench, MBReturnValue):
    pass

bench = Bench()

@bench
def compute(n):
    return sum(range(n))

compute(100)
# record contains: {"return_value": 4950, ...}
```

The return value must be JSON-serialisable. If it is not, a
`JSONEncodeWarning` is issued and a placeholder is stored. See
[Custom JSON encoding](extending.md#custom-json-encoding) to handle
custom types.

## Host resources

### `MBHostCpuCores` and `MBHostRamTotal`

Capture static host hardware information. Requires
[psutil](https://pypi.org/project/psutil/).

```python
from microbench import MicroBench, MBHostCpuCores, MBHostRamTotal

class Bench(MicroBench, MBHostCpuCores, MBHostRamTotal):
    pass
```

Fields: `cpu_cores_logical`, `cpu_cores_physical`, `ram_total` (bytes).

## Job resource utilisation

### `MBPeakMemory`

Captures the peak Python memory allocation during the benchmarked function
(across all iterations when `iterations > 1`) as `peak_memory_bytes` (bytes).
Uses [`tracemalloc`](https://docs.python.org/3/library/tracemalloc.html) from
the standard library — no extra dependencies required.

```python
from microbench import MicroBench, MBPeakMemory

class Bench(MicroBench, MBPeakMemory):
    pass

bench = Bench()

@bench
def process(data):
    return sorted(data)

process(list(range(1_000_000, 0, -1)))
# record contains: {"peak_memory_bytes": 8056968, ...}
```

!!! note
    `tracemalloc` tracks memory that goes through Python's allocator, which
    covers Python objects and most C-extension allocations. Memory allocated
    directly via `malloc` in C extensions (e.g. some large NumPy operations)
    is not tracked.

!!! tip "Continuous resource monitoring"
    `MBPeakMemory` gives a single high-water mark per call. For time-series
    sampling of memory, CPU, and other metrics *while the function runs*,
    see [Periodic monitoring](monitoring.md).

## HPC / SLURM

### `MBSlurmInfo`

Captures all `SLURM_*` environment variables into a `slurm` dict. Keys are
lowercased with the `SLURM_` prefix stripped, so `SLURM_JOB_ID` becomes
`slurm['job_id']`. If the benchmark runs outside a SLURM job, `slurm` is
an empty dict.

```python
from microbench import MicroBench, MBSlurmInfo

class Bench(MicroBench, MBSlurmInfo):
    pass

bench = Bench()
```

Each record will contain:

```json
{
  "slurm": {
    "job_id": "12345",
    "array_task_id": "3",
    "nodelist": "gpu-node-[01-04]",
    "cpus_per_task": "4"
  }
}
```

Access individual values in pandas with:

```python
results['slurm'].apply(lambda s: s.get('job_id'))
```

!!! tip
    `MBSlurmInfo` supersedes the manual `env_vars = ('SLURM_JOB_ID', ...)`
    pattern — it captures every `SLURM_*` variable automatically with no
    configuration.

## Code provenance

### `MBGitInfo`

Captures the current git repo, commit hash, branch name, and dirty flag
(whether there are uncommitted changes in the working tree). Requires
`git` ≥ 2.11 on `PATH`.

```python
from microbench import MicroBench, MBGitInfo

class Bench(MicroBench, MBGitInfo):
    pass
```

Each record will contain:

```json
{
  "git_info": {
    "repo": "/home/user/project",
    "commit": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
    "branch": "main",
    "dirty": false
  }
}
```

`dirty` is `True` if there are any staged or unstaged changes to tracked
files. `branch` is an empty string in detached HEAD state.

By default the repository is located from the running script's directory
(`sys.argv[0]`), which works correctly even when a script is launched by
absolute path from a different working directory (e.g. cluster job
submission). Falls back to the shell's working directory in interactive
Python sessions. Set `git_repo` to target a specific directory explicitly:

```python
class Bench(MicroBench, MBGitInfo):
    git_repo = '/path/to/repo'
```

Use `capture_optional = True` to silently skip git capture on machines
without git or when running outside a repository.

## Package versions

### `MBGlobalPackages`

Captures the version of every module imported in the caller's global
namespace:

```python
from microbench import MicroBench, MBGlobalPackages
import numpy, pandas

class Bench(MicroBench, MBGlobalPackages):
    pass
```

The `package_versions` field will contain `{"numpy": "1.26.0", "pandas": "2.1.0", ...}`.

### `MBInstalledPackages`

Captures every package available for import (from `importlib.metadata`).
Useful for full reproducibility audits. Can be slow on environments with
many packages.

Set `capture_paths = True` to also record installation paths:

```python
class Bench(MicroBench, MBInstalledPackages):
    capture_paths = True
```

### `MBCondaPackages`

Captures all packages in the active conda environment using the `conda` CLI.

```python
class Bench(MicroBench, MBCondaPackages):
    include_builds = True    # include build string (default: True)
    include_channels = False  # include channel name (default: False)
```

### `capture_versions`

To capture specific package versions without a mixin, list them on the
class:

```python
import numpy, pandas

class Bench(MicroBench):
    capture_versions = (numpy, pandas)
```

## Code provenance

### `MBFileHash`

Records a cryptographic checksum of one or more files alongside benchmark
results. This ties a result to the exact version of the script that produced
it — useful when benchmarks evolve over time and you need to know which code
generated which numbers.

```python
from microbench import MicroBench, MBFileHash

class Bench(MicroBench, MBFileHash):
    pass

bench = Bench()
```

By default, `MBFileHash` hashes `sys.argv[0]` — the script that was run. To
hash specific files instead, set `hash_files`:

```python
class Bench(MicroBench, MBFileHash):
    hash_files = ['run_experiment.py', 'config.yaml']
```

Relative paths in `hash_files` are resolved against the **working directory
at the time the benchmarked function is called**, which may differ from the
script's location (especially on clusters where a job scheduler launches
scripts from a scratch directory). Use absolute paths to be safe:

```python
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

class Bench(MicroBench, MBFileHash):
    hash_files = [
        os.path.join(SCRIPT_DIR, 'run_experiment.py'),
        os.path.join(SCRIPT_DIR, 'config.yaml'),
    ]
```

Each record will contain a `file_hashes` dict mapping each path to its
hex digest:

```json
{
  "file_hashes": {
    "run_experiment.py": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "config.yaml": "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
  }
}
```

The default algorithm is SHA-256. Use `hash_algorithm` to select a different
algorithm from Python's [`hashlib`](https://docs.python.org/3/library/hashlib.html):

```python
class Bench(MicroBench, MBFileHash):
    hash_files = ['large_model_weights.bin']
    hash_algorithm = 'md5'   # faster for large files
```

Any algorithm name accepted by `hashlib.new()` works: `'sha256'` (default),
`'md5'`, `'sha1'`, `'blake2b'`, etc.

!!! tip
    Pair `MBFileHash` with `capture_optional = True` if the script path
    may not always be available (e.g. interactive Python sessions):

    ```python
    class Bench(MicroBench, MBFileHash):
        hash_files = ['sometimes_missing.dat']
        capture_optional = True
    ```

## NVIDIA GPU — `MBNvidiaSmi`

Captures attributes for each installed GPU via `nvidia-smi`.

By default captures `gpu_name` and `memory.total`. Customise with
`nvidia_attributes`:

```python
from microbench import MicroBench, MBNvidiaSmi

class GpuBench(MicroBench, MBNvidiaSmi):
    nvidia_attributes = ('gpu_name', 'memory.total', 'pcie.link.width.max')
    nvidia_gpus = ('GPU-abc123',)  # UUIDs preferred; omit to capture all
```

Results are stored as `nvidia_<attr>` dicts keyed by GPU UUID, e.g.
`nvidia_gpu_name: {"GPU-abc123": "NVIDIA A100"}`.

Run `nvidia-smi --help-query-gpu` for the full list of available attributes.
Run `nvidia-smi -L` to list GPU UUIDs.

## Line profiler — `MBLineProfiler`

Captures a line-by-line timing profile of the decorated function using
[line_profiler](https://github.com/rkern/line_profiler).

```python
from microbench import MicroBench, MBLineProfiler

class Bench(MicroBench, MBLineProfiler):
    pass

bench = Bench()

@bench
def my_function():
    acc = 0
    for i in range(1000000):
        acc += i
    return acc

my_function()

results = bench.get_results()
MBLineProfiler.print_line_profile(results['line_profiler'][0])
```

The profile is stored as a base64-encoded pickle in the `line_profiler` field.
Use `MBLineProfiler.decode_line_profile()` to deserialise it, or
`MBLineProfiler.print_line_profile()` to print it directly.

!!! warning "Security"
    `decode_line_profile()` uses `pickle.loads`. Only decode profiles from
    trusted sources (your own benchmark output). Never decode data received
    over a network or from an untrusted file.
