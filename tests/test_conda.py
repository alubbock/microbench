import os
from unittest.mock import patch

from microbench import MBCondaPackages, MicroBench

SAMPLE_CONDA_LIST = """\
# packages in environment at /path/to/env:
#
# Name                    Version                   Build  Channel
numpy                     1.24.3           py311ha0bc626_0    conda-forge
pandas                    2.0.3            py311h9a0d8c7_0
"""


def _run_conda_bench(env=None, **cls_attrs):
    attrs = {'include_builds': True, 'include_channels': True}
    attrs.update(cls_attrs)
    CondaBench = type('CondaBench', (MicroBench, MBCondaPackages), attrs)
    bench = CondaBench()

    @bench
    def noop():
        pass

    conda_env = {'CONDA_PREFIX': '/opt/conda/envs/myenv', 'CONDA_DEFAULT_ENV': 'myenv'}
    if env is not None:
        conda_env.update(env)

    with (
        patch('shutil.which', return_value='conda'),
        patch(
            'subprocess.check_output',
            return_value=SAMPLE_CONDA_LIST.encode('utf8'),
        ),
        patch.dict(os.environ, conda_env, clear=False),
    ):
        noop()

    return bench.get_results(format='df')


def test_conda_no_channel_doubling():
    """include_channels=True must not double the version string (B1 fix)."""
    results = _run_conda_bench(include_builds=True, include_channels=True)
    packages = results['conda'][0]['packages']
    # numpy has a channel: expect "version build(channel)" with a space before build
    assert packages['numpy'] == '1.24.3 py311ha0bc626_0(conda-forge)', (
        f'Got: {packages["numpy"]!r}'
    )
    # pandas has no channel: expect "version build" with a space before build
    assert packages['pandas'] == '2.0.3 py311h9a0d8c7_0', f'Got: {packages["pandas"]!r}'


def test_conda_include_builds_false():
    """include_builds=False should omit build string."""
    results = _run_conda_bench(include_builds=False, include_channels=False)
    packages = results['conda'][0]['packages']
    assert packages['numpy'] == '1.24.3'
    assert packages['pandas'] == '2.0.3'


def test_conda_skip_comments_and_blanks():
    """Comment lines and blank lines should not appear in conda.packages."""
    results = _run_conda_bench()
    packages = results['conda'][0]['packages']
    assert not any(k.startswith('#') for k in packages)


def test_conda_field_populated():
    """conda field contains name and path from CONDA_DEFAULT_ENV and CONDA_PREFIX."""
    results = _run_conda_bench()
    conda = results['conda'][0]
    assert conda['name'] == 'myenv'
    assert conda['path'] == '/opt/conda/envs/myenv'


def test_conda_packages_nested_under_conda():
    """conda.packages holds the version dict, not a separate top-level field."""
    results = _run_conda_bench()
    result = results['conda'][0]
    assert 'packages' in result
    assert isinstance(result['packages'], dict)
    assert 'numpy' in result['packages']
    assert 'conda_versions' not in results.columns


def test_conda_field_none_when_vars_unset():
    """conda.name and conda.path are None when env vars are absent."""
    CondaBench = type('CondaBench', (MicroBench, MBCondaPackages), {})
    bench = CondaBench()

    @bench
    def noop():
        pass

    clean_env = {
        k: v
        for k, v in os.environ.items()
        if k not in ('CONDA_PREFIX', 'CONDA_DEFAULT_ENV')
    }
    with (
        patch('shutil.which', return_value='conda'),
        patch(
            'subprocess.check_output',
            return_value=SAMPLE_CONDA_LIST.encode('utf8'),
        ),
        patch.dict(os.environ, clean_env, clear=True),
    ):
        noop()

    conda = bench.get_results()[0]['conda']
    assert conda['name'] is None
    assert conda['path'] is None


def test_conda_uses_conda_prefix_for_list():
    """conda list is invoked with --prefix CONDA_PREFIX, not sys.prefix."""
    CondaBench = type('CondaBench', (MicroBench, MBCondaPackages), {})
    bench = CondaBench()

    @bench
    def noop():
        pass

    with (
        patch('shutil.which', return_value='conda'),
        patch(
            'subprocess.check_output',
            return_value=SAMPLE_CONDA_LIST.encode('utf8'),
        ) as mock_co,
        patch.dict(
            os.environ,
            {'CONDA_PREFIX': '/opt/conda/envs/myenv', 'CONDA_DEFAULT_ENV': 'myenv'},
            clear=False,
        ),
    ):
        noop()

    args = mock_co.call_args[0][0]
    assert '--prefix' in args
    assert args[args.index('--prefix') + 1] == '/opt/conda/envs/myenv'


def test_conda_falls_back_to_conda_exe():
    """When conda is not on PATH, CONDA_EXE is used as the conda executable."""
    CondaBench = type('CondaBench', (MicroBench, MBCondaPackages), {})
    bench = CondaBench()

    @bench
    def noop():
        pass

    with (
        patch('shutil.which', return_value=None),
        patch(
            'subprocess.check_output',
            return_value=SAMPLE_CONDA_LIST.encode('utf8'),
        ) as mock_co,
        patch.dict(
            os.environ,
            {
                'CONDA_PREFIX': '/opt/conda/envs/myenv',
                'CONDA_DEFAULT_ENV': 'myenv',
                'CONDA_EXE': '/opt/conda/bin/conda',
            },
            clear=False,
        ),
    ):
        noop()

    exe = mock_co.call_args[0][0][0]
    assert exe == '/opt/conda/bin/conda'


def test_conda_flat_results():
    """get_results(flat=True) flattens conda.packages.* to dot-notation keys."""
    CondaBench = type(
        'CondaBench',
        (MicroBench, MBCondaPackages),
        {'include_builds': False, 'include_channels': False},
    )
    bench = CondaBench()

    @bench
    def noop():
        pass

    with (
        patch('shutil.which', return_value='conda'),
        patch(
            'subprocess.check_output',
            return_value=SAMPLE_CONDA_LIST.encode('utf8'),
        ),
        patch.dict(
            os.environ,
            {'CONDA_PREFIX': '/opt/conda/envs/myenv', 'CONDA_DEFAULT_ENV': 'myenv'},
            clear=False,
        ),
    ):
        noop()

    flat = bench.get_results(flat=True)[0]
    assert flat['conda.name'] == 'myenv'
    assert flat['conda.path'] == '/opt/conda/envs/myenv'
    assert flat['conda.packages.numpy'] == '1.24.3'
    assert flat['conda.packages.pandas'] == '2.0.3'
    assert 'conda' not in flat  # fully expanded, no residual dict key
