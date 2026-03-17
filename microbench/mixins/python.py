"""Python environment mixins.

Classes: MBPythonInfo, MBGlobalPackages, MBInstalledPackages, MBCondaPackages.
"""

import inspect
import os
import platform
import shutil
import subprocess
import sys
import types


def _is_microbench_internal(filename):
    """True for source files inside the microbench package, excluding tests/."""
    # Use __file__ to locate the package root without importing microbench
    # (which would create a circular import when called during package init).
    _pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _tests_dir = os.path.join(_pkg_dir, 'tests')
    abs_file = os.path.abspath(filename)
    if abs_file.startswith(_tests_dir + os.sep):
        return False
    # Also exclude top-level tests/ directory
    top_tests = os.path.join(os.path.dirname(_pkg_dir), 'tests')
    if abs_file.startswith(top_tests + os.sep):
        return False
    return abs_file == _pkg_dir or abs_file.startswith(_pkg_dir + os.sep)


class MBPythonInfo:
    """Capture the Python interpreter version, prefix, and executable path.

    Records a ``python`` dict with three keys:

    - ``version``: the Python version string (e.g. ``"3.12.4"``)
    - ``prefix``: ``sys.prefix`` — the environment root
    - ``executable``: ``sys.executable`` — the absolute interpreter path

    This mixin is included in :class:`MicroBench` by default (Python API)
    and in the CLI default mixin set. It supersedes the former ``MBPythonVersion``.
    """

    cli_compatible = True

    def capture_python_info(self, bm_data):
        python = bm_data.setdefault('python', {})
        python['version'] = platform.python_version()
        python['prefix'] = sys.prefix
        python['executable'] = sys.executable


class MBGlobalPackages:
    """Capture Python packages imported in global environment.

    Results are stored in ``python.loaded_packages`` as a dict mapping
    package name to version string.
    """

    def capture_functions(self, bm_data):
        # Walk up the call stack to the first frame outside the microbench
        # package (excluding tests/) — that is the user's module whose globals
        # we want to inspect.
        caller_frame = inspect.currentframe()
        while caller_frame is not None:
            if not _is_microbench_internal(caller_frame.f_code.co_filename):
                break
            caller_frame = caller_frame.f_back
        if caller_frame is None:
            return
        caller_globals = caller_frame.f_globals
        for g in caller_globals.values():
            if isinstance(g, types.ModuleType):
                self._capture_package_version(bm_data, g, skip_if_none=True)
            else:
                try:
                    module_name = g.__module__
                except AttributeError:
                    continue

                self._capture_package_version(
                    bm_data, sys.modules[module_name.split('.')[0]], skip_if_none=True
                )


class MBInstalledPackages:
    """Capture installed Python packages using importlib.

    Records the name and version of every distribution available in the
    current Python environment via ``importlib.metadata``.

    Results are stored in ``python.installed_packages`` as a dict mapping
    package name to version string. When ``capture_paths=True``,
    installation paths are stored in ``python.installed_package_paths``.

    Attributes:
        capture_paths (bool): Also record the installation path of each
            package under ``python.installed_package_paths``. Defaults to
            ``False``.
    """

    cli_compatible = True
    capture_paths = False

    def capture_packages(self, bm_data):
        import importlib.metadata

        python = bm_data.setdefault('python', {})
        python['installed_packages'] = {}
        if self.capture_paths:
            python['installed_package_paths'] = {}

        for pkg in importlib.metadata.distributions():
            python['installed_packages'][pkg.name] = pkg.version
            if self.capture_paths:
                python['installed_package_paths'][pkg.name] = os.path.dirname(
                    pkg.locate_file(pkg.files[0])
                )


class MBCondaPackages:
    """Capture conda packages and active environment metadata.

    Runs ``conda list --prefix PREFIX`` where PREFIX is taken from the
    ``CONDA_PREFIX`` environment variable (the active conda environment).
    Falls back to ``sys.prefix`` when ``CONDA_PREFIX`` is not set (e.g.
    when running inside the base environment without explicit activation).

    If ``conda`` is not on ``PATH``, the ``CONDA_EXE`` environment variable
    is tried as a fallback before raising an error.

    Records a single ``conda`` dict with three keys:

    - ``name`` (from ``CONDA_DEFAULT_ENV``) — may be ``None`` if unset.
    - ``path`` (from ``CONDA_PREFIX``) — may be ``None`` if unset.
    - ``packages`` — dict mapping package name to version string.

    Attributes:
        include_builds (bool): Include the build string in the version.
            Defaults to ``True``.
        include_channels (bool): Include the channel name in the version.
            Defaults to ``False``.
    """

    cli_compatible = True
    include_builds = True
    include_channels = False

    def capture_conda_packages(self, bm_data):
        conda_prefix = os.environ.get('CONDA_PREFIX', sys.prefix)
        bm_data['conda'] = {
            'name': os.environ.get('CONDA_DEFAULT_ENV'),
            'path': os.environ.get('CONDA_PREFIX'),
            'packages': {},
        }

        conda_prefix = os.environ.get('CONDA_PREFIX', sys.prefix)
        conda_exe = shutil.which('conda') or os.environ.get('CONDA_EXE', 'conda')
        pkg_list = subprocess.check_output(
            [conda_exe, 'list', '--prefix', conda_prefix]
        ).decode('utf8')

        for pkg in pkg_list.splitlines():
            if pkg.startswith('#') or not pkg.strip():
                continue
            pkg_data = pkg.split()
            pkg_name = pkg_data[0]
            pkg_version = pkg_data[1]
            if self.include_builds:
                pkg_version += pkg_data[2]
            if self.include_channels and len(pkg_data) == 4:
                pkg_version += '(' + pkg_data[3] + ')'
            bm_data['conda']['packages'][pkg_name] = pkg_version
