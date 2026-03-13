import json
import logging
import threading

import dateutil.parser


class LiveStream:
    """Tail a benchmark output file and process records as they arrive.

    Usage::

        stream = MyStream('/path/to/benchmark.jsonl')
        # ... runs in background ...
        stream.stop()
        stream.join()
    """

    def __init__(self, filename, sleeptime=0.5):
        self._log = self._setup_logger(filename)
        self._stop = threading.Event()

        process_fxns = []
        for method_name in dir(self):
            if method_name.startswith('process_'):
                method = getattr(self, method_name)
                if callable(method):
                    process_fxns.append(method)

        self._thread = threading.Thread(
            target=self._run,
            args=(filename, process_fxns, sleeptime),
            daemon=True,
        )
        self._thread.start()

    def _run(self, filename, process_fxns, sleeptime):
        try:
            for line in self._getlines(filename, self._stop, sleeptime):
                data = json.loads(line)
                if self.filter(data):
                    for fxn in process_fxns:
                        fxn(data)
                    self.display(data)
        except Exception:
            self._log.exception('Error processing benchmark record')

    def stop(self):
        """Signal the background thread to stop tailing the file."""
        self._stop.set()

    def join(self, timeout=None):
        """Wait for the background thread to finish."""
        self._thread.join(timeout=timeout)

    def _setup_logger(self, filename):
        logger = logging.getLogger(f"LiveStream('{filename}')")
        logger.setLevel(logging.INFO)

        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)

        fmt = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        ch.setFormatter(fmt)
        logger.addHandler(ch)

        return logger

    @staticmethod
    def _getlines(fn, stop_event, sleeptime=0.5):
        with open(fn) as fp:
            while not stop_event.is_set():
                line = fp.readline()

                if line:
                    yield line
                else:
                    stop_event.wait(sleeptime)

    def filter(self, data):
        # Function to filter whether to display line, should return boolean
        # True = process and display, False = ignore
        return True

    def process_runtime(self, data):
        data['runtime'] = dateutil.parser.parse(
            data['finish_time']
        ) - dateutil.parser.parse(data['start_time'])

    def display(self, data):
        self._log.info(
            '{}() on {} took {}'.format(
                data['function_name'],
                data.get('hostname', '<unknown>'),
                data['runtime'],
            )
        )
