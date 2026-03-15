# Changelog

All notable changes to microbench are documented here.

## [2.0.0] - unreleased

### Breaking changes

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
  - `flat=True` — flattens nested dict fields (e.g. `slurm`, `cgroup_limits`,
    `git_info`) into dot-notation keys (`slurm.job_id`). Works for both
    formats without requiring pandas.

- **`summary(results)` / `bench.summary()`**: prints min / mean / median /
  max / stdev of `run_durations` across all results. No dependencies required
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
  v1 and v2). Fields in `cgroup_limits`: `cpu_cores` (float — quota ÷ period,
  or `null` if unlimited), `memory_bytes` (int or `null` if unlimited),
  `cgroup_version` (1 or 2). Returns `{}` on non-Linux systems or when the
  cgroup filesystem is unavailable.

  ```python
  class Bench(MicroBench, MBSlurmInfo, MBCgroupLimits):
      pass
  ```

  ```json
  {
    "cgroup_limits": {
      "cpu_cores": 4.0,
      "memory_bytes": 17179869184,
      "cgroup_version": 2
    }
  }
  ```

- **`bench.time(name)` sub-timing API**: label phases inside a single benchmark
  record with named timing sections. Sub-timings accumulate in `mb_timings` as
  `[{"name": ..., "duration": ...}, ...]` in call order. Compatible with
  `bench.record()`, `bench.arecord()`, `@bench` (sync and async), and
  `bench.record_on_exit()`. Calling outside an active benchmark is a silent
  no-op; `mb_timings` is absent when `bench.time()` is never called.

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

- **Command-line interface** (`python -m microbench`): wrap any external
  command and record host metadata alongside timing without writing Python
  code. Useful for SLURM jobs, shell scripts, and compiled executables.
  Records `command`, `returncode` (list, one per timed iteration),
  alongside the standard timing fields. Mixins are specified by short
  kebab-case names without the `MB` prefix (e.g. `host-info`,
  `python-version`); original MB-prefixed names are also accepted. Use
  `--mixin MIXIN [MIXIN ...]` to select metadata to capture (defaults to
  `host-info`, `slurm-info`, and `loaded-modules`); use `--show-mixins` to
  list all available mixins with descriptions; use `--field KEY=VALUE` to
  attach extra labels; use `--iterations N` and `--warmup N` for repeat
  timing; use `--stdout[=suppress]` and `--stderr[=suppress]` to capture
  subprocess output into the record (output is re-printed to the terminal
  unless `=suppress` is given); use `--monitor-interval SECONDS` to sample
  child process CPU and memory over time (see below). Capture failures are
  non-fatal by default (`capture_optional = True`), making the CLI safe
  across heterogeneous cluster nodes. The process exits with the highest
  returncode seen across all timed iterations.

- **CLI subprocess monitoring** (`--monitor-interval SECONDS`): periodically
  sample the child process's CPU usage and resident memory (RSS) while it
  runs and record the time series in `subprocess_monitor`. Requires
  `psutil`. Each element of `subprocess_monitor` is a list of
  `{"timestamp", "cpu_percent", "rss_bytes"}` dicts for one timed
  iteration; warmup iterations are excluded. Works on Linux, macOS, and
  Windows. If the process exits before the first sample fires, the field is
  omitted rather than written as empty.

- **`capture_optional` class attribute**: set `capture_optional = True` on
  a benchmark class to catch exceptions from `capture_` and `capturepost_`
  methods instead of aborting the benchmark call. Failures are recorded in
  `mb_capture_errors` (a list of `{"method": ..., "error": ...}` dicts);
  the field is absent when all captures succeed. Designed for production
  jobs on heterogeneous cluster nodes where optional dependencies may not
  be present on every node.

- **`MBLoadedModules` mixin**: captures the loaded Lmod / Environment
  Modules software stack into a `loaded_modules` dict mapping module name
  to version string (e.g. `{"gcc": "12.2.0", "openmpi": "4.1.5"}`). Reads
  the standard `LOADEDMODULES` environment variable — no subprocess, no
  extra dependencies. Empty dict when no modules are loaded. Included in
  the CLI defaults alongside `MBHostInfo` and `MBSlurmInfo`.

- **`MBGitInfo` mixin**: captures the repository root path, current commit
  hash, branch name, and dirty flag (uncommitted changes present) via
  `git` ≥ 2.11 on PATH. Stored in `git_info`. Set `git_repo` to inspect
  a specific repository directory.

- **`MBPeakMemory` mixin**: captures peak Python memory allocation during the
  benchmarked function as `peak_memory_bytes` (bytes), using
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

## [1.1.0] - 2026-03-13

### New features

- **`mb_run_id` and `mb_version` fields added to every record** (#53): Both
  fields are included automatically without any configuration.
  - `mb_run_id` — UUID generated once at import time and shared by all
    `MicroBench` instances in the same process. Allows records from independent
    bench suites to be correlated with `groupby('mb_run_id')`.
  - `mb_version` — version of the `microbench` package that produced the
    record; essential for long-running studies where the benchmark code evolves.
