# Periodic monitoring

!!! note "Renamed from v1.x"
    In v1.x this feature used `telemetry` throughout the API
    (`telemetry_interval`, `telemetry_timeout`, result field `telemetry`).
    These names were renamed to `monitor` / `monitor_interval` /
    `monitor_timeout` in v2.0.

Microbench can sample resource usage in a background thread throughout the
execution of a benchmarked function. This is useful for tracking how memory
or CPU usage changes over time during a long-running computation.

Requires [psutil](https://pypi.org/project/psutil/).

!!! warning "Record size"
    All samples are accumulated in memory and written as part of the record
    when the benchmark completes. A long-running process sampled at a short
    interval can produce a large number of samples — for example, a 10-hour
    job sampled every 5 seconds yields 7,200 samples per iteration. Estimate
    your expected sample count (runtime ÷ interval) and choose an interval
    long enough to keep the record size and memory usage manageable.

## CLI

Pass `--monitor-interval SECONDS` to periodically sample the child process's
CPU usage and RSS memory while it runs:

```bash
microbench \
    --outfile results.jsonl \
    --monitor-interval 5 \
    -- ./run_simulation.sh --steps 10000
```

Each sample has three fixed fields:

| Field | Description |
|---|---|
| `timestamp` | ISO 8601 UTC timestamp of the sample |
| `cpu_percent` | CPU usage of the child process at sample time |
| `rss_bytes` | Resident set size of the child process in bytes |

Samples are stored in `call.monitor` as a list of per-iteration lists (one
inner list per `--iterations` call, warmup excluded):

```json
{
  "call": {
    "monitor": [
      [
        {"timestamp": "2025-01-01T12:00:05Z", "cpu_percent": 0.0,  "rss_bytes": 52428800},
        {"timestamp": "2025-01-01T12:00:10Z", "cpu_percent": 87.3, "rss_bytes": 61865984}
      ]
    ]
  }
}
```

If the process exits before the first sample fires, `call.monitor` is omitted
from the record.

Only the direct child process is sampled; grandchild subprocesses are not
included.

## Python API

Define a `monitor` static method on your benchmark class. It receives a
[`psutil.Process`](https://psutil.readthedocs.io/en/latest/#psutil.Process)
object and should return a dictionary of sample data. Microbench handles
launching and cleaning up the background thread automatically.

```python
from microbench import MicroBench

class MyBench(MicroBench):
    monitor_interval = 90  # seconds between samples (default: 60)

    @staticmethod
    def monitor(process):
        mem = process.memory_full_info()
        return {'rss': mem.rss, 'vms': mem.vms}

bench = MyBench()

@bench
def my_function():
    # ... long-running work ...
    pass
```

Samples are stored as a flat list in the `call.monitor` field of each result
record, each entry including a `timestamp` and whatever your `monitor` method
returns:

```json
{
  "call": {
    "monitor": [
      {"timestamp": "2024-01-01T00:00:00+00:00", "rss": 104857600, "vms": 536870912},
      {"timestamp": "2024-01-01T00:01:30+00:00", "rss": 209715200, "vms": 536870912}
    ]
  }
}
```

### Configuration

| Class variable | Default | Description |
|---|---|---|
| `monitor_interval` | `60` | Seconds between samples |
| `monitor_timeout` | `30` | Seconds to wait for the monitor thread to stop cleanly |

### Sampling all available process info

```python
class MyBench(MicroBench):
    @staticmethod
    def monitor(process):
        return process.as_dict(attrs=[
            'cpu_percent', 'memory_info', 'num_threads'
        ])
```

### Notes

- The monitor thread takes an initial sample immediately when the function
  starts, then repeats at `monitor_interval` seconds.
- Signal handlers (`SIGINT`/`SIGTERM`) are registered to stop the thread
  cleanly. If the benchmark is started from a non-main thread, a
  `RuntimeWarning` is issued and signal handlers are skipped.
- Monitor results are stored with the record regardless of whether the
  function raises an exception.
