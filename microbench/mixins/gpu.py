"""GPU mixins: MBNvidiaSmi."""

import re
import subprocess

from microbench.mixins.base import CLIArg

_NVIDIA_GPU_REGEX = re.compile(r'^[0-9A-Za-z\-:]+$')


def _nvidia_gpu_id(value):
    """argparse type: accept a GPU index, UUID, or PCI bus ID."""
    import argparse

    if not _NVIDIA_GPU_REGEX.match(value):
        raise argparse.ArgumentTypeError(
            f'{value!r} is not a valid GPU ID. '
            'Use a zero-based index, UUID, or PCI bus ID.'
        )
    return value


class MBNvidiaSmi:
    """Capture attributes on installed NVIDIA GPUs using nvidia-smi.

    Requires the ``nvidia-smi`` utility to be available on ``PATH``
    (bundled with NVIDIA drivers).

    Results are stored as ``nvidia``, a list of per-GPU dicts. Each dict
    contains ``uuid`` plus one key per queried attribute. Run
    ``nvidia-smi --help-query-gpu`` for all available attribute names.
    Run ``nvidia-smi -L`` to list GPU UUIDs.

    Example output::

        {
            "nvidia": [
                {
                    "uuid": "GPU-abc123",
                    "gpu_name": "Tesla T4",
                    "memory.total": "16160 MiB"
                }
            ]
        }

    Attributes:
        nvidia_attributes (tuple[str]): Attributes to query. Defaults to
            ``('gpu_name', 'memory.total')``.
        nvidia_gpus (tuple): GPU IDs to poll — zero-based indexes, UUIDs,
            or PCI bus IDs. GPU UUIDs are recommended (indexes can change
            after a reboot). Omit to poll all installed GPUs.

    Note:
        CLI compatible.
    """

    _nvidia_default_attributes = ('gpu_name', 'memory.total')
    _nvidia_gpu_regex = _NVIDIA_GPU_REGEX
    cli_args = [
        CLIArg(
            flags=['--nvidia-attributes'],
            dest='nvidia_attributes',
            metavar='ATTR',
            nargs='+',
            help=(
                'GPU attributes to query with nvidia-smi. '
                'Run nvidia-smi --help-query-gpu for all names. '
                'Default: gpu_name memory.total'
            ),
        ),
        CLIArg(
            flags=['--nvidia-gpus'],
            dest='nvidia_gpus',
            metavar='GPU',
            nargs='+',
            type=_nvidia_gpu_id,
            help=(
                'GPU IDs to query: zero-based indexes, UUIDs, or PCI bus IDs. '
                'Run nvidia-smi -L to list UUIDs. '
                'Default: all GPUs.'
            ),
        ),
    ]

    def capture_nvidia(self, bm_data):
        nvidia_attributes = getattr(
            self, 'nvidia_attributes', self._nvidia_default_attributes
        )

        if hasattr(self, 'nvidia_gpus'):
            gpus = self.nvidia_gpus
            if not gpus:
                raise ValueError(
                    'nvidia_gpus cannot be empty. Leave the attribute out'
                    ' to capture data for all GPUs'
                )
            for gpu in gpus:
                if not self._nvidia_gpu_regex.match(str(gpu)):
                    raise ValueError(
                        'nvidia_gpus must be a list of GPU indexes (zero-based),'
                        ' UUIDs, or PCI bus IDs'
                    )
        else:
            gpus = None

        # Construct the command
        cmd = [
            'nvidia-smi',
            '--format=csv,noheader',
            '--query-gpu=uuid,{}'.format(','.join(nvidia_attributes)),
        ]
        if gpus:
            cmd += ['-i', ','.join(str(g) for g in gpus)]

        # Execute the command
        res = subprocess.check_output(cmd).decode('utf8')

        # Process results into a list of per-GPU dicts
        nvidia_list = []
        for gpu_line in res.split('\n'):
            if not gpu_line:
                continue
            gpu_res = gpu_line.split(', ')
            gpu_uuid = gpu_res[0]
            gpu_dict = {'uuid': gpu_uuid}
            for attr_idx, attr in enumerate(nvidia_attributes):
                gpu_dict[attr] = gpu_res[attr_idx + 1]
            nvidia_list.append(gpu_dict)
        bm_data['nvidia'] = nvidia_list
