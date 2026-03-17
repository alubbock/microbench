"""Version-control mixins: MBGitInfo, MBFileHash."""

import os
import subprocess
import sys

from microbench.mixins.base import CLIArg


def _existing_file(value):
    """argparse type: accept an existing file path, reject directories."""
    import argparse

    if os.path.isdir(value):
        raise argparse.ArgumentTypeError(f'{value!r} is a directory')
    if not os.path.isfile(value):
        raise argparse.ArgumentTypeError(f'file not found: {value!r}')
    return value


def _existing_dir(value):
    """argparse type: accept an existing directory path."""
    import argparse

    if not os.path.isdir(value):
        raise argparse.ArgumentTypeError(f'directory not found: {value!r}')
    return value


def _resolve_cmd_path(cmd):
    """Resolve cmd[0] to an absolute file path for use as a hash target."""
    import shutil

    path = cmd[0]
    resolved = shutil.which(path)
    if resolved:
        return [resolved]
    if os.path.isfile(path):
        return [path]
    return []


class MBGitInfo:
    """Capture git repository information.

    Requires ``git`` ≥ 2.11 to be available on ``PATH``. Records the
    current repo directory, commit hash, branch name, and whether the
    working tree has uncommitted changes. Results are stored in the
    ``git`` field.

    By default inspects the repository containing the running script
    (``sys.argv[0]``), falling back to the shell's working directory
    when the script path is unavailable (e.g. interactive Python). Set
    ``git_repo`` explicitly to target a specific directory, which is
    useful when the script and the repository root are in different
    locations.

    **CLI usage** (``python -m microbench``): the default is the current
    working directory rather than the script directory, since
    ``sys.argv[0]`` points to the microbench package itself. Use
    ``--git-repo DIR`` to override.

    Attributes:
        git_repo (str, optional): Directory to inspect. Defaults to the
            directory of the running script, or the shell's working
            directory if unavailable.

    Example output::

        {
            "git": {
                "repo": "/home/user/project",
                "commit": "a1b2c3d4e5f6...",
                "branch": "main",
                "dirty": false
            }
        }
    """

    cli_compatible = True
    cli_args = [
        CLIArg(
            flags=['--git-repo'],
            dest='git_repo',
            metavar='DIR',
            type=_existing_dir,
            help=(
                'Directory to inspect for git info. '
                'CLI default: current working directory. '
                'Python API default: directory of the running script.'
            ),
            cli_default=lambda cmd: os.getcwd(),
        ),
    ]

    def capture_git_info(self, bm_data):
        if hasattr(self, 'git_repo'):
            cwd = self.git_repo
        else:
            argv0 = sys.argv[0] if sys.argv else ''
            if argv0 and not argv0.startswith('-'):
                cwd = os.path.dirname(os.path.abspath(argv0))
            else:
                cwd = None  # fall back to shell's working directory

        kwargs = {'cwd': cwd, 'stderr': subprocess.DEVNULL}

        repo = (
            subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], **kwargs)
            .decode()
            .strip()
        )

        output = subprocess.check_output(
            ['git', 'status', '--porcelain=v2', '--branch'], **kwargs
        ).decode()

        commit = ''
        branch = ''
        dirty = False
        for line in output.splitlines():
            if line.startswith('# branch.oid '):
                commit = line[13:]
            elif line.startswith('# branch.head '):
                head = line[14:]
                branch = '' if head == '(detached)' else head
            elif not line.startswith('#'):
                dirty = True

        bm_data['git'] = {
            'repo': repo,
            'commit': commit,
            'branch': branch,
            'dirty': dirty,
        }


class MBFileHash:
    """Capture cryptographic hashes of specified files.

    Useful for recording the exact state of scripts or configuration
    files alongside benchmark results, so results can be tied to a
    specific version of the code even without version control.

    By default hashes the running script (``sys.argv[0]``). Set
    ``hash_files`` to an iterable of paths to hash specific files
    instead. Files are read in 64 KB chunks, so large files are handled
    without loading them fully into memory.

    **CLI usage** (``python -m microbench``): the default is the
    benchmarked command executable (``cmd[0]``) rather than the running
    script, since ``sys.argv[0]`` points to the microbench package
    itself. Use ``--hash-file FILE [FILE ...]`` to override, and
    ``--hash-algorithm`` to change the algorithm.

    Attributes:
        hash_files (iterable of str, optional): File paths to hash.
            Defaults to ``[sys.argv[0]]``.
        hash_algorithm (str, optional): Hash algorithm name accepted by
            :func:`hashlib.new`. Defaults to ``'sha256'``. Use ``'md5'``
            for faster hashing of large files where cryptographic strength
            is not required.

    Example output::

        {
            "file_hashes": {
                "run_experiment.py": "e3b0c44298fc1c14..."
            }
        }
    """

    cli_compatible = True
    cli_args = [
        CLIArg(
            flags=['--hash-file'],
            dest='hash_files',
            metavar='FILE',
            nargs='+',
            type=_existing_file,
            help=(
                'File(s) to hash with the file-hash mixin. '
                'CLI default: the benchmarked command executable. '
                'Python API default: the running script.'
            ),
            cli_default=_resolve_cmd_path,
        ),
        CLIArg(
            flags=['--hash-algorithm'],
            dest='hash_algorithm',
            metavar='ALGORITHM',
            help='Hash algorithm for the file-hash mixin (e.g. sha256, md5). Default: sha256.',  # noqa: E501
        ),
    ]

    def capture_file_hashes(self, bm_data):
        import hashlib

        if hasattr(self, 'hash_files'):
            paths = list(self.hash_files)
        else:
            argv0 = sys.argv[0] if sys.argv else ''
            paths = [argv0] if argv0 and not argv0.startswith('-') else []

        algorithm = getattr(self, 'hash_algorithm', 'sha256')
        hashes = {}
        for path in paths:
            with open(path, 'rb') as f:
                if hasattr(hashlib, 'file_digest'):
                    # Python 3.11+: C-level loop, faster for large files
                    hashes[path] = hashlib.file_digest(f, algorithm).hexdigest()
                else:
                    h = hashlib.new(algorithm)
                    for chunk in iter(lambda: f.read(65536), b''):
                        h.update(chunk)
                    hashes[path] = h.hexdigest()
        bm_data['file_hashes'] = hashes
