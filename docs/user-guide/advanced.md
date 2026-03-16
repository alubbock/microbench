# Advanced usage

## `bench.record_on_exit()` — reliability and signal handling

`bench.record_on_exit()` is designed to work reliably in long-running batch
jobs. This section covers the implementation details that matter for
production use.

### What is and isn't caught

| Exit path | Record written? |
|---|---|
| Normal script completion | ✓ |
| `sys.exit()` | ✓ |
| Unhandled exception | ✓ (with `exception` field) |
| `KeyboardInterrupt` (Ctrl-C) | ✓ (with `exception` field) |
| SIGTERM (default `handle_sigterm=True`) | ✓ (with `exit_signal='SIGTERM'`) |
| SIGKILL | ✗ — unkillable by design |
| `os._exit()` | ✗ — bypasses atexit |

### SIGTERM and signal chaining

When `handle_sigterm=True`, microbench installs a SIGTERM handler that:

1. Writes the record
2. Chains to any previously installed SIGTERM handler
3. Restores the default OS signal disposition (`SIG_DFL`) and re-delivers
   SIGTERM to the process

Step 3 is important for correct job accounting. When Python intercepts a
signal, the process does not automatically exit with the signal's conventional
exit code. By restoring the default disposition and then re-sending the signal,
the process terminates as if Python had never handled it — with exit code 143.
This number follows the Unix convention of 128 + signal number: SIGTERM is
signal 15, so 128 + 15 = 143. SLURM and other schedulers use this exit code
to distinguish a walltime kill from a normal non-zero exit.

Signal handlers can only be registered from the main thread. If
`record_on_exit()` is called from a non-main thread, microbench warns and
proceeds without the SIGTERM handler; the record will still be written on
normal exit.

### Capture failures at exit time

Mixin captures run inside the exit handler. Slow or unavailable captures
(e.g. `MBCondaPackages` when conda is not installed) can delay exit, which
matters when operating inside a SLURM grace period. Use
`capture_optional = True` on the benchmark class so individual capture
failures are recorded in `mb_capture_errors` rather than aborting the
handler:

```python
class MyBench(MicroBench, MBHostInfo, MBCondaPackages):
    capture_optional = True
```

### Output sink unavailability

If the primary output sink raises (e.g. a shared filesystem that has been
unmounted before the atexit handler fires), microbench falls back to
writing the raw JSON record to `sys.stderr` so the record is not silently
lost.

## Sub-timings: `bench.time()`

When a benchmarked block contains several distinct phases, `bench.time(name)`
lets you label each one. All phases share the same benchmark record — and
therefore the same metadata capture pass. There is no need to create a separate
`MicroBench` instance per phase.

```python
with bench.record('pipeline'):
    with bench.time('parse'):
        data = parse(raw)
    with bench.time('transform'):
        result = transform(data)
    with bench.time('write'):
        write(result)
```

Sub-timings are appended to `mb_timings` in call order:

```json
{
  "function_name": "pipeline",
  "run_durations": [0.183],
  "mb_timings": [
    {"name": "parse",     "duration": 0.041},
    {"name": "transform", "duration": 0.120},
    {"name": "write",     "duration": 0.022}
  ]
}
```

`mb_timings` is absent from the record when `bench.time()` is never called.

### Compatibility

`bench.time()` works identically inside all four entry points:

| Entry point | Usage |
|---|---|
| `bench.record()` | `with bench.record('name'): ... with bench.time('phase'): ...` |
| `@bench` decorator (sync) | call `bench.time()` inside the decorated function body |
| `@bench` decorator (async) | same — use `with bench.time()` (not `async with`) |
| `bench.arecord()` | `async with bench.arecord('name'): ... with bench.time('phase'): ...` |
| `bench.record_on_exit()` | call `bench.time()` anywhere after `record_on_exit()` returns |

Calling `bench.time()` outside any active benchmark is a **silent no-op** — it
records nothing and raises no error.

### Behaviour with `iterations`

With `iterations=N`, each call to the decorated function runs `N` times. Every
`bench.time()` inside the body fires once per iteration, so `mb_timings` will
contain `N` entries per named phase:

```python
bench = MicroBench(iterations=3)

@bench
def pipeline():
    with bench.time('step'):
        ...

pipeline()
# mb_timings → [{"name": "step", ...}, {"name": "step", ...}, {"name": "step", ...}]
```

### Exceptions

An exception raised inside `with bench.time('phase')` closes the segment and
records its duration before the exception propagates. The record will contain
the partial `mb_timings` for all segments that completed or started before the
exception.

## Exception capture

When a benchmarked block raises an exception — whether via `bench.record()`
or a `@bench`-decorated function — microbench writes the record before
propagating the exception. The record includes an `exception` field with
the error type and message:

```json
{
  "function_name": "risky_step",
  "run_durations": [0.042],
  "exception": {"type": "SolverError", "message": "convergence failed"}
}
```

The exception is always re-raised — microbench never silences errors.
Failing calls still appear in your results file and can be identified in
analysis:

```python
import pandas
results = pandas.read_json('/home/user/results.jsonl', lines=True)

# Records where the call raised
failed = results[results['exception'].notna()]
```

With `--iterations N`, timing stops at the first exception; the record
contains durations for all iterations up to and including the failing one.

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

### Making a mixin CLI-compatible

A mixin with `cli_compatible = True` appears in `--show-mixins` and can be
selected with `--mixin`. That attribute alone is enough for mixins that need
no configuration:

```python
class MBMachineType:
    """Capture the machine architecture (e.g. x86_64, arm64)."""

    cli_compatible = True

    def capture_machine_type(self, bm_data):
        import platform
        bm_data['machine_type'] = platform.machine()
```

To expose configurable attributes as CLI flags, add a `cli_args` list of
`CLIArg` instances. The CLI picks them up automatically — no changes to
`__main__.py` are needed:

```python
from microbench.mixins import CLIArg, _UNSET

class MBOutputDir:
    """Record the output directory for this run."""

    cli_compatible = True
    cli_args = [
        CLIArg(
            flags=['--output-dir'],
            dest='output_dir',
            metavar='DIR',
            help='Output directory to record. CLI default: current working directory.',
            cli_default=lambda cmd: os.getcwd(),
        ),
    ]

    def capture_output_dir(self, bm_data):
        bm_data['output_dir'] = getattr(self, 'output_dir', None)
```

`CLIArg` parameters:

| Parameter | Description |
|---|---|
| `flags` | Flag strings, e.g. `['--output-dir']`. |
| `dest` | Mixin attribute name to set, e.g. `'output_dir'`. |
| `help` | Help text shown in `--help` and `--show-mixins`. |
| `metavar` | Display name for the value in help (e.g. `'DIR'`). |
| `type` | Callable to convert and validate the raw string. Defaults to `str`. Raise `ValueError` to reject a value. |
| `nargs` | Number of arguments, e.g. `'+'` for one or more. |
| `cli_default` | Default when the flag is not supplied on the CLI. A callable receives the command list (`cmd`) and returns the default value. Use `_UNSET` (the default) to fall back to the mixin's own Python-API default logic instead. |

If a `cli_default` differs from the Python API default — for example because
`sys.argv[0]` points to a different file in CLI context — document both
defaults in the `help` string and in the mixin's docstring.

Mixin flags are only accepted when their mixin is active. Passing a flag
without `--mixin <name>` (or `--all`) is an error.

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
