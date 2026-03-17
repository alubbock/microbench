# Changelog

All notable changes to microbench are documented here.

## [2.0.0] - unreleased

### Breaking changes (vs v1.1.0)

- **Removed deprecated mixins**: `MBPythonVersion`, `MBHostCpuCores`, and
  `MBHostRamTotal` have been removed.
  - Replace `MBPythonVersion` with `MBPythonInfo` (captures `python.version`,
    `python.prefix`, `python.executable`).
  - Replace `MBHostCpuCores` and/or `MBHostRamTotal` with `MBHostInfo`, which
    now captures `host.cpu_cores_logical`, `host.cpu_cores_physical`, and
    `host.ram_total` automatically when psutil is installed.

- **Namespace restructuring of record fields**: All benchmark record fields are
  now grouped into top-level namespace dicts, making records self-documenting
  and easier to query. The complete rename table is below.

  **Core fields** move into `mb` (static config) and `call` (per-call data):

  | Old key | New key |
  |---|---|
  | `mb_run_id` | `mb.run_id` |
  | `mb_version` | `mb.version` |
  | `timestamp_tz` | `mb.timezone` |
  | `duration_counter` | `mb.duration_counter` |
  | `start_time` | `call.start_time` |
  | `finish_time` | `call.finish_time` |
  | `run_durations` | `call.durations` |
  | `function_name` | `call.name` |
  | `mb_timings` | `call.timings` |
  | `mb_capture_errors` | `call.capture_errors` |
  | `monitor` | `call.monitor` |
  | `env_*` (flat keys) | `env.*` (dict) |
  | `package_versions` (from `capture_versions`) | `python.loaded_packages` |

  **Mixin fields** move to typed namespaces:

  | Old key | New key |
  |---|---|
  | `hostname` | `host.hostname` |
  | `operating_system` | `host.os` |
  | `cpu_cores_logical` | `host.cpu_cores_logical` |
  | `cpu_cores_physical` | `host.cpu_cores_physical` |
  | `ram_total` | `host.ram_total` |
  | `working_dir` | `call.working_dir` |
  | `peak_memory_bytes` | `call.peak_memory_bytes` |
  | `args` | `call.args` |
  | `kwargs` | `call.kwargs` |
  | `return_value` | `call.return_value` |
  | `line_profiler` | `call.line_profiler` |
  | `package_versions` (MBGlobalPackages) | `python.loaded_packages` |
  | `package_versions` (MBInstalledPackages) | `python.installed_packages` |
  | `package_paths` | `python.installed_package_paths` |
  | `git_info` | `git` |
  | `cgroup_limits` | `cgroups` (inner keys also renamed: `cpu_cores` → `cpu_cores_limit`, `memory_bytes` → `memory_bytes_limit`, `cgroup_version` → `version`) |
  | `nvidia_<attr>` (multiple flat dicts) | `nvidia` (list of per-GPU dicts with `uuid` key) |

  **CLI fields** also move into `call`:

  | Old key | New key |
  |---|---|
  | `function_name` (basename) | `call.name` |
  | `command` | `call.command` |
  | `returncode` | `call.returncode` |
  | `stdout` | `call.stdout` |
  | `stderr` | `call.stderr` |
  | `subprocess_monitor` | `call.monitor` |

  A new `call.invocation` field is always present: `'Python'` for the Python
  API and `'CLI'` for the command-line interface.

  Unchanged namespaces: `slurm`, `loaded_modules`, `conda`, `file_hashes`,
  `exception` (top-level), `exit_signal` (top-level).

  **Migration:** Use `get_results(flat=True)` to access fields via dot-notation
  keys (`call.name`, `mb.run_id`, `host.hostname`, etc.) in pandas or scripts
  without rewriting nested dict access. Alternatively, update field access to
  the new nested structure: `result['call']['name']`, `result['mb']['run_id']`,
  `result['host']['hostname']`, etc.

- **`get_results()` now returns a list of dicts by default**: The default
  `format='dict'` returns a list of plain Python dicts and requires no
  dependencies. Pass `format='df'` to get a pandas DataFrame (previous
  behaviour). Update existing callers: `bench.get_results()` →
  `bench.get_results(format='df')`.

- **`telemetry` renamed to `monitor`** (#51): The background sampling thread
  has been renamed throughout the API to better reflect its intent (continuous
  monitoring, not data transmission).
  - `TelemetryThread` → `MonitorThread`
  - Class variable `telemetry_interval` → `monitor_interval`
  - Class variable `telemetry_timeout` → `monitor_timeout`
  - Result field `bm_data['telemetry']` → `bm_data['monitor']`
  - Internal attribute `self._telemetry_thread` → `self._monitor_thread`

- **`MicroBenchRedis` removed** (#52): Use
  `MicroBench(outputs=[RedisOutput(...)])` instead.

  Before:
  ```python
  from microbench import MicroBenchRedis

  class RedisBench(MicroBenchRedis):
      redis_connection = {'host': 'localhost', 'port': 6379}
      redis_key = 'microbench:mykey'

  bench = RedisBench()
  ```

  After:
  ```python
  from microbench import MicroBench, RedisOutput

  bench = MicroBench(outputs=[RedisOutput('microbench:mykey',
                                           host='localhost', port=6379)])
  ```

### New features

- **`get_results(format=..., flat=...)`**: `get_results` now accepts two
  keyword arguments.
  - `format='dict'` (default) — returns a list of dicts; no pandas required.
  - `format='df'` — returns a pandas DataFrame (previous default behaviour).
  - `flat=True` — flattens nested dict fields (e.g. `slurm`, `cgroups`,
    `git`) into dot-notation keys (`slurm.job_id`, `call.name`). Works for both
    formats without requiring pandas.

- **`summary(results)` / `bench.summary()`**: prints min / mean / median /
  max / stdev of `call.durations` across all results. No dependencies required
  beyond the Python standard library. `bench.summary()` is a one-liner
  convenience that calls `bench.get_results()` internally. The module-level
  `summary(results)` accepts any list of dicts and can be composed with other
  results-processing steps.

  ```python
  from microbench import MicroBench, summary

  bench = MicroBench()

  @bench
  def my_function():
      ...

  for _ in range(10):
      my_function()

  bench.summary()
  # n=10  min=0.000031  mean=0.000038  median=0.000036  max=0.000059  stdev=0.000008

  # or with explicit results list:
  summary(bench.get_results())
  ```

- **`MBCgroupLimits`**: captures the CPU quota and memory limit enforced by
  the Linux cgroup filesystem. Works for SLURM jobs and Kubernetes pods (cgroup
  v1 and v2). Fields in `cgroups`: `cpu_cores_limit` (float — quota ÷ period,
  or `null` if unlimited), `memory_bytes_limit` (int or `null` if unlimited),
  `version` (1 or 2). Returns `{}` on non-Linux systems or when the
  cgroup filesystem is unavailable.

  ```python
  class Bench(MicroBench, MBSlurmInfo, MBCgroupLimits):
      pass
  ```

  ```json
  {
    "cgroups": {
      "cpu_cores_limit": 4.0,
      "memory_bytes_limit": 17179869184,
      "version": 2
    }
  }
  ```

- **`bench.time(name)` sub-timing API**: label phases inside a single benchmark
  record with named timing sections. Sub-timings accumulate in `call.timings` as
  `[{"name": ..., "duration": ...}, ...]` in call order. Compatible with
  `bench.record()`, `bench.arecord()`, `@bench` (sync and async), and
  `bench.record_on_exit()`. Calling outside an active benchmark is a silent
  no-op; `call.timings` is absent when `bench.time()` is never called.

  ```python
  with bench.record('pipeline'):
      with bench.time('parse'):
          data = parse(raw)
      with bench.time('transform'):
          result = transform(data)
  ```

- **Async support**: the `@bench` decorator now detects `async def` functions
  and returns an `async def` wrapper that must be awaited. A new
  `bench.arecord(name)` method provides the async counterpart of
  `bench.record()` for use with `async with`. All mixins, static fields,
  output sinks, `iterations`, and `warmup` work identically to the sync path.
  `MBLineProfiler` raises `NotImplementedError` at decoration time when used
  with an async function (line profiling of coroutines is not supported).

  ```python
  @bench
  async def fetch():
      await asyncio.sleep(0.01)

  asyncio.run(fetch())

  async with bench.arecord('load'):
      await load_data()
  ```

  **Note:** elapsed time includes event-loop interleaving from other concurrent
  tasks; run in an otherwise-idle event loop for repeatable results.

- **`bench.record_on_exit(name, handle_sigterm=True)`**: registers a
  process-exit handler that writes one benchmark record when the script
  terminates. Captures wall-clock duration from the call site to exit plus
  all mixin fields. Designed for SLURM jobs and batch scripts where
  restructuring code around a decorator is impractical. Key behaviours:
  - By default installs a SIGTERM handler (main thread only) that writes
    the record, chains to any existing SIGTERM handler, then re-delivers
    SIGTERM so the process exits with the conventional code 143 (128 + 15).
  - Wraps `sys.excepthook` to capture unhandled exceptions into an
    `exception` field before the process exits.
  - Adds an `exit_signal` field when the exit was triggered by SIGTERM.
  - Falls back to writing the record to `sys.stderr` if the primary output
    sink raises (e.g. filesystem unmounted at exit time).
  - Calling a second time on the same instance replaces the first
    registration and resets the start time.

- **`bench.record(name)` context manager**: times an arbitrary code block
  and writes one record, without requiring the code to be in a named
  function. All mixins, static fields, and output sinks behave identically
  to the decorator form.

- **Exception capture**: when a benchmarked block raises — via
  `bench.record()` or a `@bench`-decorated function — the record is
  written before the exception propagates. An `exception` field is added
  containing `{"type": ..., "message": ...}`. The exception is always
  re-raised. With `--iterations N`, timing stops at the first exception.

- **`microbench` console entry point**: `microbench` is now available as a
  shell command after installation — no need to spell out `python -m microbench`.
  `python -m microbench` remains fully equivalent and is still the recommended
  form when you need to select a specific Python interpreter explicitly.

- **`MBPythonInfo` mixin** replaces `MBPythonVersion`: records a `python` dict
  with `version`, `prefix` (`sys.prefix`), and `executable` (`sys.executable`),
  giving a complete picture of the running interpreter in one field. `MBPythonVersion`
  is deprecated and will be removed in a future release. `MBPythonInfo` is included
  in :class:`MicroBench` by default (Python API) and in the CLI default mixin set;
  `--no-mixin` suppresses it on the CLI as usual.

- **`MicroBenchBase`**: the core benchmarking machinery is now exposed as
  `MicroBenchBase` (no default mixins). `MicroBench` inherits from both
  `MicroBenchBase` and `MBPythonInfo`. Subclass `MicroBenchBase` directly when
  you need a completely bare benchmark class with no automatic captures.

- **`MBCondaPackages` improvements**:
  - Queries the environment identified by `CONDA_PREFIX` (the shell's active conda
    environment) rather than `sys.prefix`. Falls back to `sys.prefix` when
    `CONDA_PREFIX` is not set.
  - Falls back to `CONDA_EXE` if `conda` is not on `PATH` (common in non-interactive
    SLURM batch scripts where conda is activated but its `bin/` is not on `PATH`).
  - Replaces the separate `conda_versions` field with a unified `conda` dict
    containing `name` (`CONDA_DEFAULT_ENV`), `path` (`CONDA_PREFIX`), and
    `packages` (the version dict). Either of `name`/`path` may be `None` if
    the corresponding variable is unset. With `get_results(flat=True)` these
    expand to `conda.name`, `conda.path`, `conda.packages.<pkg>` etc.

- **Command-line interface** (`python -m microbench`): wrap any external
  command and record host metadata alongside timing without writing Python
  code. Useful for SLURM jobs, shell scripts, and compiled executables.
  Records `command`, `returncode` (list, one per timed iteration),
  alongside the standard timing fields. Mixins are specified by short
  kebab-case names without the `MB` prefix (e.g. `host-info`,
  `python-version`); original MB-prefixed names are also accepted. Use
  `--mixin MIXIN [MIXIN ...]` to select metadata to capture (defaults to
  `host-info`, `slurm-info`, `loaded-modules`, and `working-dir`); use `--show-mixins` to
  list all available mixins with descriptions; use `--field KEY=VALUE` to
  attach extra labels; use `--iterations N` and `--warmup N` for repeat
  timing; use `--stdout[=suppress]` and `--stderr[=suppress]` to capture
  subprocess output into the record (output is re-printed to the terminal
  unless `=suppress` is given); use `--monitor-interval SECONDS` to sample
  child process CPU and memory over time (see below). Some mixins expose
  their own configuration flags (shown in `--show-mixins` and `--help`):
  `git-info` adds `--git-repo DIR` (default: current working directory),
  and `file-hash` adds `--hash-file FILE [FILE ...]` (default: the
  benchmarked command) and `--hash-algorithm ALGORITHM` (default:
  `sha256`). Mixin flags are validated before the subprocess runs — passing
  a non-existent path or a directory where a file is expected is caught
  immediately. Supplying a mixin flag without loading the corresponding
  mixin is an error. Capture failures are non-fatal by default
  (`capture_optional = True`), making the CLI safe across heterogeneous
  cluster nodes. The process exits with the highest returncode seen across
  all timed iterations.

- **CLI subprocess monitoring** (`--monitor-interval SECONDS`): periodically
  sample the child process's CPU usage and resident memory (RSS) while it
  runs and record the time series in `call.monitor`. Requires
  `psutil`. Each element of `call.monitor` is a list of
  `{"timestamp", "cpu_percent", "rss_bytes"}` dicts for one timed
  iteration; warmup iterations are excluded. Works on Linux, macOS, and
  Windows. If the process exits before the first sample fires, the field is
  omitted rather than written as empty.

- **`capture_optional` class attribute**: set `capture_optional = True` on
  a benchmark class to catch exceptions from `capture_` and `capturepost_`
  methods instead of aborting the benchmark call. Failures are recorded in
  `call.capture_errors` (a list of `{"method": ..., "error": ...}` dicts);
  the field is absent when all captures succeed. Designed for production
  jobs on heterogeneous cluster nodes where optional dependencies may not
  be present on every node.

- **`MBLoadedModules` mixin**: captures the loaded Lmod / Environment
  Modules software stack into a `loaded_modules` dict mapping module name
  to version string (e.g. `{"gcc": "12.2.0", "openmpi": "4.1.5"}`). Reads
  the standard `LOADEDMODULES` environment variable — no subprocess, no
  extra dependencies. Empty dict when no modules are loaded. Included in
  the CLI defaults alongside `MBHostInfo`, `MBSlurmInfo`, and `MBWorkingDir`.

- **`MBWorkingDir` mixin**: captures the absolute path of the working
  directory at benchmark time into `call.working_dir`. No dependencies.
  Included in the CLI defaults — useful for reproducibility when comparing
  results across nodes or directories.

- **`MBGitInfo` mixin**: captures the repository root path, current commit
  hash, branch name, and dirty flag (uncommitted changes present) via
  `git` ≥ 2.11 on PATH. Stored in `git`. Set `git_repo` to inspect
  a specific repository directory.

- **`MBPeakMemory` mixin**: captures peak Python memory allocation during the
  benchmarked function as `call.peak_memory_bytes` (bytes), using
  `tracemalloc` from the standard library. No extra dependencies required.

- **`MBSlurmInfo` mixin**: captures all `SLURM_*` environment variables into
  a `slurm` dict (keys lowercased, `SLURM_` prefix stripped). Empty dict
  when running outside a SLURM job. Supersedes the manual
  `env_vars = ('SLURM_JOB_ID', ...)` pattern.

- **`MBFileHash` mixin**: records a cryptographic checksum of specified files
  in the `file_hashes` field (a dict mapping path to hex digest). Defaults to
  hashing `sys.argv[0]` — the running script. Set `hash_files` to an iterable
  of paths to hash specific files instead. Set `hash_algorithm` to any
  algorithm accepted by `hashlib.new` (default: `'sha256'`).

- **`warmup` parameter**: pass `warmup=N` to run the function `N` times
  before timing begins, priming caches or JIT compilation without affecting
  results. Warmup calls are unrecorded and do not interact with the monitor
  thread or capture triggers.

- **Multi-sink output architecture** (#52): Results can now be written to
  multiple destinations simultaneously by passing an `outputs` list to
  `MicroBench`. Three classes make up the new output API:
  - `Output` — abstract base class; subclass this to implement custom sinks.
  - `FileOutput` — writes JSONL to a file path or file-like object (wraps the
    previous default behaviour).
  - `RedisOutput` — writes to a Redis list.

  The existing `outfile` parameter and class-level `outfile` attribute continue
  to work as shorthand for a single `FileOutput`. Passing both `outfile` and
  `outputs` raises `ValueError`.

  Example — write to a file and Redis simultaneously:

  ```python
  from microbench import MicroBench, FileOutput, RedisOutput

  bench = MicroBench(outputs=[
      FileOutput('/home/user/results.jsonl'),
      RedisOutput('microbench:mykey', host='redis-host', port=6379),
  ])
  ```

  `get_results()` delegates to the first sink that supports reading back
  results (`FileOutput` and `RedisOutput` both do).

Also includes all changes from v1.1.0.

### Refactoring

- **Module structure split**: the `microbench/__init__.py` god-module and the
  `microbench/__main__.py` CLI monolith have been broken into focused
  subpackages:
  - `microbench/core/` — `bench.py`, `contexts.py`, `encoding.py`,
    `monitoring.py`
  - `microbench/mixins/` — `base.py`, `call.py`, `python.py`, `system.py`,
    `vcs.py`, `profiling.py`, `gpu.py`
  - `microbench/outputs/` — `base.py`, `file.py`, `http.py`, `redis.py`,
    `utils.py`
  - `microbench/cli/` — `main.py`, `parser.py`, `registry.py`, `runner.py`
  - `microbench/version.py` — `__version__` in its own module

  The **public import surface is preserved**: `from microbench import
  MicroBench`, all `MB*` mixins, output classes, `JSONEncoder`, `summary`, and
  `__version__` all continue to work unchanged.

  The old *private* module paths (`microbench._mixins`, `microbench._output`,
  `microbench._encoding`) are deprecated and no longer re-export every symbol
  they previously exposed. If your code imports from these private paths,
  migrate to direct `from microbench import ...` imports.

- **`_apply_default_mixin()` removed**: the runtime class-construction hack
  that deferred `MBPythonInfo` inclusion to avoid a circular import has been
  replaced with a direct `class MicroBench(MBPythonInfo, MicroBenchBase)`
  definition. No circular import occurs with the new layout.

- **`_is_microbench_internal()` circular import fixed**: `mixins/python.py`
  now resolves the package directory from `__file__` directly instead of
  importing from `__init__`.

## [1.1.0] - 2026-03-13

### New features

- **`mb_run_id` and `mb_version` fields added to every record** (#53): Both
  fields are included automatically without any configuration.
  - `mb_run_id` — UUID generated once at import time and shared by all
    `MicroBench` instances in the same process. Allows records from independent
    bench suites to be correlated with `groupby('mb_run_id')`.
  - `mb_version` — version of the `microbench` package that produced the
    record; essential for long-running studies where the benchmark code evolves.
