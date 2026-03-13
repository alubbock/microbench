import json
import os
import tempfile
import time

from microbench.livestream import LiveStream


def _write_record(fp, record):
    fp.write(json.dumps(record) + '\n')
    fp.flush()


def _make_record(**kwargs):
    base = {
        'function_name': 'test_fn',
        'hostname': 'localhost',
        'start_time': '2024-01-01T00:00:00+00:00',
        'finish_time': '2024-01-01T00:00:01+00:00',
    }
    base.update(kwargs)
    return base


def test_livestream_processes_existing_lines():
    """LiveStream must process lines already in the file before tailing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        fname = f.name
        for i in range(3):
            _write_record(f, _make_record(function_name=f'fn_{i}'))

    seen = []

    class TestStream(LiveStream):
        def display(self, data):
            seen.append(data['function_name'])

    try:
        stream = TestStream(fname)
        time.sleep(0.4)
        stream.stop()
        stream.join(timeout=3)

        assert not stream._thread.is_alive(), 'LiveStream thread did not stop'
        assert seen == ['fn_0', 'fn_1', 'fn_2']
    finally:
        os.unlink(fname)


def test_livestream_stop_terminates_tail():
    """LiveStream.stop() must cause the background thread to exit (Q6 fix)."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        fname = f.name
        _write_record(f, _make_record())

    seen = []

    class TestStream(LiveStream):
        def display(self, data):
            seen.append(data['function_name'])

    try:
        stream = TestStream(fname)
        time.sleep(0.2)

        # Write a second record while the stream is running
        with open(fname, 'a') as f:
            _write_record(f, _make_record(function_name='test_fn2'))

        # Poll until both records are seen, then stop
        deadline = time.time() + 5
        while len(seen) < 2 and time.time() < deadline:
            time.sleep(0.05)

        stream.stop()
        stream.join(timeout=3)

        assert not stream._thread.is_alive(), (
            'LiveStream thread did not stop after stop()'
        )
        assert 'test_fn' in seen
        assert 'test_fn2' in seen
    finally:
        os.unlink(fname)
