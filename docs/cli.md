# Command-line interface

Microbench can wrap any external command and record host metadata
alongside timing, without writing any Python code:

```bash
python -m microbench --outfile results.jsonl -- ./run_simulation.sh
```

This is particularly useful for SLURM jobs, shell scripts, or compiled
executables where adding a Python decorator is not practical.

## Usage

```
python -m microbench [options] -- COMMAND [ARGS...]
```

| Option | Description |
|---|---|
| `--outfile FILE` / `-o FILE` | Append results to FILE in JSONL format. Defaults to stdout. |
| `--mixin MIXIN` / `-m MIXIN` | Mixin to include. Replaces defaults when specified. Can be repeated. |
| `--all` / `-a` | Include all available mixins. |
| `--no-mixin` | Disable all mixins including defaults. Records only timing and command fields. |
| `--iterations N` / `-n N` | Run the command N times, recording each duration. Defaults to 1. |
| `--warmup N` / `-w N` | Run the command N times before timing begins (unrecorded). Defaults to 0. |
| `--stdout[=suppress]` | Capture stdout into the record. Output is still shown on the terminal unless `=suppress` is given. |
| `--stderr[=suppress]` | Capture stderr into the record. Output is still shown on the terminal unless `=suppress` is given. |
| `--field KEY=VALUE` / `-f KEY=VALUE` | Extra metadata field. Can be repeated. |

Use `--` to separate microbench options from the command being benchmarked.

## Fields recorded

Every record contains the standard fields (`start_time`, `finish_time`,
`run_durations`, etc.) plus:

| Field | Description |
|---|---|
| `command` | Full command as a list, e.g. `["./run_sim.sh", "--steps", "1000"]`. |
| `returncode` | List of exit codes, one per timed iteration (warmup excluded). The process exits with the highest value. |
| `function_name` | Basename of the executable, e.g. `"run_sim.sh"`. |

## Default mixins

When no `--mixin` is specified, `MBHostInfo`, `MBSlurmInfo`, and
`MBLoadedModules` are included automatically, capturing hostname,
operating system, all `SLURM_*` environment variables, and the loaded
Lmod/Environment Modules software stack. All three degrade gracefully
to empty dicts outside of their respective environments.

Specifying `--mixin` replaces the defaults entirely. Use `--no-mixin` to
disable all mixins and record only timing and command fields:

```bash
# Only Python version — no host info or SLURM
python -m microbench --mixin MBPythonVersion -- ./job.sh

# No mixins at all — timing and command only
python -m microbench --no-mixin -- ./job.sh
```

Available mixins (those marked `cli_compatible`):
`MBCondaPackages`, `MBFileHash`, `MBGitInfo`, `MBHostCpuCores`,
`MBHostInfo`, `MBHostRamTotal`, `MBInstalledPackages`, `MBLoadedModules`,
`MBNvidiaSmi`, `MBPythonVersion`, `MBSlurmInfo`.

See [Mixins](user-guide/mixins.md) for details on each.

## Capture failures

Metadata capture failures (e.g. `nvidia-smi` not installed on this node,
script not in a git repository) are caught automatically and recorded in
`mb_capture_errors` rather than aborting the run. This makes the CLI safe
to use across heterogeneous cluster nodes.

## SLURM example

A typical SLURM job script:

```bash
#!/bin/bash
#SBATCH --job-name=my-sim
#SBATCH --output=slurm-%j.out

python -m microbench \
    --outfile /scratch/$USER/results.jsonl \
    --mixin MBHostInfo \
    --mixin MBSlurmInfo \
    --mixin MBHostCpuCores \
    --field experiment=baseline \
    -- ./run_simulation.sh --steps 10000
```

Each node that runs this job appends one JSONL record to `results.jsonl`,
capturing hostname, CPU count, and all SLURM variables (job ID, array task
ID, node list, etc.) alongside the wall-clock time of the simulation.

Read the results with pandas:

```python
import pandas
results = pandas.read_json('/scratch/user/results.jsonl', lines=True)
results['total_duration'] = results['run_durations'].apply(sum)
results.groupby('slurm.job_id')['total_duration'].describe()
```

## Repeated runs

Use `--iterations` to run the command multiple times within a single record.
This is useful when the command is short-lived and you want to amortise
per-record overhead or reduce timing noise:

```bash
python -m microbench --iterations 10 --warmup 2 -- ./run_simulation.sh
```

With 10 iterations and 2 warmup runs, the record contains:

- `run_durations` — list of 10 wall-clock durations in seconds
- `returncode` — list of 10 exit codes (one per timed iteration)
- `stdout` / `stderr` — list of 10 captured strings, if `--stdout`/`--stderr` is used

Warmup runs are excluded from all three lists. The process exits with
`max(returncode)` so any failing iteration propagates to the shell.

To detect failed iterations when analysing results with pandas:

```python
results['any_failed'] = results['returncode'].apply(lambda rc: max(rc) != 0)
```

## Extra metadata

Use `--field` to attach experiment labels or other fixed values:

```bash
python -m microbench \
    --outfile results.jsonl \
    --field experiment=ablation-1 \
    --field dataset=large \
    -- python train.py
```

All `--field` values are stored as strings.
