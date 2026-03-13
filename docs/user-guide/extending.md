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

For more advanced extension patterns — custom JSON encoding, writing
reusable mixins, and tools for consuming benchmark output — see
[Advanced usage](advanced.md).
