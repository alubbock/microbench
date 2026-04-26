# Mixins

Mixins add metadata capture to a benchmark suite. The same set of mixins is
available from both the CLI and the Python API.

## CLI

Select mixins with `--mixin`:

```bash
microbench --mixin host-info slurm-info git-info -- ./run.sh
```

Mixin names use kebab-case without the `MB` prefix (`host-info` for
`MBHostInfo`, etc.). MB-prefixed names are also accepted. Run `--show-mixins`
to list all available mixins with descriptions:

```bash
microbench --show-mixins
```

By default, `python-info`, `host-info`, `slurm-info`, `loaded-modules`,
`working-dir`, and `resource-usage` are included automatically. Specifying
`--mixin` replaces the defaults entirely. Use `--no-mixin` to disable all mixins:

```bash
# Only peak-memory — no host info or SLURM
microbench --mixin peak-memory -- ./job.sh

# No mixins at all — timing and command fields only
microbench --no-mixin -- ./job.sh
```

`MBFunctionCall`, `MBReturnValue`, `MBGlobalPackages`, and `MBLineProfiler`
have no CLI equivalent — they are Python API only.

## Python API

Combine any number of mixins with `MicroBench` via multiple inheritance:

```python
from microbench import MicroBench, MBHostInfo

class MyBench(MicroBench, MBHostInfo):
    pass
```

`MicroBench` already includes `MBPythonInfo` by default, so a `python` dict
is present in every record without any extra mixin. Subclass
`MicroBenchBase` instead if you want a completely bare benchmark class with
no default captures.

Python resolves method calls across multiple base classes using the **Method
Resolution Order (MRO)** — a deterministic left-to-right search that ensures
each class in the hierarchy is visited exactly once. This means you can
combine any number of microbench mixins without conflicts, and their
`capture_*` methods will all be called.

## Reference

| Mixin | CLI name | Fields captured | Extra requirements |
|---|---|---|---|
| *(none)* | — | `mb.run_id`, `mb.version`, `mb.timezone`, `mb.duration_counter`, `call.invocation`, `call.name`, `call.start_time`, `call.finish_time`, `call.durations` | — |
| `MBFunctionCall` | Python only | `call.args`, `call.kwargs` | — |
| `MBReturnValue` | Python only | `call.return_value` | — |
| `MBPythonInfo` | `python-info` *(default)* | `python.version`, `python.prefix`, `python.executable` — **included in `MicroBench` by default** | — |
| `MBHostInfo` | `host-info` *(default)* | `host.hostname`, `host.os`; also `host.cpu_cores_logical`, `host.cpu_cores_physical`, `host.ram_total` (bytes) when psutil is installed (silently omitted otherwise) | psutil (optional) |
| `MBPeakMemory` | `peak-memory` | `call.peak_memory_bytes` | — |
| `MBSlurmInfo` | `slurm-info` *(default)* | `slurm` dict of all `SLURM_*` env vars (empty dict if not in a SLURM job) | — |
| `MBLoadedModules` | `loaded-modules` *(default)* | `loaded_modules` dict mapping module name to version (empty dict if no Lmod/Environment Modules are loaded) | — |
| `MBWorkingDir` | `working-dir` *(default)* | `call.working_dir` — absolute path of the working directory at benchmark time | — |
| `MBCgroupLimits` | `cgroup-limits` | `cgroups` dict with `cpu_cores_limit`, `memory_bytes_limit`, `version` (empty dict if not on Linux or cgroup fs unavailable) | Linux only |
| `MBResourceUsage` | `resource-usage` *(default)* | `resource_usage` list of dicts with CPU times, peak RSS, page faults, I/O ops, and context switches (`[]` when the stdlib `resource` module is unavailable) | POSIX only (stdlib) |
| `MBGitInfo` | `git-info` | `git` dict with `repo`, `commit`, `branch`, `dirty` | `git` ≥ 2.11 on PATH |
| `MBGlobalPackages` | Python only | `python.loaded_packages` for every package in the caller's global scope | — |
| `MBInstalledPackages` | `installed-packages` | `python.installed_packages` (and optionally `python.installed_package_paths`) for every installed package | — |
| `MBCondaPackages` | `conda-packages` | `conda` dict with `name`, `path`, and `packages` (version dict) | `conda` on PATH or `CONDA_EXE` set |
| `MBNvidiaSmi` | `nvidia-smi` | `nvidia` — list of per-GPU dicts (see below) | `nvidia-smi` on PATH |
| `MBLineProfiler` | Python only | `call.line_profiler` (base64-encoded profile, see below) | line_profiler |
| `MBFileHash` | `file-hash` | `file_hashes` — SHA-256 checksum of each specified file | — |

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
# record contains: {"call": {"args": [1], "kwargs": {"b": 2}}, ...}
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
# record contains: {"call": {"return_value": 4950}, ...}
```

The return value must be JSON-serialisable. If it is not, a
`JSONEncodeWarning` is issued and a placeholder is stored. See
[Custom JSON encoding](extending.md#custom-json-encoding) to handle
custom types.

## Host resources

### `MBHostInfo`

Captures hostname, operating system, and (when [psutil](https://pypi.org/project/psutil/)
is installed) CPU core counts and total RAM.

```python
from microbench import MicroBench, MBHostInfo

class Bench(MicroBench, MBHostInfo):
    pass
```

Always-present fields: `host.hostname`, `host.os`.

Fields added when psutil is installed (silently omitted otherwise):
`host.cpu_cores_logical`, `host.cpu_cores_physical`, `host.ram_total` (bytes).

!!! note
    `MBHostCpuCores` and `MBHostRamTotal` have been removed. Use `MBHostInfo`,
    which captures all host fields including the psutil-dependent ones.

## Job resource utilisation

### `MBPeakMemory`

Captures the peak Python memory allocation during the benchmarked function
(across all iterations when `iterations > 1`) as `call.peak_memory_bytes` (bytes).
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
# record contains: {"call": {"peak_memory_bytes": 8056968}, ...}
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

## HPC and containers

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

### `MBLoadedModules`

Captures the currently loaded [Lmod](https://lmod.readthedocs.io/) or
[Environment Modules](https://modules.readthedocs.io/) software stack into a
`loaded_modules` dict, mapping each module name to its version string. If no
modules are loaded, or the benchmark is not running in a module-enabled
environment, `loaded_modules` is an empty dict.

```python
from microbench import MicroBench, MBLoadedModules

class Bench(MicroBench, MBLoadedModules):
    pass

bench = Bench()
```

Each record will contain:

```json
{
  "loaded_modules": {
    "gcc": "12.2.0",
    "openmpi": "4.1.5",
    "python": "3.10.4"
  }
}
```

Module entries without a version (e.g. `null`) are stored with an empty
string as the version. Hierarchical module names such as
`GCC/12.2.0-GCCcore-12.2.0` are split on the first `/`, so the name is
`GCC` and the version is `12.2.0-GCCcore-12.2.0`.

This mixin reads the `LOADEDMODULES` environment variable, which is the
standard set by both Lmod and Environment Modules. No subprocess is
required and there are no extra dependencies.

### `MBWorkingDir`

Captures the absolute path of the working directory at benchmark time into `call.working_dir`:

```python
from microbench import MicroBench, MBWorkingDir

class Bench(MicroBench, MBWorkingDir):
    pass

bench = Bench()
```

Each record will contain:

```json
{
  "call": {
    "working_dir": "/home/user/experiments/run-42"
  }
}
```

Useful for reproducibility — records exactly which directory was current when
the benchmark ran, so results from different nodes or directories can be
distinguished. Included in the CLI defaults.

### `MBCgroupLimits`

Captures the CPU quota and memory limit enforced by the Linux control groups
(cgroups). Works for SLURM jobs and Kubernetes pods, on both cgroup v1 and
cgroup v2 systems, with no external dependencies. Unlike `MBHostInfo` (which reports the physical node's total resources),
`MBCgroupLimits` reports what the scheduler actually allocated to this job or
container — the number that determines your benchmark's resource budget.

```python
from microbench import MicroBench, MBSlurmInfo, MBCgroupLimits

class Bench(MicroBench, MBSlurmInfo, MBCgroupLimits):
    pass

bench = Bench()
```

Each record will contain:

```json
{
  "cgroups": {
    "cpu_cores_limit": 4.0,
    "memory_bytes_limit": 17179869184,
    "version": 2
  }
}
```

**`cpu_cores_limit`** is derived from the cgroup CPU quota and period
(`quota_us / period_us`), so it represents effective CPU parallelism rather than
a physical core count. A SLURM job launched with `--cpus-per-task=4` will
typically report `cpu_cores_limit: 4.0`.

**`memory_bytes_limit`** is the hard memory limit in bytes. A job allocated `--mem=16G`
will typically report `memory_bytes_limit: 17179869184`.

Both fields are `null` when no limit is set (the scheduler granted unlimited
access to that resource). `cgroups` is an empty dict on non-Linux
platforms or when the cgroup filesystem is unavailable.

!!! tip
    Pair with `MBSlurmInfo` for full HPC context — `MBSlurmInfo` captures
    scheduler metadata (job ID, node list, etc.) while `MBCgroupLimits` captures
    the kernel-enforced resource limits.

### `MBResourceUsage`

Captures POSIX [`getrusage(2)`](https://man7.org/linux/man-pages/man2/getrusage.2.html)
data — CPU time, page faults, block I/O operations, and context switches —
using only the Python standard library (`resource` module). No extra
dependencies are required.

**Modes**

- **CLI mode**: on POSIX, uses `os.wait4()` to get the exact rusage of each
  child process as reported by the kernel — one dict per timed iteration,
  aligned index-for-index with `call.durations`.
  `maxrss` is the child's own peak RSS.
- **Python API mode**: uses `RUSAGE_SELF` — one dict per timed iteration,
  each a before/after delta around that single call (aligned index-for-index
  with `call.durations`). Warmup calls are excluded.
  `maxrss` is **omitted** — `RUSAGE_SELF.maxrss` is a lifetime process
  high-water mark that reflects the peak since the interpreter started,
  not just since the decorated function was called, making it unreliable
  for function-level measurement.

On platforms where the stdlib `resource` module is unavailable, the
`resource_usage` key is omitted from the record entirely.

```python
from microbench import MicroBench, MBResourceUsage

class Bench(MicroBench, MBResourceUsage):
    pass

bench = Bench()

@bench
def work():
    return list(range(1_000_000))

work()
```

Python API record (one entry per timed iteration, no `maxrss`):

```json
{
  "resource_usage": [
    {
      "utime": 0.052,
      "stime": 0.003,
      "minflt": 1024,
      "majflt": 0,
      "inblock": 0,
      "oublock": 0,
      "nvcsw": 2,
      "nivcsw": 1
    }
  ]
}
```

CLI record with `--iterations 2` (one entry per iteration, includes `maxrss`):

```json
{
  "resource_usage": [
    {
      "utime": 0.068,
      "stime": 0.029,
      "maxrss": 11386880,
      "minflt": 621,
      "majflt": 0,
      "inblock": 0,
      "oublock": 0,
      "nvcsw": 1,
      "nivcsw": 2
    },
    {
      "utime": 0.071,
      "stime": 0.031,
      "maxrss": 11386880,
      "minflt": 618,
      "majflt": 0,
      "inblock": 0,
      "oublock": 0,
      "nvcsw": 1,
      "nivcsw": 3
    }
  ]
}
```

| Field | Modes | Description |
|---|---|---|
| `utime` | Both | User CPU time in seconds (float) |
| `stime` | Both | System CPU time in seconds (float) |
| `maxrss` | CLI only | Peak RSS in bytes (int) — see platform notes |
| `minflt` | Both | Minor page faults — pages reclaimed without I/O (int) |
| `majflt` | Both | Major page faults — pages requiring disk I/O (int) |
| `inblock` | Both | Block input operations (int) — see platform notes |
| `oublock` | Both | Block output operations (int) — see platform notes |
| `nvcsw` | Both | Voluntary context switches (int) |
| `nivcsw` | Both | Involuntary context switches (int) |

All fields are before/after **deltas** so they reflect only the benchmarked
work. `utime`, `stime`, `minflt`, `nvcsw`, and `nivcsw` are the most
reliable across platforms.

#### Platform notes and known quirks

**`maxrss` — CLI mode with `os.wait4()` (all POSIX)**

`os.wait4()` returns the exact rusage of each individual child process as
reported by the kernel. `maxrss` is the child's own peak RSS, accurate
regardless of iteration count or warmup. Values are normalised to bytes
(Linux reports kilobytes; macOS already reports bytes).

**`maxrss` — Python API mode (`RUSAGE_SELF`)**

`RUSAGE_SELF.maxrss` is a lifetime high-water mark for the Python interpreter
process. It is intentionally omitted. Use
[`MBPeakMemory`](#mbpeakmemory) if you need per-call peak memory tracking.

**`inblock` / `oublock` — macOS**

These counters are **almost always zero on macOS**, even for substantial file
I/O.  The macOS unified buffer cache charges block I/O to the *first* process
that touches each page; subsequent reads and writes to cached pages are not
counted against the process that performed them. In practice, nearly all file
I/O is served from the cache and the counters never increment.

This is a macOS kernel accounting limitation. It is documented in the
[`getrusage(2)` man page](https://developer.apple.com/library/archive/documentation/System/Conceptual/ManPages_iPhoneOS/man2/getrusage.2.html):
*"The numbers ru_inblock and ru_oublock account only for real I/O; data
supplied by the caching mechanism is charged only to the first process to
read or write the data."*

**`inblock` / `oublock` — Linux**

On Linux these counters increment only for I/O that truly bypasses the page
cache — cold-cache reads (first access to a file since it was last evicted)
or writes with `O_DIRECT`. Warm-cache reads also show zero. Drop the page
cache (`echo 3 > /proc/sys/vm/drop_caches` as root) before benchmarking if
you need to measure true cold-cache I/O.

**`majflt` — macOS**

Major page faults are rare on macOS because the unified buffer cache handles
most page-in activity. Zero is normal.

**`utime`, `stime`, `minflt`, `nvcsw`, `nivcsw`**

These are the most reliable fields across both Linux and macOS and are
non-zero for any non-trivial workload.

!!! note "Non-POSIX platforms"
    When the Python `resource` module is unavailable, the `resource_usage`
    key is omitted from the record entirely.

**CLI:** `resource-usage` is a default mixin — no flags needed:

```bash
# Included automatically
microbench --outfile results.jsonl -- ./run_simulation.sh

# Explicit, if defaults have been overridden
microbench --mixin resource-usage -- ./run_simulation.sh
```

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
  "git": {
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

**CLI:** use `--git-repo DIR` to specify the repository directory (defaults
to the current working directory):

```bash
microbench --mixin git-info --git-repo /path/to/repo -- ./run.sh
```

### `MBFileHash`

Records a cryptographic checksum of one or more files alongside benchmark
results. This ties a result to the exact version of the script that produced
it — useful when benchmarks evolve over time and you need to know which code
generated which numbers. Hashes are computed as a pre-hook, i.e. before the
enclosed code is run.

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
hex digest. The hashing algorithm is stored under `mb.file_hash_algorithm`:

```json
{
  "mb": {
    "file_hash_algorithm": "sha256"
  },
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

**CLI:** use `--hash-file FILE [FILE ...]` and `--hash-algorithm ALGORITHM`.
The CLI default hashes the benchmarked command executable *plus* any
arguments that resolve to existing files on disk:

```bash
# Automatically hashes run.sh, input.csv, and params.yaml
microbench --mixin file-hash -- ./run.sh input.csv --config params.yaml

# Hash a specific set of files (overrides the default entirely)
microbench --mixin file-hash --hash-file run_experiment.py config.yaml -- ./run.sh

# Change the hash algorithm
microbench --mixin file-hash --hash-algorithm md5 -- ./run.sh
```

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

The `python.loaded_packages` field will contain `{"numpy": "1.26.0", "pandas": "2.1.0", ...}`.

### `MBInstalledPackages`

Captures every package available for import (from `importlib.metadata`).
Results are stored in `python.installed_packages`. Useful for full
reproducibility audits. Can be slow on environments with many packages.

Set `capture_paths = True` to also record installation paths in
`python.installed_package_paths`:

```python
class Bench(MicroBench, MBInstalledPackages):
    capture_paths = True
```

### `MBCondaPackages`

Captures the active conda environment's identity and package list using the
`conda` CLI. The active environment is determined by the `CONDA_PREFIX`
environment variable, falling back to `sys.prefix` when it is unset.
If `conda` is not on `PATH`, the `CONDA_EXE` environment variable is tried.

Records two fields:

A single `conda` dict with three keys:

- `name` (`CONDA_DEFAULT_ENV`) — may be `None` if unset.
- `path` (`CONDA_PREFIX`) — may be `None` if unset.
- `packages` — dict mapping package name to version string.

```python
class Bench(MicroBench, MBCondaPackages):
    include_builds = True    # include build string (default: True)
    include_channels = False  # include channel name (default: False)
```

### `capture_versions`

To capture specific package versions without a mixin, list them on the
class. Results are stored in `python.loaded_packages`:

```python
import numpy, pandas

class Bench(MicroBench):
    capture_versions = (numpy, pandas)
```

## NVIDIA GPU — `MBNvidiaSmi`

Captures attributes for each installed GPU via `nvidia-smi`. Results are stored
in `nvidia` as a list of per-GPU dicts, each containing a `uuid` key plus one
key per queried attribute:

```json
{
  "nvidia": [
    {"uuid": "GPU-abc123", "gpu_name": "NVIDIA A100", "memory.total": "40960 MiB"}
  ]
}
```

### Choosing attributes

By default, `gpu_name` and `memory.total` are captured. To record additional
attributes — power draw, temperature, utilisation, etc. — set `nvidia_attributes`:

```python
from microbench import MicroBench, MBNvidiaSmi

class GpuBench(MicroBench, MBNvidiaSmi):
    nvidia_attributes = ('gpu_name', 'memory.total', 'power.draw', 'temperature.gpu')
```

Run `nvidia-smi --help-query-gpu` for the full list of available attribute names.

**CLI:** use `--nvidia-attributes ATTR [ATTR ...]`:

```bash
microbench --mixin nvidia-smi --nvidia-attributes gpu_name power.draw temperature.gpu -- ./run.sh
```

### Selecting specific GPUs

By default all installed GPUs are captured. To restrict to a subset, set
`nvidia_gpus` to a list of GPU identifiers. Three formats are accepted:

- **Zero-based index** — `0`, `1`, etc. Simple but can change after a reboot or
  driver reset.
- **UUID** — `GPU-abc123...` as reported by `nvidia-smi -L`. Stable across
  reboots and recommended for reproducible results.
- **PCI bus ID** — `00000000:01:00.0` format. Stable and unique when multiple
  GPUs share the same model name.

```python
class GpuBench(MicroBench, MBNvidiaSmi):
    nvidia_gpus = ('GPU-abc123def456',)   # single GPU by UUID
```

```python
class GpuBench(MicroBench, MBNvidiaSmi):
    nvidia_gpus = (0, 1)   # first two GPUs by index
```

Omit `nvidia_gpus` entirely to capture all GPUs.

**CLI:** use `--nvidia-gpus GPU [GPU ...]`:

```bash
microbench --mixin nvidia-smi --nvidia-gpus 0 1 -- ./run.sh
microbench --mixin nvidia-smi --nvidia-gpus GPU-abc123def456 -- ./run.sh
```

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
MBLineProfiler.print_line_profile(results[0]['call']['line_profiler'])
```

The profile is stored as a base64-encoded pickle in the `call.line_profiler` field.
Use `MBLineProfiler.decode_line_profile()` to deserialise it, or
`MBLineProfiler.print_line_profile()` to print it directly.

!!! warning "Security"
    `decode_line_profile()` uses `pickle.loads`. Only decode profiles from
    trusted sources (your own benchmark output). Never decode data received
    over a network or from an untrusted file.
