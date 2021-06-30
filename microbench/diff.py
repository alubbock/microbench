import difflib
import json
import re
from itertools import zip_longest
try:
    import html
except ImportError:
    html = None


def _mark_text(text):
    return '<span style="color: red;">{}</span>'.format(text)


def _mark_span(text):
    return [_mark_text(token) for token in text]


def _markup_diff(a,
                 b,
                 mark=_mark_span,
                 default_mark=lambda x: x,
                 isjunk=None):
    """Returns a and b with any differences processed by mark

    Junk is ignored by the differ
    """
    seqmatcher = difflib.SequenceMatcher(isjunk=isjunk, a=a, b=b, autojunk=False)
    out_a, out_b = [], []
    for tag, a0, a1, b0, b1 in seqmatcher.get_opcodes():
        markup = default_mark if tag == 'equal' else mark
        out_a += markup(a[a0:a1])
        out_b += markup(b[b0:b1])
    assert len(out_a) == len(a)
    assert len(out_b) == len(b)
    return out_a, out_b


def _align_seqs(a, b, fill=''):
    out_a, out_b = [], []
    seqmatcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    for tag, a0, a1, b0, b1 in seqmatcher.get_opcodes():
        delta = (a1 - a0) - (b1 - b0)
        out_a += a[a0:a1] + [fill] * max(-delta, 0)
        out_b += b[b0:b1] + [fill] * max(delta, 0)
    assert len(out_a) == len(out_b)
    return out_a, out_b


def _html_sidebyside(a, b):
    # Set the panel display
    out = '<div style="display: grid;grid-template-columns: 1fr 1fr;grid-gap: 0;">'
    # There's some CSS in Jupyter notebooks that makes the first pair unalign.
    # This is a workaround
    out += '<p></p><p></p>'
    for left, right in zip_longest(a, b, fillvalue=''):
        out += '<pre style="margin-top:0;padding:0">{}</pre>'.format(left)
        out += '<pre style="margin-top:0";padding:0>{}</pre>'.format(right)
    out += '</div>'
    return out


def _html_diffs(a, b):
    if not html:
        raise ImportError('html package not found; Python 3.x required')
    a = html.escape(a)
    b = html.escape(b)

    out_a, out_b = [], []
    for sent_a, sent_b in zip(*_align_seqs(a.splitlines(), b.splitlines())):
        mark_a, mark_b = _markup_diff(sent_a.split(' '), sent_b.split(' '))
        out_a.append('&nbsp;'.join(mark_a))
        out_b.append('&nbsp;'.join(mark_b))

    return _html_sidebyside(out_a, out_b)


def _show_diffs(a, b):
    from IPython.display import HTML, display
    display(HTML(_html_diffs(a, b)))


def envdiff(a, b):
    """ Compare 2 JSON environments using visual diff

    a and b should be either pandas Series or strings of JSON objects
    """
    try:
        import pandas
    except ImportError:
        pandas = None
    if pandas:
        if isinstance(a, pandas.Series):
            a = a.to_json()
        if isinstance(b, pandas.Series):
            b = b.to_json()
    return _show_diffs(json.dumps(json.loads(a), indent=2),
                       json.dumps(json.loads(b), indent=2))
