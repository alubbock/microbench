import json
import os
import tempfile
import time
from datetime import timedelta

from microbench.livestream import LiveStream


def _write_record(fp, record):
    fp.write(json.dumps(record) + '\n')
    fp.flush()


def _make_record(**kwargs):
    """Build a v2-schema benchmark record."""
    base = {
        'call': {
            'name': 'test_fn',
            'start_time': '2024-01-01T00:00:00+00:00',
            'finish_time': '2024-01-01T00:00:01+00:00',
        },
        'host': {
            'hostname': 'localhost',
        },
    }
    # Allow overriding nested keys via dotted kwargs, e.g. call_name='foo'
    for key, value in kwargs.items():
        namespace, _, field = key.partition('_')
        if namespace in base and isinstance(base[namespace], dict) and field:
            base[namespace][field] = value
        else:
            base[key] = value
    return base


def test_livestream_processes_existing_lines():
    """LiveStream must process lines already in the file before tailing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        fname = f.name
        for i in range(3):
            rec = _make_record()
            rec['call']['name'] = f'fn_{i}'
            _write_record(f, rec)

    seen = []

    class TestStream(LiveStream):
        def display(self, data):
            seen.append(data['call']['name'])

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
    """LiveStream.stop() must cause the background thread to exit."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        fname = f.name
        _write_record(f, _make_record())

    seen = []

    class TestStream(LiveStream):
        def display(self, data):
            seen.append(data['call']['name'])

    try:
        stream = TestStream(fname)
        time.sleep(0.2)

        # Write a second record while the stream is running
        rec2 = _make_record()
        rec2['call']['name'] = 'test_fn2'
        with open(fname, 'a') as f:
            _write_record(f, rec2)

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


def test_livestream_process_runtime_nested_schema():
    """process_runtime must compute a timedelta from the v2 nested call fields."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        fname = f.name
        _write_record(f, _make_record())

    runtimes = []

    class TestStream(LiveStream):
        def display(self, data):
            runtimes.append(data.get('runtime'))

    try:
        stream = TestStream(fname)
        deadline = time.time() + 5
        while not runtimes and time.time() < deadline:
            time.sleep(0.05)
        stream.stop()
        stream.join(timeout=3)

        assert len(runtimes) == 1
        assert isinstance(runtimes[0], timedelta)
        assert runtimes[0] == timedelta(seconds=1)
    finally:
        os.unlink(fname)


def test_livestream_process_runtime_missing_fields():
    """process_runtime must set runtime=None when timestamp fields are absent."""
    record = {'call': {'name': 'test_fn'}, 'host': {'hostname': 'localhost'}}

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        fname = f.name
        _write_record(f, record)

    runtimes = []

    class TestStream(LiveStream):
        def display(self, data):
            runtimes.append(data.get('runtime'))

    try:
        stream = TestStream(fname)
        deadline = time.time() + 5
        while not runtimes and time.time() < deadline:
            time.sleep(0.05)
        stream.stop()
        stream.join(timeout=3)

        assert runtimes == [None]
    finally:
        os.unlink(fname)
