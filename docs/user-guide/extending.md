# Extending microbench

## Custom capture methods

Add methods prefixed with `capture_` to run before the function starts, or
`capturepost_` to run after it returns. Each receives `bm_data`, the
dictionary that will be serialised as the result record.

```python
from microbench import MicroBench
import platform

class MyBench(MicroBench):
    def capture_machine_type(self, bm_data):
        bm_data['machine'] = platform.machine()  # e.g. 'x86_64'

    def capturepost_slow_call(self, bm_data):
        # run_durations and finish_time are available in capturepost_ methods
        if sum(bm_data['run_durations']) > 1.0:
            bm_data['slow_call'] = True
```

Avoid key names that clash with built-in fields (e.g. `start_time`,
`function_name`). The `mb_` prefix is reserved for microbench internals.

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
methods. Define it as a standalone class, then include it in benchmark suite
definitions via multiple inheritance:

```python
class MBMachineType:
    """Capture the machine architecture (e.g. x86_64, arm64)."""

    def capture_machine_type(self, bm_data):
        import platform
        bm_data['machine_type'] = platform.machine()


class MyBench(MicroBench, MBMachineType, MBPythonVersion):
    pass
```

Mixins have no required base class — they rely entirely on Python's MRO.
