# Changelog

All notable changes to microbench are documented here.

## [1.1.0] - unreleased

### New features

- **`mb_run_id` and `mb_version` fields added to every record**: Both fields
  are included automatically without any configuration.
  - `mb_run_id` — UUID generated once at import time and shared by all
    `MicroBench` instances in the same process. Allows records from independent
    bench suites to be correlated with `groupby('mb_run_id')`.
  - `mb_version` — version of the `microbench` package that produced the
    record; essential for long-running studies where the benchmark code evolves.
