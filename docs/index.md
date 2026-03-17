# microbench

![Microbench: Benchmarking and reproducibility metadata capture for Python](https://raw.githubusercontent.com/alubbock/microbench/master/microbench.png)

Running the same script on a laptop, cloud VM, or cluster can produce
different results. Maybe some nodes have twice the RAM, or you're running
a different git commit without realising it.

Microbench records the context alongside your timings: Python version,
package versions, hostname, hardware, environment variables, git commit,
and more. When performance varies, the metadata tells you why. When you
need to reproduce a result, it shows exactly what was running.

## Two ways to use it

**CLI** — wrap any command with a single line, no code changes required:

```bash
microbench --outfile results.jsonl -- ./run_simulation.sh --steps 1000
```

**Python API** — decorate functions or wrap code blocks for richer capture:

```python
from microbench import MicroBench

bench = MicroBench(outfile='results.jsonl')

@bench
def my_function(n):
    return sum(range(n))

my_function(1_000_000)
```

Both modes produce JSONL records like this:

```json
{
  "mb":   { "run_id": "8a3d213a...", "version": "2.0.0", "timezone": "UTC" },
  "call": { "name": "my_function", "durations": [0.0498], "start_time": "..." },
  "python": { "version": "3.13.1", "prefix": "/opt/conda/envs/myenv", ... },
  "host": { "hostname": "cluster-node-04", "os": "linux", "ram_total": 137438953472, ... },
  "slurm": { "job_id": "12345", "cpus_on_node": "16", ... }
}
```

→ [Getting started](getting-started.md) for a full walkthrough.  
→ [CLI reference](cli.md) for all command-line options.

## Key features

- **CLI and Python API** — wrap any script or decorate any function; both
  produce the same JSONL format
- **Captures what matters** — Python version, hostname, CPU/RAM, SLURM
  variables, conda/pip packages, NVIDIA GPU info, git commit, file hashes,
  and more, via composable _mixins_
- **Cluster and HPC ready** — captures SLURM environment variables; safe for
  concurrent writes from many nodes via `O_APPEND`; `mb.run_id` correlates
  records across independent bench suites in the same process
- **Flexible output** — JSONL file, in-memory buffer, Redis, or HTTP endpoint;
  load results directly into pandas with `read_json(..., lines=True)`
- **Python API extras** — sub-timings (`bench.time()`), context managers
  (`bench.record()`), `record_on_exit()` for full-script timing, async
  support, line-level profiling
- **No mandatory dependencies** — works with the standard library alone;
  optional extras unlock pandas, psutil, Redis, and line profiling

## Installation

Requires Python 3.10+.

```
pip install microbench
```

## Requirements

Some mixins have optional requirements:

| Mixin / feature | Requires |
|---|---|
| `MBHostInfo` (CPU/RAM fields), `--monitor-interval` | [psutil](https://pypi.org/project/psutil/) |
| `MBLineProfiler` | [line_profiler](https://github.com/rkern/line_profiler) |
| `MBNvidiaSmi` | `nvidia-smi` on `PATH` (ships with NVIDIA drivers) |
| `MBCondaPackages` | `conda` on `PATH` |
| `RedisOutput` | [redis-py](https://github.com/andymccurdy/redis-py) (`pip install microbench[redis]`) |
| `HttpOutput` | no extra dependencies (uses stdlib `urllib`) |

See [Getting started](getting-started.md) to dive in.
