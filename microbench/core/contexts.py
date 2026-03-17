"""Context managers for microbench benchmarks.

_ContextManagerRun   — sync  ``with bench.record(name)``
_AsyncContextManagerRun — async ``async with bench.arecord(name)``
_TimingSection       — sync/async ``with bench.time(name)``
"""

from .bench import _active_bm_data


class _ContextManagerRun:
    """Context manager returned by :meth:`MicroBench.record`."""

    __slots__ = ('_bench', '_name', '_bm_data', '_ctx_token')

    def __init__(self, bench, name):
        self._bench = bench
        self._name = name

    def __enter__(self):
        from microbench.mixins.profiling import MBLineProfiler

        if isinstance(self._bench, MBLineProfiler):
            raise NotImplementedError(
                'MBLineProfiler requires a callable to profile and cannot be '
                'used with bench.record(). Use the @bench decorator instead.'
            )
        bm_data = dict()
        bm_data.update(self._bench._bm_static)
        bm_data.setdefault('call', {})['name'] = self._name or '<record>'
        # Sentinels so MBFunctionCall produces args=[], kwargs={} rather than
        # a KeyError; _func is intentionally absent so capture_function_name
        # leaves call.name as set above.
        bm_data['_args'] = ()
        bm_data['_kwargs'] = {}
        self._bm_data = bm_data
        self._ctx_token = _active_bm_data.set(bm_data)
        self._bench.pre_start_triggers(bm_data)
        self._bench.pre_run_triggers(bm_data)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._bench.post_run_triggers(self._bm_data)
        self._bench.post_finish_triggers(self._bm_data)
        if exc_type is not None:
            self._bm_data['exception'] = {
                'type': exc_type.__name__,
                'message': str(exc_val),
            }
        bm_data = {k: v for k, v in self._bm_data.items() if not k.startswith('_')}
        self._bench.output_result(bm_data)
        _active_bm_data.reset(self._ctx_token)
        return False  # never suppress exceptions


class _AsyncContextManagerRun:
    """Async context manager returned by :meth:`MicroBench.arecord`."""

    __slots__ = ('_bench', '_name', '_bm_data', '_ctx_token')

    def __init__(self, bench, name):
        self._bench = bench
        self._name = name

    async def __aenter__(self):
        from microbench.mixins.profiling import MBLineProfiler

        if isinstance(self._bench, MBLineProfiler):
            raise NotImplementedError(
                'MBLineProfiler requires a callable to profile and cannot be '
                'used with bench.arecord(). Use the @bench decorator instead.'
            )
        bm_data = dict()
        bm_data.update(self._bench._bm_static)
        bm_data.setdefault('call', {})['name'] = self._name or '<record>'
        bm_data['_args'] = ()
        bm_data['_kwargs'] = {}
        self._bm_data = bm_data
        self._ctx_token = _active_bm_data.set(bm_data)
        self._bench.pre_start_triggers(bm_data)
        self._bench.pre_run_triggers(bm_data)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._bench.post_run_triggers(self._bm_data)
        self._bench.post_finish_triggers(self._bm_data)
        if exc_type is not None:
            self._bm_data['exception'] = {
                'type': exc_type.__name__,
                'message': str(exc_val),
            }
        bm_data = {k: v for k, v in self._bm_data.items() if not k.startswith('_')}
        self._bench.output_result(bm_data)
        _active_bm_data.reset(self._ctx_token)
        return False  # never suppress exceptions


class _TimingSection:
    """Context manager returned by :meth:`MicroBench.time`."""

    __slots__ = ('_bench', '_name', '_bm_data', '_start')

    def __init__(self, bench, name):
        self._bench = bench
        self._name = name
        # Capture the active bm_data now (at construction time) so that nested
        # bench.time() calls inside async tasks always attach to the right record.
        self._bm_data = _active_bm_data.get()
        self._start = None

    def __enter__(self):
        self._start = self._bench._duration_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._start is None:
            return False
        duration = self._bench._duration_counter() - self._start
        entry = {'name': self._name, 'duration': duration}
        if self._bm_data is not None:
            self._bm_data.setdefault('call', {}).setdefault('timings', []).append(entry)
        elif hasattr(self._bench, '_record_on_exit_timings'):
            self._bench._record_on_exit_timings.append(entry)
        return False  # never suppress exceptions

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return self.__exit__(exc_type, exc_val, exc_tb)
