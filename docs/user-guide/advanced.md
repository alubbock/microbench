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
