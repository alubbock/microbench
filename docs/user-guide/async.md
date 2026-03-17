# Async functions

Microbench supports `async def` functions natively. The `@bench` decorator
detects coroutine functions automatically and returns an `async def` wrapper
that must be awaited. A companion `bench.arecord()` method provides an async
context manager equivalent to `bench.record()`.

## Decorating an async function

```python
import asyncio
from microbench import MicroBench

bench = MicroBench()

@bench
async def fetch_data(url):
    # e.g. await httpx.AsyncClient().get(url)
    await asyncio.sleep(0.01)
    return {'rows': 42}

asyncio.run(fetch_data('https://example.com/api'))
print(bench.get_results(format='df', flat=True)[['call.name', 'call.start_time', 'call.durations']])
```

The wrapper is a true `async def`, so you can `await` it, pass it to
`asyncio.gather`, or use it inside any async framework.

`iterations`, `warmup`, mixins, static fields, and output sinks all behave
identically to the synchronous decorator.

## Async context manager — `bench.arecord()`

Use `bench.arecord()` to time an async block without wrapping it in a named
function:

```python
import asyncio
from microbench import MicroBench

bench = MicroBench()

async def main():
    async with bench.arecord('data_load'):
        await asyncio.sleep(0.01)

asyncio.run(main())
print(bench.get_results())
```

This is the async counterpart of `bench.record()`. All mixins and output
sinks work identically. The `call.name` field defaults to `'<record>'`
when no name is given.

## Timing caveat

Microbench measures **elapsed wall time**, not CPU time. In an async program
the event loop may interleave other tasks while your coroutine is suspended
(e.g. during `await`). The measured duration therefore includes any time spent
running other coroutines.

Results are comparable across runs only when the event loop is not saturated
by concurrent work. For repeatable microbenchmarks consider:

- running in an otherwise-idle event loop (`asyncio.run()` starts a fresh one)
- using `iterations=N` to average over multiple calls

## `MBLineProfiler` incompatibility

`MBLineProfiler` relies on `line_profiler.LineProfiler.runcall`, which does
not support coroutines. Combining `MBLineProfiler` with an `async def`
function raises `NotImplementedError` at decoration time:

```python
class Bench(MicroBench, MBLineProfiler):
    pass

bench = Bench()

@bench  # raises NotImplementedError immediately
async def my_coroutine():
    ...
```

Use a synchronous wrapper function if you need line profiling, or remove
`MBLineProfiler` from the class.
