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

### New features

- **Multi-sink output architecture**: Results can now be written to multiple
  destinations simultaneously by passing an `outputs` list to `MicroBench`.
  Three classes make up the new output API:
  - `Output` — abstract base class; subclass this to implement custom sinks.
  - `FileOutput` — writes JSONL to a file path or file-like object (wraps the
    previous default behaviour).
  - `RedisOutput` — writes to a Redis list; extracted from `MicroBenchRedis`.

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

  `MicroBenchRedis` is now thin sugar for
  `MicroBench(outputs=[RedisOutput(...)])` and retains its existing interface.

  `get_results()` on `MicroBench` delegates to the first sink that supports
  reading back results (`FileOutput` and `RedisOutput` both do).
