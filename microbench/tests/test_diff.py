from microbench.diff import _align_seqs, _html_diffs, _markup_diff


def test_markup_diff_identical():
    """Identical sequences produce no highlighted spans."""
    tokens = ['hello', 'world']
    out_a, out_b = _markup_diff(tokens, tokens)
    assert out_a == tokens
    assert out_b == tokens


def test_markup_diff_different():
    """Differing tokens are wrapped in a <span> marker."""
    a = ['hello', 'world']
    b = ['hello', 'earth']
    out_a, out_b = _markup_diff(a, b)
    assert out_a[0] == 'hello'  # equal — unchanged
    assert '<span' in out_a[1]  # 'world' is marked
    assert '<span' in out_b[1]  # 'earth' is marked


def test_markup_diff_lengths_preserved():
    """Output lists are always the same length as the inputs."""
    a = ['a', 'b', 'c']
    b = ['x', 'b', 'z']
    out_a, out_b = _markup_diff(a, b)
    assert len(out_a) == len(a)
    assert len(out_b) == len(b)


def test_align_seqs_equal_length():
    """Equal-length sequences are returned unchanged."""
    a = ['x', 'y']
    b = ['a', 'b']
    out_a, out_b = _align_seqs(a, b)
    assert len(out_a) == len(out_b) == 2


def test_align_seqs_pads_shorter():
    """Shorter sequence is padded with the fill value to match the longer one."""
    a = ['a', 'b', 'c']
    b = ['a']
    out_a, out_b = _align_seqs(a, b)
    assert len(out_a) == len(out_b)
    assert '' in out_b  # default fill value


def test_html_diffs_returns_html():
    """_html_diffs returns an HTML string containing a grid div."""
    result = _html_diffs('hello world', 'hello earth')
    assert '<div' in result
    assert 'grid' in result


def test_html_diffs_identical():
    """Identical strings produce HTML with no diff spans."""
    result = _html_diffs('same text', 'same text')
    assert '<div' in result
    assert '<span' not in result
