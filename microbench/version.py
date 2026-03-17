"""Package version — single authoritative source for microbench.__version__."""

try:
    from ._version_scm import __version__
except ImportError:
    try:
        from importlib.metadata import version as _version

        __version__ = _version('microbench')
    except Exception:
        __version__ = 'unknown'
