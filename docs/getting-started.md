# Getting started

## CLI quick start

The fastest way to use microbench is from the command line. Wrap any command
and capture timing and host metadata with no code changes:

```bash
microbench --outfile results.jsonl -- ./run_simulation.sh --steps 1000
```

Host information and SLURM environment variables are captured by default.
Use `--field KEY=VALUE` to attach labels and `--iterations N` to run the
command multiple times:

```bash
microbench \
    --outfile results.jsonl \
    --field experiment=baseline \
    --iterations 5 \
    -- ./run_simulation.sh
```

Add `--monitor-interval` to sample CPU and RSS memory over time (requires
`psutil`):

```bash
microbench --outfile results.jsonl --monitor-interval 30 -- python train_model.py
```

See the [CLI reference](cli.md) for all options and `microbench --show-mixins`
to list all available metadata mixins.

---

## Python API quick start

### Minimal example

Decorate the function you want to benchmark and call it normally:

```python
from microbench import MicroBench

bench = MicroBench()

@bench
def my_function(x):
    return x ** 2

my_function(42)
```

By default results are captured into an in-memory buffer. Read them back as
a list of dicts:

```python
results = bench.get_results()          # list of dicts — no extra dependencies
results = bench.get_results(format='df')  # pandas DataFrame
```

Or print a quick stats summary without any dependencies:

```python
bench.summary()
# n=1  min=0.000042  mean=0.000042  median=0.000042  max=0.000042  stdev=nan
```

Every record contains these fields automatically (all nested under `mb` or `call`):

| Field | Description |
|---|---|
| `mb.run_id` | UUID generated once when `microbench` is imported. Identical across all bench suites in the same process — use `groupby('mb.run_id')` to correlate records from different benchmarks in the same run. |
| `mb.version` | Version of the `microbench` package that produced the record. |
| `mb.timezone` | Timezone used for `call.start_time`/`call.finish_time`. |
| `mb.duration_counter` | Name of the timer function used for `call.durations`. |
| `call.invocation` | `'Python'` for the Python API, `'CLI'` for the command-line interface. |
| `call.name` | Name of the decorated function (or the name passed to `bench.record()`). |
| `call.start_time` | ISO-8601 timestamp when the function was called (UTC by default). |
| `call.finish_time` | ISO-8601 timestamp when the function returned. |
| `call.durations` | List of per-iteration durations in seconds. |

### Extended example

Here's an extended example to give you an idea of real-world usage.

```python
from microbench import MicroBench, MBFunctionCall, \
    MBHostInfo, MBSlurmInfo
import numpy, pandas, time

class MyBench(MicroBench, MBFunctionCall, MBHostInfo, MBSlurmInfo):
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
- `MBHostInfo` captures `host.hostname` and `host.os`.
- `MBSlurmInfo` captures all `SLURM_*` environment variables (used by the
  [SLURM](https://slurm.schedmd.com/overview.html) cluster system).

Note: `MBPythonInfo` is already included in `MicroBench` by default — there is
no need to list it explicitly in the class definition.

Class variables:
- `outfile` saves results to a file (one JSON object per line).
- `capture_versions` records the versions of specified packages.
- `env_vars` captures environment variables as `env.<NAME>` fields — see [Environment variables](user-guide/configuration.md#environment-variables) for more.

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
results = bench.get_results()              # list of dicts — no extra dependencies
results = bench.get_results(format='df')  # pandas DataFrame
```

## Analysing results

For a quick stats overview with no extra dependencies:

```python
bench.summary()
# n=3  min=0.049512  mean=0.049821  median=0.049823  max=0.050128  stdev=0.000312

# or pass any list of result dicts:
from microbench import summary
summary(bench.get_results())
```

Load into a pandas DataFrame for full aggregation and filtering:

```python
results = bench.get_results(format='df', flat=True)

# call.durations is a list of per-iteration times; sum for total call time
results['total_duration'] = results['call.durations'].apply(sum)

# Average call time by Python version
results.groupby('python.version')['total_duration'].mean()

# Correlate records from the same process run
results.groupby('mb.run_id')['total_duration'].describe()
```

Use `flat=True` to flatten nested fields (e.g. `slurm`, `git`,
`cgroups`, `call`, `mb`) into dot-notation columns — useful when loading
into pandas or a spreadsheet:

```python
results = bench.get_results(flat=True)          # list of flat dicts
results = bench.get_results(format='df', flat=True)  # flat DataFrame
# 'call' dict becomes: call.name, call.durations, call.start_time, ...
# 'slurm' dict becomes: slurm.job_id, slurm.cpus_on_node, ...
```

See the [pandas documentation](https://pandas.pydata.org/docs/) for more.

## Timing code blocks

Use `bench.record(name)` when the code you want to time is not easily
wrapped in a function — for example, a block in a notebook cell or a
section of a script:

```python
from microbench import MicroBench, MBHostInfo

class MyBench(MicroBench, MBHostInfo):
    outfile = '/home/user/results.jsonl'

bench = MyBench(experiment='run-1')

with bench.record('data_loading'):
    dataset = load_dataset('/data/train.h5')

with bench.record('preprocessing'):
    X, y = preprocess(dataset)
```

Each `with` block produces one record. The `name` argument sets the
`call.name` field. All mixins, static fields, and output sinks
behave identically to the decorator form.

If the block raises an exception the record is still written, with an
`exception` field containing the error type and message, and the
exception is re-raised normally:

```python
try:
    with bench.record('risky_step'):
        result = unstable_solver(data)
except SolverError:
    pass  # record written with exception field; continue to next step
```

**Mixin compatibility notes:**

- `MBFunctionCall` — records `args=[]` and `kwargs={}` (no callable to inspect); not an error, but not meaningful.
- `MBReturnValue` — silently a no-op; no `return_value` field is set.
- `MBLineProfiler` — raises `NotImplementedError`; it requires a callable to profile and cannot be used with `bench.record()`. Use the `@bench` decorator instead.

## Timing entire scripts with `record_on_exit`

Call `bench.record_on_exit(name)` once near the top of a script to time
the full process lifetime. The record is written automatically when the
process exits — no restructuring of the script is required:

```python
from microbench import MicroBench, MBHostInfo, MBSlurmInfo

class MyBench(MicroBench, MBHostInfo, MBSlurmInfo):
    outfile = '/scratch/results.jsonl'
    capture_optional = True  # recommended: don't let a failed capture abort exit

bench = MyBench(experiment='baseline')
bench.record_on_exit('simulation')

run_simulation()  # whatever the script does
```

A single record is appended to `results.jsonl` when the process exits,
containing the wall-clock duration from the `record_on_exit()` call to
exit plus all mixin fields captured at exit time.

**SIGTERM handling (SLURM walltime):** By default microbench installs a
SIGTERM handler. When SLURM hits the job's walltime limit it sends SIGTERM
(with a grace period before SIGKILL); the handler writes the record before
re-delivering the signal so job accounting sees the correct exit code.
Pass `handle_sigterm=False` to opt out.

**Exception capture:** If the script exits due to an unhandled exception,
the record includes an `exception` field with the error type and message.
The exception is still printed and the process still exits non-zero.

**Limitations:** SIGKILL and `os._exit()` cannot be caught; no record
will be written in those cases.
