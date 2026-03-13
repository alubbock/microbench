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

## Basic setup

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

Samples are stored as a list in the `monitor` field of each result record,
each entry including a `timestamp` and whatever your `monitor` method
returns:

```json
{
  "monitor": [
    {"timestamp": "2024-01-01T00:00:00+00:00", "rss": 104857600, "vms": 536870912},
    {"timestamp": "2024-01-01T00:01:30+00:00", "rss": 209715200, "vms": 536870912}
  ]
}
```

## Configuration

| Class variable | Default | Description |
|---|---|---|
| `monitor_interval` | `60` | Seconds between samples |
| `monitor_timeout` | `30` | Seconds to wait for the monitor thread to stop cleanly |

## Sampling all available process info

```python
class MyBench(MicroBench):
    @staticmethod
    def monitor(process):
        return process.as_dict(attrs=[
            'cpu_percent', 'memory_info', 'num_threads'
        ])
```

## Notes

- The monitor thread takes an initial sample immediately when the function
  starts, then repeats at `monitor_interval` seconds.
- Signal handlers (`SIGINT`/`SIGTERM`) are registered to stop the thread
  cleanly. If the benchmark is started from a non-main thread, a
  `RuntimeWarning` is issued and signal handlers are skipped.
- Monitor results are stored with the record regardless of whether the
  function raises an exception.
