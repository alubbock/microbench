# Getting started

## Minimal example

Microbench works by adding a Python decorator (e.g. `@bench`) to the function
you want to benchmark. To benchmark `my_function`, you create the
benchmark suite `bench`, add the decorator to your function, and simply
call it as normal:

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
| `mb_run_id` | UUID generated once when `microbench` is imported. Identical across all bench suites in the same process — use `groupby('mb_run_id')` to correlate records from different benchmarks in the same run. |
| `mb_version` | Version of the `microbench` package that produced the record. |
| `start_time` | ISO-8601 timestamp when the function was called (UTC by default). |
| `finish_time` | ISO-8601 timestamp when the function returned. |
| `run_durations` | List of per-iteration durations in seconds. |
| `function_name` | Name of the decorated function. |
| `timestamp_tz` | Timezone used for `start_time`/`finish_time`. |
| `duration_counter` | Name of the timer function used for `run_durations`. |

## Extended example

Here's an extended example to give you an idea of real-world usage.

```python
from microbench import MicroBench, MBFunctionCall, MBPythonVersion, \
    MBHostInfo, MBSlurmInfo
import numpy, pandas, time

class MyBench(MicroBench, MBFunctionCall, MBPythonVersion, MBHostInfo, MBSlurmInfo):
    outfile = '/home/user/my-benchmarks.jsonl'
    capture_versions = (numpy, pandas)
    env_vars = ('CUDA_VISIBLE_DEVICES',)

benchmark = MyBench(experiment='run-1', iterations=3,
                    duration_counter=time.monotonic)

@benchmark
def myfunction(arg1, arg2):
    ...

myfunction(x, y)
```

Mixins used:
- `MBFunctionCall` records the supplied arguments `x` and `y`.
- `MBPythonVersion` captures the Python version.
- `MBHostInfo` captures `hostname` and `operating_system`.
- `MBSlurmInfo` captures all `SLURM_` environment variables (used by the
  [SLURM](https://slurm.schedmd.com/overview.html) cluster system).

Class variables:
- `outfile` saves results to a file (one JSON object per line).
- `capture_versions` records the versions of specified packages.
- `env_vars` captures environment variables as `env_<NAME>` fields — see [Environment variables](user-guide/configuration.md#environment-variables) for more.

Constructor arguments:
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

Or via `get_results()`, which works regardless of the output destination:

```python
results = bench.get_results()
```

## Analysing results

Load results into a pandas DataFrame and use its full range of aggregation
and filtering capabilities:

```python
import pandas

results = pandas.read_json('/home/user/my-benchmarks.jsonl', lines=True)

# run_durations is a list of per-iteration times; sum for total call time
results['total_duration'] = results['run_durations'].apply(sum)

# Average call time by Python version
results.groupby('python_version')['total_duration'].mean()

# Correlate records from the same process run
results.groupby('mb_run_id')['total_duration'].describe()
```

See the [pandas documentation](https://pandas.pydata.org/docs/) for more.

## Benchmarking external commands

Microbench can also wrap shell commands, scripts, and compiled executables
without writing any Python code. This is useful for SLURM jobs or any
workload where adding a Python decorator is not practical:

```bash
python -m microbench --outfile results.jsonl -- ./run_simulation.sh --steps 1000
```

Host information and SLURM environment variables are captured by default.
Use `--field KEY=VALUE` to attach labels and `--iterations N` to run the
command multiple times:

```bash
python -m microbench \
    --outfile results.jsonl \
    --field experiment=baseline \
    --iterations 5 \
    -- ./run_simulation.sh
```

See the [CLI reference](cli.md) for all options.
