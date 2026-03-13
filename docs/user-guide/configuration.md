# Configuration

## Constructor parameters

| Parameter | Default | Description |
|---|---|---|
| `outfile` | `None` | File path or file-like object to write results to. |
| `json_encoder` | `JSONEncoder` | Custom JSON encoder class. |
| `tz` | `timezone.utc` | Timezone for `start_time` / `finish_time`. |
| `iterations` | `1` | Number of times to run the decorated function. |
| `duration_counter` | `time.perf_counter` | Callable used for `run_durations`. |

Any additional keyword arguments are stored as extra fields in every record:

```python
bench = MicroBench(experiment='run-42', node='gpu-node-03')
```

## Environment variables

Set `env_vars` as a class attribute to capture specific environment
variables into every record. Each variable is stored as `env_<NAME>`; if
the variable is unset it is recorded as `null`:

```python
from microbench import MicroBench

class MyBench(MicroBench):
    env_vars = ('MY_VAR', 'ANOTHER_VAR')
```

### HPC / SLURM

In SLURM environments, capture job and task identifiers automatically:

```python
class SlurmBench(MicroBench):
    env_vars = (
        'SLURM_JOB_ID',
        'SLURM_ARRAY_TASK_ID',
        'SLURM_NODELIST',
        'SLURM_CPUS_PER_TASK',
    )
```

Fields are stored as `env_SLURM_JOB_ID`, `env_SLURM_ARRAY_TASK_ID`, etc.
Combined with `mb_run_id`, this lets you group and compare results across
all tasks in a job array:

```python
results.groupby(['mb_run_id', 'env_SLURM_ARRAY_TASK_ID'])['run_durations'].mean()
```

Run `env | grep SLURM` inside a job to see which variables are available
in your cluster's environment.

## Duration timings

`run_durations` are measured using `time.perf_counter` by default, which
gives wall-clock time in fractional seconds. Override with any callable that
returns a numeric value:

```python
import time
from microbench import MicroBench

# Nanosecond precision
bench = MicroBench(duration_counter=time.perf_counter_ns)

# Monotonic clock (unaffected by NTP adjustments)
bench = MicroBench(duration_counter=time.monotonic)
```

The name of the counter function is recorded in the `duration_counter` field
so results remain interpretable after the code changes.

When `iterations > 1`, `run_durations` is a list with one entry per
iteration. The function's return value is always taken from the final
iteration.

## Timezones

`start_time` and `finish_time` are ISO-8601 timestamps in UTC by default.
Override with any `datetime.timezone`:

```python
import datetime
from microbench import MicroBench

# Local machine timezone
bench = MicroBench(tz=datetime.datetime.now().astimezone().tzinfo)
```

UTC is recommended when comparing results across machines in different
locations. The timezone is also recorded in the `timestamp_tz` field.

## Runtime impact

Capturing environment variables, package versions, and timing has negligible
overhead. Things with measurable cost:

- **`MBNvidiaSmi`** — spawns a subprocess per invocation; typically < 1 s.
- **`MBInstalledPackages` / `MBCondaPackages`** — enumerates all installed
  packages; can take several seconds on large environments. Consider running
  once and storing the output separately rather than capturing on every call.
- **Periodic monitoring** — background thread with configurable interval.
  Keep `monitor_interval` at 60 s or more to avoid meaningful overhead.
- **`MBLineProfiler`** — instruments every line; expect 2–5× slowdown on
  typical Python code. Only use for profiling runs, not production timing.
