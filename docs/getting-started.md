# Getting started

## Minimal example

Create a benchmark suite, attach it to a function as a decorator, then call
the function as normal:

```python
from microbench import MicroBench

bench = MicroBench()

@bench
def my_function(x):
    return x ** 2

my_function(42)
```

By default results are captured into an in-memory buffer. Read them back as
a pandas DataFrame:

```python
results = bench.get_results()
```

Every record contains these fields automatically:

| Field | Description |
|---|---|
| `mb_run_id` | UUID generated once when `microbench` is imported. Identical across all bench suites in the same process — use `groupby('mb_run_id')` to correlate records from independent suites. |
| `mb_version` | Version of the `microbench` package that produced the record. |
| `start_time` | ISO-8601 timestamp when the function was called (UTC by default). |
| `finish_time` | ISO-8601 timestamp when the function returned. |
| `run_durations` | List of per-iteration durations in seconds. |
| `function_name` | Name of the decorated function. |
| `timestamp_tz` | Timezone used for `start_time`/`finish_time`. |
| `duration_counter` | Name of the timer function used for `run_durations`. |

## Extended example

Subclass `MicroBench` when you want to add [mixins](user-guide/mixins.md)
or set reusable configuration. Pass keyword arguments to the constructor to
attach experiment metadata to every record:

```python
from microbench import MicroBench, MBFunctionCall, MBPythonVersion, MBHostInfo
import numpy, pandas, time

class MyBench(MicroBench, MBFunctionCall, MBPythonVersion, MBHostInfo):
    outfile = '/home/user/my-benchmarks.jsonl'
    capture_versions = (numpy, pandas)
    env_vars = ('CUDA_VISIBLE_DEVICES',)

benchmark = MyBench(experiment='run-1', iterations=3,
                    duration_counter=time.monotonic)
```

- `outfile` saves results to a file (one JSON object per line).
- `capture_versions` records the versions of specified packages.
- `env_vars` captures environment variables as `env_<NAME>` fields — see [Environment variables](user-guide/configuration.md#environment-variables) for more. For SLURM jobs, use `MBSlurmInfo` instead.
- `iterations=3` runs the function three times, recording all three durations.
- `duration_counter` overrides the timer (see [Configuration](user-guide/configuration.md)).
- `experiment='run-1'` adds a custom `experiment` field to every record.

!!! tip "Class attributes vs constructor arguments"
    **Class attributes** configure microbench's own behaviour — `outfile`,
    `capture_versions`, `env_vars`, mixin-specific settings like
    `nvidia_attributes`. They are shared across all instances of the class.

    **Constructor keyword arguments** attach experiment metadata to every
    record — use them for labels like `experiment=`, `trial=`, `node=`.
    They are stored verbatim in each JSON record.

    If you don't need mixins, skip the class entirely:

    ```python
    bench = MicroBench(outfile='/home/user/results.jsonl')
    ```

## Saving results to a file

Pass `outfile` as a constructor argument or set it as a class attribute:

```python
bench = MicroBench(outfile='/home/user/results.jsonl')
```

Results are appended in [JSONL](https://jsonlines.org/) format (one JSON
object per line). Read them back with pandas:

```python
import pandas
results = pandas.read_json('/home/user/results.jsonl', lines=True)
```

Or via `get_results()`, which works regardless of the output sink:

```python
results = bench.get_results()
```

## Analysing results

Load results into a pandas DataFrame and use its full range of aggregation
and filtering capabilities:

```python
import pandas

results = pandas.read_json('/home/user/my-benchmarks.jsonl', lines=True)

# Total elapsed time per call
results['elapsed'] = results['finish_time'] - results['start_time']

# Average runtime by Python version
results.groupby('python_version')['elapsed'].mean()

# Correlate all records from the same process run
results.groupby('mb_run_id')['elapsed'].describe()
```

See the [pandas documentation](https://pandas.pydata.org/docs/) for more.
