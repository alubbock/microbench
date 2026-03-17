"""Call-related mixins: MBFunctionCall, MBReturnValue."""

import warnings

from microbench.core.encoding import _UNENCODABLE_PLACEHOLDER_VALUE, JSONEncodeWarning


class MBFunctionCall:
    """Capture function arguments and keyword arguments"""

    def capture_function_args_and_kwargs(self, bm_data):
        call = bm_data.setdefault('call', {})
        # Check all args are encodeable as JSON, then store the raw value
        call['args'] = []
        for i, v in enumerate(bm_data['_args']):
            try:
                self.to_json(v)
                call['args'].append(v)
            except TypeError:
                warnings.warn(
                    f'Function argument {i} is not JSON encodable (type: {type(v)}). '
                    'Extend JSONEncoder class to fix (see README).',
                    JSONEncodeWarning,
                )
                call['args'].append(_UNENCODABLE_PLACEHOLDER_VALUE)

        # Check all kwargs are encodeable as JSON, then store the raw value
        call['kwargs'] = {}
        for k, v in bm_data['_kwargs'].items():
            try:
                self.to_json(v)
                call['kwargs'][k] = v
            except TypeError:
                warnings.warn(
                    f'Function keyword argument "{k}" is not JSON encodable'
                    f' (type: {type(v)}). Extend JSONEncoder class to fix'
                    ' (see README).',
                    JSONEncodeWarning,
                )
                call['kwargs'][k] = _UNENCODABLE_PLACEHOLDER_VALUE


class MBReturnValue:
    """Capture the decorated function's return value"""

    pass
