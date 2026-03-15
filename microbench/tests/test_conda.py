from unittest.mock import patch

from microbench import MBCondaPackages, MicroBench

SAMPLE_CONDA_LIST = """\
# packages in environment at /path/to/env:
#
# Name                    Version                   Build  Channel
numpy                     1.24.3           py311ha0bc626_0    conda-forge
pandas                    2.0.3            py311h9a0d8c7_0
"""


def _run_conda_bench(**cls_attrs):
    attrs = {'include_builds': True, 'include_channels': True}
    attrs.update(cls_attrs)
    CondaBench = type('CondaBench', (MicroBench, MBCondaPackages), attrs)
    bench = CondaBench()

    @bench
    def noop():
        pass

    with patch(
        'subprocess.check_output',
        return_value=SAMPLE_CONDA_LIST.encode('utf8'),
    ):
        noop()

    return bench.get_results(format='df')


def test_conda_no_channel_doubling():
    """include_channels=True must not double the version string (B1 fix)."""
    results = _run_conda_bench(include_builds=True, include_channels=True)
    versions = results['conda_versions'][0]
    # numpy has a channel: expect "version+build(channel)", not doubled version
    assert versions['numpy'] == '1.24.3py311ha0bc626_0(conda-forge)', (
        f'Got: {versions["numpy"]!r}'
    )
    # pandas has no channel: expect "version+build"
    assert versions['pandas'] == '2.0.3py311h9a0d8c7_0', f'Got: {versions["pandas"]!r}'


def test_conda_include_builds_false():
    """include_builds=False should omit build string."""
    results = _run_conda_bench(include_builds=False, include_channels=False)
    versions = results['conda_versions'][0]
    assert versions['numpy'] == '1.24.3'
    assert versions['pandas'] == '2.0.3'


def test_conda_skip_comments_and_blanks():
    """Comment lines and blank lines should not appear in conda_versions."""
    results = _run_conda_bench()
    versions = results['conda_versions'][0]
    assert not any(k.startswith('#') for k in versions)
