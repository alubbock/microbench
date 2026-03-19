"""MicroBenchBase and MicroBench — core benchmark classes."""

import atexit
import contextvars
import functools
import inspect
import json
import os
import signal
import statistics as _statistics
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

from microbench.mixins.python import (
    MBPythonInfo,  # noqa: E402 (import after package init)
)

from .encoding import _UNENCODABLE_PLACEHOLDER_VALUE, JSONEncoder, JSONEncodeWarning
from .monitoring import _MonitorThread

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


def summary(results):
    """Print summary statistics for ``call.durations`` across a list of results.

    Requires no dependencies beyond the Python standard library.

    Args:
        results (list[dict]): Result dicts as returned by
            :meth:`MicroBench.get_results` (default ``format='dict'``).

    Example::

        bench = MicroBench()

        @bench
        def my_function():
            ...

        my_function()
        summary(bench.get_results())
        # n=1  min=0.000042  mean=0.000042  median=0.000042  max=0.000042  stdev=nan
    """
    durations = []
    for r in results:
        durations.extend(r.get('call', {}).get('durations', []))

    n = len(durations)
    if n == 0:
        print('No call.durations found in results.')
        return

    stdev = _statistics.stdev(durations) if n > 1 else float('nan')
    print(
        f'n={n}  '
        f'min={min(durations):.6f}  '
        f'mean={_statistics.mean(durations):.6f}  '
        f'median={_statistics.median(durations):.6f}  '
        f'max={max(durations):.6f}  '
        f'stdev={stdev:.6f}'
    )


class MicroBenchBase:
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
            tz (timezone, optional): Timezone for call.start_time and
                call.finish_time. Defaults to timezone.utc.
            iterations (int, optional): Number of iterations to run function.
                Defaults to 1.
            warmup (int, optional): Number of unrecorded calls to make before
                timing begins. Useful for priming caches or JIT compilation.
                Defaults to 0.
            duration_counter (callable, optional): Timer function to use for
                call.durations. Defaults to time.perf_counter.
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
        # Import here to avoid a circular import: outputs/ imports core/encoding
        from microbench.outputs.file import FileOutput

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
        # Store static config in mb namespace
        from microbench.version import __version__

        mb = bm_data.setdefault('mb', {})
        mb['timezone'] = str(self.tz)
        mb['duration_counter'] = self._duration_counter.__name__
        mb['run_id'] = _run_id
        mb['version'] = __version__

        # Mark as a Python API invocation (CLI overrides this to 'CLI')
        bm_data.setdefault('call', {})['invocation'] = 'Python'

        # Capture environment variables
        if hasattr(self, 'env_vars'):
            if not isinstance(self.env_vars, Iterable):
                raise ValueError(
                    'env_vars should be a tuple of environment variable names'
                )

            for env_var in self.env_vars:
                bm_data.setdefault('env', {})[env_var] = os.environ.get(env_var)

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
                            bm_data.setdefault('call', {}).setdefault(
                                'capture_errors', []
                            ).append(
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
            bm_data.setdefault('call', {})['monitor'] = []
            self._monitor_thread = _MonitorThread(
                self.monitor, interval, bm_data['call']['monitor'], self.tz
            )
            self._monitor_thread.start()

        bm_data.setdefault('call', {})['durations'] = []
        bm_data.setdefault('call', {})['start_time'] = datetime.now(self.tz)

    def post_finish_triggers(self, bm_data):
        bm_data.setdefault('call', {})['finish_time'] = datetime.now(self.tz)

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
                            bm_data.setdefault('call', {}).setdefault(
                                'capture_errors', []
                            ).append(
                                {
                                    'method': method_name,
                                    'error': f'{type(e).__name__}: {e}',
                                }
                            )
                    else:
                        method(bm_data)

    def pre_run_triggers(self, bm_data):
        bm_data['_run_start'] = self._duration_counter()
        # Forward to mixin overrides via cooperative super() chaining.
        parent = super()
        if hasattr(parent, 'pre_run_triggers'):
            parent.pre_run_triggers(bm_data)

    def post_run_triggers(self, bm_data):
        # Forward to mixin overrides before recording the elapsed time.
        parent = super()
        if hasattr(parent, 'post_run_triggers'):
            parent.post_run_triggers(bm_data)
        bm_data['call']['durations'].append(
            self._duration_counter() - bm_data['_run_start']
        )

    def capture_function_name(self, bm_data):
        if '_func' in bm_data:
            bm_data.setdefault('call', {})['name'] = bm_data['_func'].__name__

    def _capture_package_version(self, bm_data, pkg, skip_if_none=False):
        try:
            ver = pkg.__version__
        except AttributeError:
            if skip_if_none:
                return
            ver = None
        bm_data.setdefault('python', {}).setdefault('loaded_packages', {})[
            pkg.__name__
        ] = ver

    def to_json(self, bm_data):
        bm_str = json.dumps(bm_data, cls=self._json_encoder)

        return bm_str

    def output_result(self, bm_data):
        """Fan out the JSON-encoded result to all configured output sinks."""
        bm_str = self.to_json(bm_data)
        for output in self._outputs:
            output.write(bm_str)

    def get_results(self, format='dict', flat=False):
        """Return results from the first output sink that supports it.

        Args:
            format (str): ``'dict'`` (default) returns a list of dicts;
                ``'df'`` returns a pandas DataFrame (requires pandas).
            flat (bool): If *True*, flatten nested dict fields into
                dot-notation keys (e.g. ``call.name``, ``host.hostname``).
                Works for both formats and does not require pandas.

        Returns:
            list[dict] or pandas.DataFrame

        Raises:
            RuntimeError: If no configured sink supports reading results.
            ImportError: If *format* is ``'df'`` and pandas is not installed.
            ValueError: If *format* is not ``'dict'`` or ``'df'``.
        """
        for output in self._outputs:
            try:
                return output.get_results(format=format, flat=flat)
            except NotImplementedError:
                continue
        raise RuntimeError(
            'None of the configured output sinks support get_results(). '
            'Use FileOutput or RedisOutput.'
        )

    def summary(self):
        """Print summary statistics for ``call.durations`` across all results.

        Requires no dependencies beyond the Python standard library.
        Reads results via :meth:`get_results`.
        """
        summary(self.get_results())

    def __call__(self, func):
        from .contexts import _AsyncContextManagerRun, _ContextManagerRun  # noqa: F401

        if inspect.iscoroutinefunction(func):
            from microbench.mixins.profiling import MBLineProfiler

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
                    elif isinstance(self, _get_mbreturnvalue()):
                        try:
                            self.to_json(res)
                            bm_data.setdefault('call', {})['return_value'] = res
                        except TypeError:
                            warnings.warn(
                                f'Return value is not JSON encodable '
                                f'(type: {type(res)}). '
                                'Extend JSONEncoder class to fix (see README).',
                                JSONEncodeWarning,
                            )
                            bm_data.setdefault('call', {})['return_value'] = (
                                _UNENCODABLE_PLACEHOLDER_VALUE
                            )

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

        from microbench.mixins.profiling import MBLineProfiler

        @functools.wraps(func)
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
                elif isinstance(self, _get_mbreturnvalue()):
                    try:
                        self.to_json(res)
                        bm_data.setdefault('call', {})['return_value'] = res
                    except TypeError:
                        warnings.warn(
                            f'Return value is not JSON encodable (type: {type(res)}). '
                            'Extend JSONEncoder class to fix (see README).',
                            JSONEncodeWarning,
                        )
                        bm_data.setdefault('call', {})['return_value'] = (
                            _UNENCODABLE_PLACEHOLDER_VALUE
                        )

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
            name (str, optional): Value for the ``call.name`` field.
                Defaults to ``'<record>'``.

        Example::

            with bench.record('training'):
                model.fit(X, y)
        """
        from .contexts import _ContextManagerRun

        return _ContextManagerRun(self, name)

    def arecord(self, name=None):
        """Return an async context manager that times a block and writes one record.

        Use with ``async with`` inside an async function or coroutine.

        Args:
            name (str, optional): Value for the ``call.name`` field.
                Defaults to ``'<record>'``.

        .. note::
            Elapsed wall time includes event-loop interleaving from other
            concurrent tasks. Results are comparable across runs only when
            the event loop is not saturated by other tasks.

        Example::

            async with bench.arecord('data_load'):
                await load_data()
        """
        from .contexts import _AsyncContextManagerRun

        return _AsyncContextManagerRun(self, name)

    def time(self, name: str) -> '_TimingSection':  # noqa: F821
        """Return a context manager recording a named sub-timing within a benchmark.

        Sub-timings are stored in ``call.timings`` as a list of
        ``{"name": ..., "duration": ...}`` dicts in call order.
        Compatible with ``bench.record()``, ``bench.arecord()``,
        ``@bench`` (sync and async), and ``bench.record_on_exit()``.
        Calling outside an active benchmark is a silent no-op.

        Args:
            name (str): Label for this timing section.
        """
        from .contexts import _TimingSection

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
            name (str, optional): Value for the ``call.name`` field.
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
            bm_data.setdefault('call', {})['name'] = name or '<process>'
            bm_data['_args'] = ()
            bm_data['_kwargs'] = {}

            self.pre_start_triggers(bm_data)
            # pre_start_triggers sets call.start_time and call.durations=[]; override
            # both with the values recorded at the call site.
            bm_data['call']['start_time'] = _start_time
            bm_data['call']['durations'] = [self._duration_counter() - _start_counter]
            # Replace exit-time-only monitor samples with our full-run ones.
            if _monitor_slot is not None:
                bm_data['call']['monitor'] = _monitor_slot

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
                bm_data.setdefault('call', {})['timings'] = list(
                    self._record_on_exit_timings
                )

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


def _get_mbreturnvalue():
    """Late-import MBReturnValue to avoid circular imports."""
    from microbench.mixins.call import MBReturnValue

    return MBReturnValue


class MicroBench(MBPythonInfo, MicroBenchBase):
    """Benchmark suite with :class:`MBPythonInfo` included by default.

    Subclass this for typical usage. If you need a completely bare benchmark
    class with no default mixins, subclass :class:`MicroBenchBase` instead.
    """
