# Output

## Saving to a file

Pass `outfile` as a constructor argument or set it as a class attribute:

```python
from microbench import MicroBench

# As a constructor argument
bench = MicroBench(outfile='/home/user/results.jsonl')

# Or as a class attribute
class MyBench(MicroBench):
    outfile = '/home/user/results.jsonl'
```

Results are written in [JSONL](https://jsonlines.org/) format (one JSON
object per line). When `outfile` is a path string, each write opens the
file with `O_APPEND`, which guarantees atomic appends on POSIX filesystems.
Multiple processes can safely write to the same file simultaneously — a
common pattern when running benchmark jobs across cluster nodes.

Read results back via `get_results()`:

```python
results = bench.get_results()              # list of dicts — no extra dependencies
results = bench.get_results(format='df')  # pandas DataFrame

# or read directly with pandas:
import pandas
results = pandas.read_json('/home/user/results.jsonl', lines=True)
```

Pass `flat=True` to flatten nested fields (e.g. `mb`, `call`, `slurm`, `git`,
`cgroups`) into dot-notation keys:

```python
results = bench.get_results(flat=True)
# {'call.name': 'noop', 'mb.run_id': '...', 'slurm.job_id': '12345', ...}
```

## Quick summary

Print min/mean/median/max/stdev of `call.durations` with no extra dependencies:

```python
bench.summary()
# n=10  min=0.000031  mean=0.000038  median=0.000036  max=0.000059  stdev=0.000008
```

The module-level `summary()` accepts any list of result dicts:

```python
from microbench import summary
summary(bench.get_results())
```

## In-memory buffer

If no `outfile` is specified, results are written to an in-memory
`io.StringIO` buffer. This is the default and is useful for interactive
sessions or testing:

```python
bench = MicroBench()

@bench
def my_function():
    pass

my_function()

results = bench.get_results()              # list of dicts
results = bench.get_results(format='df')  # pandas DataFrame
```

## Multiple output sinks

Pass an `outputs` list to write to several destinations simultaneously.
Each element must be an `Output` subclass instance. `outfile` and `outputs`
are mutually exclusive.

```python
from microbench import MicroBench, FileOutput, RedisOutput

bench = MicroBench(outputs=[
    FileOutput('/home/user/results.jsonl'),
    RedisOutput('microbench:mykey', host='redis-host', port=6379),
])
```

`get_results()` reads from the first sink that supports it. The `format` and
`flat` arguments work the same as with `FileOutput`.

## Redis output

[Redis](https://redis.io) is useful when a shared filesystem is not
available, such as on cloud or HPC clusters. Requires
[redis-py](https://github.com/andymccurdy/redis-py).

```python
from microbench import MicroBench, RedisOutput

bench = MicroBench(outputs=[
    RedisOutput('microbench:mykey', host='redis-host', port=6379)
])

@bench
def my_function():
    pass

my_function()

results = bench.get_results()              # list of dicts
results = bench.get_results(format='df')  # pandas DataFrame
```

Results are appended to a Redis list using `RPUSH` and read back with
`LRANGE`.

The CLI exposes the same sink via `--redis-output KEY` (see the [CLI reference](../cli.md#redis-output)).

## Custom output sinks

Subclass `Output` and implement `write` to send results anywhere:

```python
from microbench import MicroBench, Output

class MyOutput(Output):
    def write(self, bm_json_str):
        send_to_my_system(bm_json_str)

bench = MicroBench(outputs=[MyOutput()])
```
