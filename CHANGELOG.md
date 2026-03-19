# Changelog

All notable changes to microbench are documented here.

## [2.1.0] - 2026-03-19

### New features

- **`MBResourceUsage` mixin**: captures POSIX `getrusage()` data — user and
  system CPU time, peak RSS (in bytes, normalised across platforms), minor and
  major page faults, block I/O operations, and voluntary/involuntary context
  switches. Works in both CLI and Python API modes: CLI uses `RUSAGE_CHILDREN`
  (subprocess resources); Python API uses `RUSAGE_SELF` (current-process
  delta). Results are stored in `resource_usage`. Added as a **default CLI
  mixin** so every CLI run captures it automatically.

  On Windows (where the `resource` module is unavailable) the mixin records an
  empty dict without raising an error.

### Enhancements

- **`--mixin defaults` keyword** (CLI): `defaults` can be used as a mixin
  name to expand to the standard default set (`python-info`, `host-info`,
  `slurm-info`, `loaded-modules`, `working-dir`). This makes it easy to add
  one or more extra mixins without listing all five defaults explicitly:
  `microbench --mixin defaults file-hash -- ./job.sh`.

- **`file-hash` mixin — automatic argument file scanning** (CLI): the
  default hash list now includes not only the command executable (`cmd[0]`)
  but also any command-line arguments (`cmd[1:]`) that resolve to existing
  files on disk prior to command execution. Passing `--hash-file` still
  overrides the default entirely; the Python API is unaffected. The hash
  algorithm name is now stored under `mb.file_hash_algorithm`.

### Documentation

- Fix documentation on writing custom mixins to note that they must be
  added to the registry if they are to be detected by the CLI.

## [2.0.0] - 2026-03-17

Microbench v2 is a significant upgrade with many new features versus v1.1.0.
Be sure to review the breaking changes before upgrading.

### New features

- **Command-line interface** (`microbench -- COMMAND`): wrap any external
  command and record host metadata alongside timing without writing Python
  code. Useful for SLURM jobs, shell scripts, and compiled executables.

    * Records `command`, `returncode` (list, one per timed iteration),
  alongside the standard timing fields. Mixins are specified by short
  kebab-case names without the `MB` prefix (e.g. `host-info`);
  original MB-prefixed names are also accepted.
    * Use
  `--mixin MIXIN [MIXIN ...]` to select metadata to capture (defaults to
  `host-info`, `slurm-info`, `loaded-modules`, `python-info`
  and `working-dir`)
    * Use `--show-mixins` to
  list all available mixins with descriptions; use `--field KEY=VALUE` to
  attach extra labels
    * Use `--iterations N` and `--warmup N` for repeat
  timing
    * Use `--stdout[=suppress]` and `--stderr[=suppress]` to capture subprocess output into the record (output is re-printed to the terminal
  unless `=suppress` is given)
    * Use `--monitor-interval SECONDS` to sample
  child process CPU and memory over time.
    * Some mixins expose
  their own configuration flags (shown in `--show-mixins` and `--help`)
    * Capture failures are non-fatal by default
  (`capture_optional = True`), making the CLI safe across heterogeneous
  cluster nodes.
    * The process exits with the first non-zero returncode seen
  across all timed iterations if present, or zero (success) otherwise.

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

- **`bench.time(name)` sub-timing**: [Python API] label phases inside a single benchmark
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

- **Async support**: [Python API] the `@bench` decorator now detects `async def` functions
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

- **`bench.record_on_exit(name, handle_sigterm=True)`**: [Python API]
  registers a
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

- **`bench.record(name)` context manager**: [Python API] times an arbitrary code block
  and writes one record, without requiring the code to be in a named
  function. All mixins, static fields, and output sinks behave identically
  to the decorator form.

- **Exception capture**: [Python API] when a benchmarked block raises — via
  `bench.record()` or a `@bench`-decorated function — the record is
  written before the exception propagates. An `exception` field is added
  containing `{"type": ..., "message": ...}`. The exception is always
  re-raised. With `--iterations N`, timing stops at the first exception.

- **`MBPythonInfo` mixin** replaces `MBPythonVersion`: records a `python` dict
  with `version`, `prefix` (`sys.prefix`), and `executable` (`sys.executable`),
  giving a complete picture of the running interpreter in one field. `MBPythonVersion`
  has been removed (see breaking changes above). `MBPythonInfo` is included
  in `MicroBench` by default (Python API) and in the CLI default mixin set;
  `--no-mixin` suppresses it on the CLI as usual.

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

- **`MBCgroupLimits` mixin**: captures the CPU quota and memory limit enforced by
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

- **`MicroBenchBase`**: the core benchmarking machinery is now exposed as
  `MicroBenchBase` (no default mixins). `MicroBench` inherits from both
  `MicroBenchBase` and `MBPythonInfo`. Subclass `MicroBenchBase` directly when
  you need a completely bare benchmark class with no automatic captures.

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
  - `HttpOutput` - New for v2 - POST each benchmark result to an HTTP/HTTPS endpoint.

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

- **`get_results(format=..., flat=...)`**: `get_results` now accepts two
  keyword arguments.
  - `format='dict'` (default) — returns a list of dicts; no pandas required.
  - `format='df'` — returns a pandas DataFrame (previous default behaviour).
  - `flat=True` — flattens nested dict fields (e.g. `slurm`, `cgroups`,
    `git`) into dot-notation keys (`slurm.job_id`, `call.name`). Works for both
    formats without requiring pandas.

- **`capture_optional` class attribute**: set `capture_optional = True` on
  a benchmark class to catch exceptions from `capture_` and `capturepost_`
  methods instead of aborting the benchmark call. Failures are recorded in
  `call.capture_errors` (a list of `{"method": ..., "error": ...}` dicts);
  the field is absent when all captures succeed. Designed for production
  jobs on heterogeneous cluster nodes where optional dependencies may not
  be present on every node.

- **`python-dateutil` dependency removed from `LiveStream`**: timestamp
  parsing now uses `datetime.fromisoformat()` from the standard library.
  Remove `python-dateutil` from your environment if it was
  only installed for microbench.

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
  | `telemetry` | `call.monitor` |
  | `env_*` (flat keys) | `env.*` (dict) |
  | `package_versions` (from `capture_versions`) | `python.loaded_packages` |

  **Mixin fields** move to typed namespaces:

  | Old key | New key |
  |---|---|
  | `hostname` | `host.hostname` |
  | `operating_system` | `host.os` |
  | `cpu_cores_physical` | `host.cpu_cores_physical` |
  | `ram_total` | `host.ram_total` |
  | `args` | `call.args` |
  | `kwargs` | `call.kwargs` |
  | `return_value` | `call.return_value` |
  | `line_profiler` | `call.line_profiler` |
  | `package_versions` (MBGlobalPackages) | `python.loaded_packages` |
  | `package_versions` (MBInstalledPackages) | `python.installed_packages` |
  | `package_paths` | `python.installed_package_paths` |
  | `nvidia_<attr>` (multiple flat dicts) | `nvidia` (list of per-GPU dicts with `uuid` key) |

  Unchanged namespaces: `conda`.

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

- **`LiveStream` updated for v2 record schema**: field references updated from
  the v1 flat schema (`function_name`, `hostname`, `start_time`,
  `finish_time`) to the v2 nested schema (`call.name`, `host.hostname`,
  `call.start_time`, `call.finish_time`). Records produced by microbench v1
  are no longer parsed correctly by `LiveStream`; this is expected given the
  v2 schema migration documented in the breaking changes section above.

## [1.1.0] - 2026-03-13

### New features

- **`mb_run_id` and `mb_version` fields added to every record** (#53): Both
  fields are included automatically without any configuration.
  - `mb_run_id` — UUID generated once at import time and shared by all
    `MicroBench` instances in the same process. Allows records from independent
    bench suites to be correlated with `groupby('mb_run_id')`.
  - `mb_version` — version of the `microbench` package that produced the
    record; essential for long-running studies where the benchmark code evolves.
