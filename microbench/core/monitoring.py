"""Background monitoring thread for microbench.

_MonitorThread samples a user-supplied telemetry function at a fixed
interval and appends timestamped records to a shared list.
"""

import signal
import threading
import warnings
from datetime import datetime

try:
    import psutil
except ImportError:
    psutil = None


class _MonitorThread(threading.Thread):
    def __init__(self, telem_fn, interval, slot, timezone, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._terminate = threading.Event()
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGINT, self.terminate)
            signal.signal(signal.SIGTERM, self.terminate)
        else:
            warnings.warn(
                '_MonitorThread: signal handlers not registered because '
                'benchmark was started from a non-main thread. Monitoring '
                'will still be collected but may not stop cleanly on '
                'SIGINT/SIGTERM.',
                RuntimeWarning,
            )
        self._interval = interval
        self._monitor_data = slot
        self._monitor_fn = telem_fn
        self._tz = timezone
        if not psutil:
            raise ImportError('Monitoring requires the "psutil" package')
        self.process = psutil.Process()

    def terminate(self, signum=None, frame=None):
        self._terminate.set()

    def _get_sample(self):
        sample = {'timestamp': datetime.now(self._tz)}
        sample.update(self._monitor_fn(self.process))
        self._monitor_data.append(sample)

    def run(self):
        self._get_sample()
        while not self._terminate.wait(self._interval):
            self._get_sample()
