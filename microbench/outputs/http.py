"""HttpOutput — POST each benchmark result to an HTTP/HTTPS endpoint."""

import json
import urllib.error
import urllib.request

from .base import Output


class HttpOutput(Output):
    """POST each benchmark result to an HTTP/HTTPS endpoint.

    Designed for webhooks and real-time notifications (e.g. Slack, Teams,
    custom event endpoints). Not intended for bulk storage — there is no
    :meth:`get_results` support.

    Uses only the Python standard library (``urllib``). Raises on non-2xx
    responses or network failures — no silent dropping, no automatic retry.

    By default the record dict is JSON-encoded and sent with
    ``Content-Type: application/json``. Override :meth:`format_payload` in a
    subclass to produce any body shape required by the target provider (e.g.
    a Slack ``{"text": ...}`` envelope).

    Args:
        url (str): Endpoint URL. Must be ``http://`` or ``https://``.
        headers (dict, optional): Extra HTTP headers merged with the defaults.
            Caller-supplied keys win on collision (case-sensitive). Use this
            for authentication (e.g. ``{'Authorization': 'Bearer <token>'}``).
            Defaults to ``None``.
        timeout (float, optional): Request timeout in seconds passed to
            :func:`urllib.request.urlopen`. Defaults to ``30.0``.
        method (str, optional): HTTP method. Defaults to ``'POST'``.

    Raises:
        urllib.error.HTTPError: If the server returns a non-2xx status code.
        urllib.error.URLError: If a network-level error occurs (DNS failure,
            connection refused, etc.).

    Example — basic usage::

        from microbench import MicroBench, HttpOutput

        bench = MicroBench(outputs=[HttpOutput('https://example.com/events')])

    Example — bearer token authentication::

        from microbench import MicroBench, HttpOutput

        bench = MicroBench(outputs=[HttpOutput(
            'https://api.example.com/benchmarks',
            headers={'Authorization': 'Bearer my-secret-token'},
        )])

    Example — Slack webhook via subclass::

        import json
        from microbench import MicroBench, HttpOutput

        class SlackOutput(HttpOutput):
            def format_payload(self, record):
                name = record.get('call', {}).get('name', '?')
                return json.dumps({'text': f'Benchmark `{name}` finished.'}).encode()

        bench = MicroBench(outputs=[SlackOutput('https://hooks.slack.com/services/...')])
    """

    def __init__(self, url, *, headers=None, timeout=30.0, method='POST'):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout
        self.method = method.upper()

    def format_payload(self, record):
        """Encode *record* as the HTTP request body.

        The default implementation JSON-encodes the record dict and returns
        UTF-8 bytes. Subclasses may override this to produce any body shape
        required by the target provider.

        Args:
            record (dict): Decoded benchmark result dict.

        Returns:
            bytes: Request body.
        """
        return json.dumps(record).encode('utf-8')

    def _build_request(self, record):
        body = self.format_payload(record)
        if isinstance(body, str):
            body = body.encode('utf-8')
        default_headers = {'Content-Type': 'application/json'}
        merged_headers = {**default_headers, **self.headers}
        return urllib.request.Request(
            self.url,
            data=body,
            headers=merged_headers,
            method=self.method,
        )

    def write(self, bm_json_str):
        """POST *bm_json_str* to the configured URL.

        Args:
            bm_json_str (str): JSON-encoded benchmark record, as produced by
                :meth:`MicroBenchBase.to_json`.

        Raises:
            urllib.error.HTTPError: On a non-2xx HTTP response.
            urllib.error.URLError: On a network-level error.
        """
        record = json.loads(bm_json_str)
        request = self._build_request(record)
        with urllib.request.urlopen(request, timeout=self.timeout):
            pass
