# Changelog

All notable changes to microbench are documented here.

## [2.0.0] - unreleased

### Breaking changes

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
