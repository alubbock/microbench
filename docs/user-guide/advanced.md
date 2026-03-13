# Advanced usage

## Tolerating capture failures

By default, an exception in any `capture_` or `capturepost_` method
propagates and aborts the benchmark call. Set `capture_optional = True` as
a class attribute to catch failures instead and record them in
`mb_capture_errors`:

```python
from microbench import MicroBench, MBNvidiaSmi, MBCondaPackages

class MyBench(MicroBench, MBNvidiaSmi, MBCondaPackages):
    capture_optional = True  # missing nvidia-smi or conda won't abort the run
```

When one or more captures fail, the record contains:

```json
{
  "mb_capture_errors": [
    {"method": "capture_nvidia", "error": "FileNotFoundError: [Errno 2] No such file or directory: 'nvidia-smi'"}
  ]
}
```

`mb_capture_errors` is absent from the record when all captures succeed,
keeping the happy-path output clean.

!!! tip "When to use `capture_optional`"
    Use it in production jobs running across heterogeneous cluster nodes
    where optional dependencies (e.g. `nvidia-smi`, `conda`) may not be
    present on every node. Leave it off during development so misconfigured
    captures surface immediately.

## Custom JSON encoding

Microbench serialises records as JSON. If a captured value is not
JSON-serialisable (e.g. a custom object), microbench replaces it with a
placeholder and emits a `JSONEncodeWarning`.

To handle custom types, subclass `JSONEncoder`:

```python
import microbench as mb
from igraph import Graph

class MyEncoder(mb.JSONEncoder):
    def default(self, o):
        if isinstance(o, Graph):
            return str(o)
        return super().default(o)

class MyBench(mb.MicroBench, mb.MBReturnValue):
    pass

bench = MyBench(json_encoder=MyEncoder)

@bench
def make_graph():
    return Graph(2, ((0, 1), (0, 2)))

make_graph()  # no warning
```

`JSONEncoder` already handles `datetime`, `timedelta`, `timezone`, and
numpy scalar/array types by default.

## Writing a mixin

A mixin is simply a class with one or more `capture_` or `capturepost_`
methods. Define it as a standalone class, then combine it with `MicroBench`
via multiple inheritance:

```python
class MBMachineType:
    """Capture the machine architecture (e.g. x86_64, arm64)."""

    def capture_machine_type(self, bm_data):
        import platform
        bm_data['machine_type'] = platform.machine()


class MyBench(MicroBench, MBMachineType, MBPythonVersion):
    pass
```

Mixins have no required base class. Python's **Method Resolution Order
(MRO)** determines the order in which base classes are searched for
methods — a deterministic left-to-right traversal that visits each class
exactly once. Because every `capture_` method has a unique name, all of
them are found and called regardless of MRO order. The MRO only matters if
two mixins define a method with the *same* name, in which case the
leftmost class in the inheritance list wins.

## Tailing output in real time

`LiveStream` tails a JSONL output file in a background thread and fires
`process_*` methods on each record as it arrives. It has two main use
cases:

**1. In-process monitoring** — react to results while a long job is still
running in the same Python process:

```python
from microbench.livestream import LiveStream

class MyStream(LiveStream):
    def process_alert(self, data):
        if sum(data['run_durations']) > 10.0:
            print(f"Slow call on {data.get('hostname')}: {data['run_durations']}")

stream = MyStream('/home/user/results.jsonl')
# ... runs in background while your job continues ...
stream.stop()
stream.join()
```

**2. Separate terminal** — run a watcher script in a second terminal while
your benchmark job writes to the file:

```python
# watch.py — run in a separate terminal: python watch.py
from microbench.livestream import LiveStream
import time

class Watcher(LiveStream):
    def filter(self, data):
        # Only show records from GPU nodes
        return 'gpu' in data.get('hostname', '')

    def display(self, data):
        print(f"{data['function_name']} | {data['hostname']} | {data['run_durations']}")

stream = Watcher('/home/user/results.jsonl')
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    stream.stop()
    stream.join()
```

The base class includes a `process_runtime` method that adds a `runtime`
field (finish_time − start_time) to each record before `display()` is
called. Override `display()` to change how records are shown, or `filter()`
to skip records selectively.

Requires [python-dateutil](https://pypi.org/project/python-dateutil/):
`pip install python-dateutil`.

## Comparing environments

`envdiff` produces a side-by-side visual diff of two records in a Jupyter
notebook, highlighting fields that differ. Useful for diagnosing why the
same code performs differently on two nodes.

Requires [IPython](https://ipython.org/): `pip install ipython`.

```python
from microbench.diff import envdiff
import pandas

results = pandas.read_json('/home/user/results.jsonl', lines=True)

# Compare the environment of the slowest and fastest calls
slowest = results.loc[results['run_durations'].apply(sum).idxmax()]
fastest = results.loc[results['run_durations'].apply(sum).idxmin()]

envdiff(slowest, fastest)
```

Differences are highlighted in red in the rendered output.
