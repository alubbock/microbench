# Extending microbench

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

### Custom capture methods

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

For more advanced extension patterns — custom JSON encoding, writing
reusable mixins, and tools for consuming benchmark output — see
[Advanced usage](advanced.md).
