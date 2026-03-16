# Command-line interface

Microbench can wrap any external command and record host metadata
alongside timing, without writing any Python code:

```bash
microbench --outfile results.jsonl -- ./run_simulation.sh
```

This is particularly useful for SLURM jobs, shell scripts, or compiled
executables where adding a Python decorator is not practical.

`python -m microbench` is equivalent and can be used when you need to
select a specific Python interpreter explicitly.

## Usage

```
microbench [options] -- COMMAND [ARGS...]
```

| Option | Description |
|---|---|
| `--outfile FILE` / `-o FILE` | Append results to FILE in JSONL format. Defaults to stdout. |
| `--mixin MIXIN [MIXIN ...]` / `-m MIXIN [MIXIN ...]` | One or more mixins to include. Replaces defaults when specified. |
| `--show-mixins` | List all available mixins with descriptions and exit. |
| `--all` / `-a` | Include all available mixins. |
| `--no-mixin` | Disable all mixins including defaults. Records only timing and command fields. |
| `--iterations N` / `-n N` | Run the command N times, recording each duration. Defaults to 1. |
| `--warmup N` / `-w N` | Run the command N times before timing begins (unrecorded). Defaults to 0. |
| `--stdout[=suppress]` | Capture stdout into the record and stream it to the terminal in real time. Use `=suppress` to capture without printing. |
| `--stderr[=suppress]` | Capture stderr into the record and stream it to the terminal in real time. Use `=suppress` to capture without printing. |
| `--timeout SECONDS` | Send SIGTERM to the command after SECONDS seconds per iteration. If the process has not exited after an additional grace period (default 5 s, see `--timeout-grace-period`), send SIGKILL. Timed-out iterations are recorded with `call.timed_out = true`. |
| `--timeout-grace-period SECONDS` | Seconds to wait after SIGTERM before sending SIGKILL. Only relevant when `--timeout` is set. Default: 5. |
| `--monitor-interval SECONDS` | Sample the child process CPU usage and RSS memory every SECONDS seconds. Requires `psutil`. See [Subprocess monitoring](#subprocess-monitoring) below. |
| `--field KEY=VALUE` / `-f KEY=VALUE` | Extra metadata field. Can be repeated. |

Use `--` to separate microbench options from the command being benchmarked.

## Fields recorded

Every record contains the standard `mb.*` and `call.*` fields plus:

| Field | Description |
|---|---|
| `call.invocation` | Always `'CLI'` for records produced by the CLI. |
| `call.name` | Basename of the executable, e.g. `"run_sim.sh"`. |
| `call.command` | Full command as a list, e.g. `["./run_sim.sh", "--steps", "1000"]`. |
| `call.returncode` | List of exit codes, one per timed iteration (warmup excluded). The process exits with the highest value. |
| `call.timed_out` | *(present only when `--timeout` fires)* `true` when at least one timed iteration was killed due to the timeout. Absent on normal completion. |
| `call.monitor` | *(present only with `--monitor-interval`)* List of per-iteration sample lists. See [Subprocess monitoring](#subprocess-monitoring). |

## Default mixins

When no `--mixin` is specified, `python-info`, `host-info`, `slurm-info`,
`loaded-modules`, and `working-dir` are included automatically, capturing
the Python interpreter version, prefix, and executable path; hostname and
operating system; all `SLURM_*` environment variables; the loaded
Lmod/Environment Modules software stack; and the current working directory.
All five degrade gracefully or produce stable values outside their respective
environments.

Mixin names use a short kebab-case form without the `MB` prefix
(e.g. `host-info` instead of `MBHostInfo`). MB-prefixed names are also
accepted for convenience. Run `--show-mixins` to list all available
mixins with descriptions:

```bash
microbench --show-mixins
```

Specifying `--mixin` replaces the defaults entirely. Use `--no-mixin` to
disable all mixins and record only timing and command fields:

```bash
# Only Python info — no host info or SLURM
microbench --mixin python-info -- ./job.sh

# No mixins at all — timing and command only
microbench --no-mixin -- ./job.sh
```

!!! note "Python-environment mixins"
    `python-info` and `installed-packages` capture the **microbench
    process's** Python interpreter. In typical usage (microbench installed
    in the same environment as the benchmarked code) this is exactly what
    you want. If you need to target a different interpreter, invoke
    microbench via it: `python -m microbench --mixin python-info -- ./job.sh`.

    `conda-packages` queries the environment identified by `CONDA_PREFIX`
    (the shell's active conda environment), not `sys.prefix`, so it
    captures the correct environment even when microbench's Python lives
    elsewhere (e.g. in base). Package versions are stored under
    `conda.packages` alongside `conda.name` and `conda.path`.

See [Mixins](user-guide/mixins.md) for details on each.

## Mixin options

Some mixins expose their own CLI flags for configuration. These are shown
under each mixin in `--show-mixins` output and in `--help`. A mixin flag
may only be used when its mixin is loaded; passing one without the
corresponding mixin is an error.

### `git-info` options

| Option | Description |
|---|---|
| `--git-repo DIR` | Directory to inspect for git information. |

**CLI default:** current working directory.

**Python API default:** directory of the running script (`sys.argv[0]`).
When using the CLI, `sys.argv[0]` points to the microbench package itself,
so the CLI defaults to the working directory instead.

### `file-hash` options

| Option | Description |
|---|---|
| `--hash-file FILE [FILE ...]` | File(s) to hash. |
| `--hash-algorithm ALGORITHM` | Hash algorithm (e.g. `sha256`, `md5`). Default: `sha256`. |

**CLI default for `--hash-file`:** the benchmarked command executable
(`cmd[0]`), e.g. `./run_simulation.sh`.

**Python API default:** the running script (`sys.argv[0]`). The same
`sys.argv[0]` issue applies here, so the CLI defaults to hashing the
command being benchmarked instead.

## Capture failures

Metadata capture failures (e.g. `nvidia-smi` not installed on this node,
script not in a git repository) are caught automatically and recorded in
`call.capture_errors` rather than aborting the run. This makes the CLI safe
to use across heterogeneous cluster nodes.

## SLURM example

A typical SLURM job script:

```bash
#!/bin/bash
#SBATCH --job-name=my-sim
#SBATCH --output=slurm-%j.out

microbench \
    --outfile /scratch/$USER/results.jsonl \
    --mixin host-info slurm-info \
    --field experiment=baseline \
    -- ./run_simulation.sh --steps 10000
```

Each node that runs this job appends one JSONL record to `results.jsonl`,
capturing hostname, OS, CPU count, RAM, and all SLURM variables (job ID, array
task ID, node list, etc.) alongside the wall-clock time of the simulation.
CPU and RAM fields are included automatically by `host-info` when psutil is
installed.

Read the results with pandas:

```python
import pandas
results = pandas.read_json('/scratch/user/results.jsonl', lines=True)
results = results.apply(lambda r: pandas.Series(r), axis=1)  # flatten if needed
# Or use get_results(flat=True) when reading via microbench:
from microbench import FileOutput
flat = FileOutput('/scratch/user/results.jsonl').get_results(flat=True)
import pandas
df = pandas.DataFrame(flat)
df['total_duration'] = df['call.durations'].apply(sum)
df.groupby('slurm.job_id')['total_duration'].describe()
```

## Repeated runs

Use `--iterations` to run the command multiple times within a single record.
This is useful when the command is short-lived and you want to amortise
per-record overhead or reduce timing noise:

```bash
microbench --iterations 10 --warmup 2 -- ./run_simulation.sh
```

With 10 iterations and 2 warmup runs, the record contains:

- `call.durations` — list of 10 wall-clock durations in seconds
- `call.returncode` — list of 10 exit codes (one per timed iteration)
- `call.stdout` / `call.stderr` — list of 10 captured strings, if `--stdout`/`--stderr` is used

Warmup runs are excluded from all three lists. The process exits with
`max(returncode)` so any failing iteration propagates to the shell.

!!! note "Subprocess-side buffering"
    When stdout or stderr is captured via a pipe, many programs switch from
    line-buffered to block-buffered mode because they detect they are not
    writing to a TTY. Output will still stream to the terminal in real time
    from microbench's perspective, but the subprocess itself may batch writes
    into larger chunks. Use `stdbuf -oL` (Linux) or the program's own
    unbuffering flag (e.g. `python -u`) if you need per-line flushing:

    ```bash
    microbench --stdout -- stdbuf -oL ./run_simulation.sh
    ```

To detect failed iterations when analysing results with pandas (using `flat=True`):

```python
df['any_failed'] = df['call.returncode'].apply(lambda rc: max(rc) != 0)
```

## Timeout

Use `--timeout SECONDS` to limit how long each iteration is allowed to run:

```bash
microbench --timeout 120 -- ./run_simulation.sh
```

After `SECONDS` seconds, microbench sends **SIGTERM** to the process. If the
process has not exited after an additional grace period (default 5 s), **SIGKILL**
is sent. The SIGTERM window gives well-behaved processes a chance to flush output
and write partial results before being force-killed. Use `--timeout-grace-period`
to adjust the gap between SIGTERM and SIGKILL:

```bash
microbench --timeout 120 --timeout-grace-period 30 -- ./run_simulation.sh
```

The record is always written, even for timed-out iterations. Detect timeouts in
analysis with:

```python
df['any_timed_out'] = df['call.timed_out'].notna()
```

The `call.returncode` for a SIGTERM-killed process will be `-15`; for SIGKILL, `-9`.

## Extra metadata

Use `--field` to attach experiment labels or other fixed values:

```bash
microbench \
    --outfile results.jsonl \
    --field experiment=ablation-1 \
    --field dataset=large \
    -- python train.py
```

All `--field` values are stored as strings.

## Subprocess monitoring

Use `--monitor-interval SECONDS` to periodically sample the child process
while it runs. This requires the [`psutil`](https://psutil.readthedocs.io/)
package (`pip install psutil`).

```bash
microbench \
    --outfile results.jsonl \
    --monitor-interval 5 \
    -- ./run_simulation.sh --steps 10000
```

The record gains a `call.monitor` field: a list of per-iteration
sample lists (one inner list per `--iterations` call, warmup excluded).
Each sample is a dict with three keys:

| Key | Description |
|---|---|
| `timestamp` | ISO 8601 UTC timestamp of the sample. |
| `cpu_percent` | CPU usage of the child process as a percentage (0–100 per core, so values above 100 are possible on multi-core machines). The first sample is always `0.0` — this is a psutil limitation where two successive calls are needed to compute a ratio. |
| `rss_bytes` | Resident set size (physical RAM) of the child process in bytes. |

Example record (single iteration, two samples):

```json
{
  "call": {
    "monitor": [
      [
        {"timestamp": "2025-01-01T12:00:05Z", "cpu_percent": 0.0,  "rss_bytes": 52428800},
        {"timestamp": "2025-01-01T12:00:10Z", "cpu_percent": 87.3, "rss_bytes": 61865984}
      ]
    ]
  }
}
```

Only the direct child process is tracked. If the child spawns its own
subprocesses, their CPU and memory usage are not included.

If the process exits before the first sample interval fires (e.g. a very
short-lived command with a long `--monitor-interval`), the inner list will
be empty and `call.monitor` is omitted from the record.

Analyse with `get_results()`:

```python
from microbench import FileOutput
results = FileOutput('results.jsonl').get_results()

# Flatten all samples for the first iteration across all records
import pandas
samples = pandas.DataFrame([
    s
    for r in results
    for s in r['call']['monitor'][0]   # [0] = first iteration
])
samples['rss_mb'] = samples['rss_bytes'] / 1024 / 1024
print(samples[['timestamp', 'cpu_percent', 'rss_mb']])
```
