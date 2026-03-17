"""Output utility helpers."""


def _flatten_dict(d, sep='.', _prefix=''):
    """Recursively flatten a nested dict using dot-notation keys.

    Example::

        >>> _flatten_dict({'a': {'b': 1}, 'c': 2})
        {'a.b': 1, 'c': 2}
    """
    out = {}
    for k, v in d.items():
        key = f'{_prefix}{sep}{k}' if _prefix else k
        if isinstance(v, dict):
            out.update(_flatten_dict(v, sep=sep, _prefix=key))
        else:
            out[key] = v
    return out
