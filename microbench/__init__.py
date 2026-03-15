import atexit
import contextvars
import functools
import inspect
import json
import os
import signal
import sys
import threading
import time
import uuid
import warnings
from collections.abc import Iterable
from datetime import datetime, timezone

try:
    import line_profiler
except ImportError:
    line_profiler = None

try:
    # Written by setuptools-scm at build/install time
    from ._version_scm import __version__
except ImportError:
    try:
        from importlib.metadata import version as _version

        __version__ = _version('microbench')
    except Exception:
        __version__ = 'unknown'

from ._encoding import _UNENCODABLE_PLACEHOLDER_VALUE, JSONEncoder, JSONEncodeWarning
from ._output import FileOutput, Output, RedisOutput
from .mixins import (
    MBCgroupLimits,
    MBCondaPackages,
    MBFileHash,
    MBFunctionCall,
    MBGitInfo,
    MBGlobalPackages,
    MBHostCpuCores,
    MBHostInfo,
    MBHostRamTotal,
    MBInstalledPackages,
    MBLineProfiler,
    MBLoadedModules,
    MBNvidiaSmi,
    MBPeakMemory,
    MBPythonVersion,
    MBReturnValue,
    MBSlurmInfo,
    _MonitorThread,
)

# Generated once at import time; shared by all MicroBench instances in this
# process, allowing records from independent bench suites to be correlated.
_run_id = str(uuid.uuid4())

# ContextVar set to the active bm_data dict while inside bench.record(),
# bench.arecord(), or a @bench-decorated call.  bench.time() reads this to
# attach sub-timings to the current benchmark.  Each asyncio.Task gets its own
# copy, so concurrent arecord() calls stay isolated.
_active_bm_data: contextvars.ContextVar = contextvars.ContextVar(
    '_active_bm_data', default=None
)

__all__ = [
    # Core
    'MicroBench',
    # Output sinks
    'Output',
    'FileOutput',
    'RedisOutput',
    # Mixins
    'MBFunctionCall',
    'MBReturnValue',
    'MBPythonVersion',
    'MBHostInfo',
    'MBHostCpuCores',
    'MBHostRamTotal',
    'MBPeakMemory',
    'MBSlurmInfo',
    'MBLoadedModules',
    'MBCgroupLimits',
    'MBGitInfo',
    'MBFileHash',
    'MBGlobalPackages',
    'MBInstalledPackages',
    'MBCondaPackages',
    'MBLineProfiler',
    'MBNvidiaSmi',
    # JSON encoding
    'JSONEncoder',
    'JSONEncodeWarning',
]


class MicroBench:
    def __init__(
        self,
        outfile=None,
        json_encoder=JSONEncoder,
        tz=timezone.utc,
        iterations=1,
        warmup=0,
        duration_counter=time.perf_counter,
        outputs=None,
        *args,
        **kwargs,
    ):
        """Benchmark and metadata capture suite.

        Args:
            outfile (str or file-like, optional): Shorthand for a single
                :class:`FileOutput` destination. Mutually exclusive with
                *outputs*. Defaults to None (an in-memory
                :class:`io.StringIO` buffer when no *outputs* are given).
            json_encoder (json.JSONEncoder, optional): JSONEncoder for
                benchmark results. Defaults to JSONEncoder.
            tz (timezone, optional): Timezone for start_time and finish_time.
                Defaults to timezone.utc.
            iterations (int, optional): Number of iterations to run function.
                Defaults to 1.
            warmup (int, optional): Number of unrecorded calls to make before
                timing begins. Useful for priming caches or JIT compilation.
                Defaults to 0.
            duration_counter (callable, optional): Timer function to use for
                run_durations. Defaults to time.perf_counter.
            outputs (list of Output, optional): One or more :class:`Output`
                sinks that receive each benchmark result. Mutually exclusive
                with *outfile*. Defaults to a single :class:`FileOutput`
                (using *outfile* if given, otherwise the class-level
                ``outfile`` attribute, otherwise an in-memory
                :class:`io.StringIO`).

        Raises:
            ValueError: If both *outfile* and *outputs* are provided, or if
                extra positional arguments are passed.
        """
        if args:
            raise ValueError('Only keyword arguments are allowed')
        if outfile is not None and outputs is not None:
            raise ValueError(
                'outfile and outputs are mutually exclusive; '
                'use outputs=[FileOutput(...)] to combine file output with '
                'other sinks'
            )
        self._bm_static = kwargs
        self._json_encoder = json_encoder
        self._duration_counter = duration_counter
        self.tz = tz
        self.iterations = iterations
        self.warmup = warmup

        if outputs is not None:
            self._outputs = list(outputs)
        elif outfile is not None:
            self._outputs = [FileOutput(outfile)]
        elif hasattr(self, 'outfile'):
            self._outputs = [FileOutput(self.outfile)]
        else:
            self._outputs = [FileOutput()]

    def pre_start_triggers(self, bm_data):
        # Store timezone
        bm_data['timestamp_tz'] = str(self.tz)
        # Store duration counter function name
        bm_data['duration_counter'] = self._duration_counter.__name__
        # Run ID and package version (added to every record automatically)
        bm_data['mb_run_id'] = _run_id
        bm_data['mb_version'] = __version__

        # Capture environment variables
        if hasattr(self, 'env_vars'):
            if not isinstance(self.env_vars, Iterable):
                raise ValueError(
                    'env_vars should be a tuple of environment variable names'
                )

            for env_var in self.env_vars:
                bm_data[f'env_{env_var}'] = os.environ.get(env_var)

        # Capture package versions
        if hasattr(self, 'capture_versions'):
            if not isinstance(self.capture_versions, Iterable):
                raise ValueError(
                    'capture_versions is reserved for a tuple of package names'
                    ' - please rename this method'
                )

            for pkg in self.capture_versions:
                self._capture_package_version(bm_data, pkg)

        # Run capture triggers
        for method_name in dir(self):
            if method_name.startswith('capture_'):
                method = getattr(self, method_name)
                if callable(method):
                    if getattr(self, 'capture_optional', False):
                        try:
                            method(bm_data)
                        except Exception as e:
                            bm_data.setdefault('mb_capture_errors', []).append(
                                {
                                    'method': method_name,
                                    'error': f'{type(e).__name__}: {e}',
                                }
                            )
                    else:
                        method(bm_data)

        # Initialise monitor thread
        if hasattr(self, 'monitor'):
            interval = getattr(self, 'monitor_interval', 60)
            bm_data['monitor'] = []
            self._monitor_thread = _MonitorThread(
                self.monitor, interval, bm_data['monitor'], self.tz
            )
            self._monitor_thread.start()

        bm_data['run_durations'] = []
        bm_data['start_time'] = datetime.now(self.tz)

    def post_finish_triggers(self, bm_data):
        bm_data['finish_time'] = datetime.now(self.tz)

        # Terminate monitor thread and gather results
        if hasattr(self, '_monitor_thread'):
            self._monitor_thread.terminate()
            timeout = getattr(self, 'monitor_timeout', 30)
            self._monitor_thread.join(timeout)

        # Run capturepost triggers
        for method_name in dir(self):
            if method_name.startswith('capturepost_'):
                method = getattr(self, method_name)
                if callable(method):
                    if getattr(self, 'capture_optional', False):
                        try:
                            method(bm_data)
                        except Exception as e:
                            bm_data.setdefault('mb_capture_errors', []).append(
                                {
                                    'method': method_name,
                                    'error': f'{type(e).__name__}: {e}',
                                }
                            )
                    else:
                        method(bm_data)

    def pre_run_triggers(self, bm_data):
        bm_data['_run_start'] = self._duration_counter()

    def post_run_triggers(self, bm_data):
        bm_data['run_durations'].append(
            self._duration_counter() - bm_data['_run_start']
        )

    def capture_function_name(self, bm_data):
        if '_func' in bm_data:
            bm_data['function_name'] = bm_data['_func'].__name__

    def _capture_package_version(self, bm_data, pkg, skip_if_none=False):
        bm_data.setdefault('package_versions', {})
        try:
            ver = pkg.__version__
        except AttributeError:
            if skip_if_none:
                return
            ver = None
        bm_data['package_versions'][pkg.__name__] = ver

    def to_json(self, bm_data):
        bm_str = f'{json.dumps(bm_data, cls=self._json_encoder)}'

        return bm_str

    def output_result(self, bm_data):
        """Fan out the JSON-encoded result to all configured output sinks."""
        bm_str = self.to_json(bm_data)
        for output in self._outputs:
            output.write(bm_str)

    def get_results(self):
        """Return results from the first output sink that supports it."""
        for output in self._outputs:
            try:
                return output.get_results()
            except NotImplementedError:
                continue
        raise RuntimeError(
            'None of the configured output sinks support get_results(). '
            'Use FileOutput or RedisOutput.'
        )

    def __call__(self, func):
        if inspect.iscoroutinefunction(func):
            if isinstance(self, MBLineProfiler):
                raise NotImplementedError(
                    'MBLineProfiler does not support async functions. '
                    'Use a sync wrapper or remove MBLineProfiler.'
                )

            @functools.wraps(func)
            async def inner(*args, **kwargs):
                bm_data = dict()
                bm_data.update(self._bm_static)
                bm_data['_func'] = func
                bm_data['_args'] = args
                bm_data['_kwargs'] = kwargs

                for _ in range(self.warmup):
                    await func(*args, **kwargs)

                self.pre_start_triggers(bm_data)
                _ctx_token = _active_bm_data.set(bm_data)

                res = None
                exc_info = None
                try:
                    for _ in range(self.iterations):
                        self.pre_run_triggers(bm_data)
                        try:
                            res = await func(*args, **kwargs)
                        except Exception as e:
                            exc_info = e
                            self.post_run_triggers(bm_data)
                            break
                        self.post_run_triggers(bm_data)

                    self.post_finish_triggers(bm_data)

                    if exc_info is not None:
                        bm_data['exception'] = {
                            'type': type(exc_info).__name__,
                            'message': str(exc_info),
                        }
                    elif isinstance(self, MBReturnValue):
                        try:
                            self.to_json(res)
                            bm_data['return_value'] = res
                        except TypeError:
                            warnings.warn(
                                f'Return value is not JSON encodable '
                                f'(type: {type(res)}). '
                                'Extend JSONEncoder class to fix (see README).',
                                JSONEncodeWarning,
                            )
                            bm_data['return_value'] = _UNENCODABLE_PLACEHOLDER_VALUE

                    # Delete any underscore-prefixed keys
                    bm_data = {
                        k: v for k, v in bm_data.items() if not k.startswith('_')
                    }

                    self.output_result(bm_data)
                finally:
                    _active_bm_data.reset(_ctx_token)

                if exc_info is not None:
                    raise exc_info

                return res

            return inner

        def inner(*args, **kwargs):
            bm_data = dict()
            bm_data.update(self._bm_static)
            bm_data['_func'] = func
            bm_data['_args'] = args
            bm_data['_kwargs'] = kwargs

            if isinstance(self, MBLineProfiler):
                if not line_profiler:
                    raise ImportError(
                        'This functionality requires the "line_profiler" package'
                    )
                self._line_profiler = line_profiler.LineProfiler(func)

            for _ in range(self.warmup):
                func(*args, **kwargs)

            self.pre_start_triggers(bm_data)
            _ctx_token = _active_bm_data.set(bm_data)

            res = None
            exc_info = None
            try:
                for _ in range(self.iterations):
                    self.pre_run_triggers(bm_data)
                    try:
                        if isinstance(self, MBLineProfiler):
                            res = self._line_profiler.runcall(func, *args, **kwargs)
                        else:
                            res = func(*args, **kwargs)
                    except Exception as e:
                        exc_info = e
                        self.post_run_triggers(bm_data)
                        break
                    self.post_run_triggers(bm_data)

                self.post_finish_triggers(bm_data)

                if exc_info is not None:
                    bm_data['exception'] = {
                        'type': type(exc_info).__name__,
                        'message': str(exc_info),
                    }
                elif isinstance(self, MBReturnValue):
                    try:
                        self.to_json(res)
                        bm_data['return_value'] = res
                    except TypeError:
                        warnings.warn(
                            f'Return value is not JSON encodable (type: {type(res)}). '
                            'Extend JSONEncoder class to fix (see README).',
                            JSONEncodeWarning,
                        )
                        bm_data['return_value'] = _UNENCODABLE_PLACEHOLDER_VALUE

                # Delete any underscore-prefixed keys
                bm_data = {k: v for k, v in bm_data.items() if not k.startswith('_')}

                self.output_result(bm_data)
            finally:
                _active_bm_data.reset(_ctx_token)

            if exc_info is not None:
                raise exc_info

            return res

        return inner

    def record(self, name=None):
        """Return a context manager that times a block and writes one record.

        Args:
            name (str, optional): Value for the ``function_name`` field.
                Defaults to ``'<record>'``.

        Example::

            with bench.record('training'):
                model.fit(X, y)
        """
        return _ContextManagerRun(self, name)

    def arecord(self, name=None):
        """Return an async context manager that times a block and writes one record.

        Use with ``async with`` inside an async function or coroutine.

        Args:
            name (str, optional): Value for the ``function_name`` field.
                Defaults to ``'<record>'``.

        .. note::
            Elapsed wall time includes event-loop interleaving from other
            concurrent tasks. Results are comparable across runs only when
            the event loop is not saturated by other tasks.

        Example::

            async with bench.arecord('data_load'):
                await load_data()
        """
        return _AsyncContextManagerRun(self, name)

    def time(self, name: str) -> '_TimingSection':
        """Return a context manager recording a named sub-timing within a benchmark.

        Sub-timings are stored in ``mb_timings`` as a list of
        ``{"name": ..., "duration": ...}`` dicts in call order.
        Compatible with ``bench.record()``, ``bench.arecord()``,
        ``@bench`` (sync and async), and ``bench.record_on_exit()``.
        Calling outside an active benchmark is a silent no-op.

        Args:
            name (str): Label for this timing section.
        """
        return _TimingSection(self, name)

    def record_on_exit(self, name=None, handle_sigterm=True):
        """Register a process-exit handler that writes one benchmark record.

        Call once near the start of a script. When the process exits normally
        (or via SIGTERM when *handle_sigterm* is ``True``), a record is written
        containing the wall-clock duration from this call to exit, plus all
        mixin fields captured at exit time.

        Calling this method a second time on the same instance replaces the
        previous registration and resets the start time.

        Args:
            name (str, optional): Value for the ``function_name`` field.
                Defaults to ``'<process>'``.
            handle_sigterm (bool): Install a SIGTERM handler that writes the
                record before re-delivering the signal. Only effective when
                called from the main thread. Defaults to ``True``.

        Fields added beyond the standard timing fields:

        - ``exit_signal``: ``'SIGTERM'`` when the handler was triggered by
          SIGTERM; absent otherwise.
        - ``exception``: ``{"type": ..., "message": ...}`` when the process
          is exiting due to an unhandled exception; absent otherwise.

        .. note::
            SIGKILL and ``os._exit()`` cannot be caught; no record will be
            written in those cases. Use ``capture_optional = True`` on the
            benchmark class so that slow or unavailable capture methods do
            not delay the exit handler.

        Example::

            bench = MyBench(outfile='/scratch/results.jsonl')
            bench.record_on_exit('simulation')

            run_simulation()
        """
        # Deregister any previous registration from this instance.
        if hasattr(self, '_record_on_exit_handler'):
            atexit.unregister(self._record_on_exit_handler)

        # Terminate any monitor thread from a previous record_on_exit() call;
        # its samples will be discarded because the start time is also reset.
        if hasattr(self, '_record_on_exit_monitor_thread'):
            self._record_on_exit_monitor_thread.terminate()
            # No join here: we don't need the data and don't want to block.

        # Start the monitor thread *now* so it spans the full process lifetime
        # from this call to exit.  _exit_handler terminates it and injects the
        # samples into the record, replacing the exit-time-only slot that
        # pre_start_triggers would otherwise create.
        _monitor_slot = None
        _early_monitor = None
        if hasattr(self, 'monitor'):
            interval = getattr(self, 'monitor_interval', 60)
            _monitor_slot = []
            _early_monitor = _MonitorThread(
                self.monitor, interval, _monitor_slot, self.tz, daemon=True
            )
            _early_monitor.start()
            # Store handle so a subsequent record_on_exit() can terminate it.
            self._record_on_exit_monitor_thread = _early_monitor

        # Reset timings list; bench.time() appends here when ContextVar is None.
        self._record_on_exit_timings = []

        _start_counter = self._duration_counter()
        _start_time = datetime.now(self.tz)

        # Wrap sys.excepthook to capture unhandled exceptions.  atexit
        # handlers cannot reliably read sys.exc_info() at exit time.
        _exception_info = [None]
        _orig_excepthook = sys.excepthook

        def _excepthook(exc_type, exc_val, exc_tb):
            _exception_info[0] = (exc_type, exc_val)
            _orig_excepthook(exc_type, exc_val, exc_tb)

        sys.excepthook = _excepthook

        # Shared state to prevent double-writing if both atexit and the
        # SIGTERM handler fire in the same exit sequence.
        _ctx = {'fired': False}

        def _exit_handler(exit_signal=None):
            if _ctx['fired']:
                return
            _ctx['fired'] = True

            # Stop the process-lifetime monitor thread before pre_start_triggers
            # starts a new (exit-time-only) one.
            if _early_monitor is not None:
                _early_monitor.terminate()
                timeout = getattr(self, 'monitor_timeout', 30)
                _early_monitor.join(timeout)

            bm_data = dict()
            bm_data.update(self._bm_static)
            bm_data['function_name'] = name or '<process>'
            bm_data['_args'] = ()
            bm_data['_kwargs'] = {}

            self.pre_start_triggers(bm_data)
            # pre_start_triggers sets start_time and run_durations=[]; override
            # both with the values recorded at the call site.
            bm_data['start_time'] = _start_time
            bm_data['run_durations'] = [self._duration_counter() - _start_counter]
            # Replace exit-time-only monitor samples with our full-run ones.
            if _monitor_slot is not None:
                bm_data['monitor'] = _monitor_slot

            self.post_finish_triggers(bm_data)

            if _exception_info[0] is not None:
                exc_type, exc_val = _exception_info[0]
                bm_data['exception'] = {
                    'type': exc_type.__name__,
                    'message': str(exc_val),
                }

            if exit_signal is not None:
                bm_data['exit_signal'] = exit_signal

            if self._record_on_exit_timings:
                bm_data['mb_timings'] = list(self._record_on_exit_timings)

            bm_data = {k: v for k, v in bm_data.items() if not k.startswith('_')}

            try:
                self.output_result(bm_data)
            except Exception:
                # Fallback: write JSON directly to stderr so the record is not
                # silently lost if the primary output sink is unavailable.
                try:
                    sys.stderr.write(self.to_json(bm_data) + '\n')
                except Exception:
                    pass

        # Unique wrapper so atexit.unregister can target exactly this
        # registration on a subsequent record_on_exit() call.
        def _atexit_handler():
            _exit_handler()

        self._record_on_exit_handler = _atexit_handler
        atexit.register(_atexit_handler)

        if handle_sigterm:
            if threading.current_thread() is threading.main_thread():
                _prev_sigterm = signal.getsignal(signal.SIGTERM)

                def _sigterm_handler(signum, frame):
                    _exit_handler(exit_signal='SIGTERM')
                    # Chain to any previously installed handler (e.g.
                    # _MonitorThread.terminate) so it also runs cleanly.
                    if callable(_prev_sigterm):
                        _prev_sigterm(signum, frame)
                    signal.signal(signal.SIGTERM, signal.SIG_DFL)
                    os.kill(os.getpid(), signal.SIGTERM)

                signal.signal(signal.SIGTERM, _sigterm_handler)
            else:
                warnings.warn(
                    'bench.record_on_exit(): SIGTERM handler not registered '
                    'because called from a non-main thread. The record will '
                    'still be written on normal exit but may be lost if the '
                    'process receives SIGTERM.',
                    RuntimeWarning,
                    stacklevel=2,
                )


class _ContextManagerRun:
    """Context manager returned by :meth:`MicroBench.record`."""

    __slots__ = ('_bench', '_name', '_bm_data', '_ctx_token')

    def __init__(self, bench, name):
        self._bench = bench
        self._name = name

    def __enter__(self):
        if isinstance(self._bench, MBLineProfiler):
            raise NotImplementedError(
                'MBLineProfiler requires a callable to profile and cannot be '
                'used with bench.record(). Use the @bench decorator instead.'
            )
        bm_data = dict()
        bm_data.update(self._bench._bm_static)
        bm_data['function_name'] = self._name or '<record>'
        # Sentinels so MBFunctionCall produces args=[], kwargs={} rather than
        # a KeyError; _func is intentionally absent so capture_function_name
        # leaves function_name as set above.
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
        if isinstance(self._bench, MBLineProfiler):
            raise NotImplementedError(
                'MBLineProfiler requires a callable to profile and cannot be '
                'used with bench.arecord(). Use the @bench decorator instead.'
            )
        bm_data = dict()
        bm_data.update(self._bench._bm_static)
        bm_data['function_name'] = self._name or '<record>'
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
            self._bm_data.setdefault('mb_timings', []).append(entry)
        elif hasattr(self._bench, '_record_on_exit_timings'):
            self._bench._record_on_exit_timings.append(entry)
        return False  # never suppress exceptions

    async def __aenter__(self):
        return self.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return self.__exit__(exc_type, exc_val, exc_tb)
