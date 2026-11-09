"""Conservative deterministic validation of stored task outputs.

Schema checks are not evidence of factual accuracy. Never elevate UNVERIFIED
results to VERIFIED merely because their JSON is structurally valid.
"""
import json

MAX_BYTES = 262144


def inspect_output(payload, schema_version):
    """Return a stable validation report. Does not access DB or providers."""
    reasons = []
    if schema_version != 'agents.task-output.v1':
        reasons.append('UNSUPPORTED_SCHEMA')
    if not isinstance(payload, dict):
        reasons.append('INVALID_PAYLOAD_TYPE')
    else:
        try:
            raw = json.dumps(payload, allow_nan=False)
            if len(raw.encode('utf-8')) > MAX_BYTES:
                reasons.append('PAYLOAD_TOO_LARGE')
        except (ValueError, TypeError, OverflowError):
            reasons.append('INVALID_JSON')
    return {'structurally_valid': not reasons, 'reason_codes': reasons,
            'evidence_verified': False}
