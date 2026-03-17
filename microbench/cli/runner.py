"""Subprocess execution and per-iteration capture for the CLI."""

import threading
from datetime import datetime, timezone


class _SubprocessMonitorThread(threading.Thread):
    """Background thread that samples CPU and RSS of a child process."""

    def __init__(self, pid, interval):
        super().__init__(daemon=True)
        self._pid = pid
        self._interval = interval
        self._stop = threading.Event()
        self.samples = []

    def stop(self):
        self._stop.set()

    def run(self):
        try:
            import psutil
        except ImportError:
            return
        try:
            proc = psutil.Process(self._pid)
            # Prime the CPU counter with a short blocking interval so the
            # immediate first sample has a meaningful cpu_percent value.
            proc.cpu_percent(interval=0.1)
            while True:
                try:
                    self.samples.append(
                        {
                            'timestamp': datetime.now(timezone.utc),
                            'cpu_percent': proc.cpu_percent(interval=None),
                            'rss_bytes': proc.memory_info().rss,
                        }
                    )
                except psutil.NoSuchProcess:
                    break
                if self._stop.wait(self._interval):
                    break
        except psutil.NoSuchProcess:
            pass
