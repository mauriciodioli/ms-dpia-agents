class EngineError(Exception):
    """Only fixed public messages belong in this exception."""

    def __init__(self, code: str, status: int = 400):
        self.code = code
        self.status = status
        super().__init__(code)


# Deterministic local failures: repeating the same input cannot repair them.
LOCAL_NON_RETRYABLE = frozenset({
    'VIDEO_TASK_NOT_AUTHORIZED','VIDEO_PARENT_NOT_AUTHORIZED',
    'VIDEO_CONFIGURATION_INVALID',
    'VIDEO_PROVIDER_NOT_SENT',
    'VIDEO_RESERVATION_LIMIT','VIDEO_RESERVATION_CONFLICT','VIDEO_OPERATION_NOT_REPLAYABLE',
    'VIDEO_COST_EXCEEDS_RESERVATION',
    'VIDEO_PREVIOUS_OPERATION_UNRESOLVED',
    'VIDEO_SCRIPT_SOURCE_INSUFFICIENT','VIDEO_SCRIPT_SOURCE_LIMIT','VIDEO_SCRIPT_INVALID_RESPONSE',
    'VIDEO_SCRIPT_INVALID_REFERENCE','VIDEO_SCRIPT_DURATION_EXCEEDED','VIDEO_CONFIGURATION_CHANGED',
    'VIDEO_COST_RATE_NOT_CONFIGURED','VIDEO_COST_NOT_VERIFIABLE','VIDEO_BUDGET_INSUFFICIENT',
    'VIDEO_PRODUCTION_APPROVAL_REQUIRED','VIDEO_LEDGER_SCHEMA_INCOMPATIBLE','VIDEO_RESOURCE_UNAVAILABLE',
    'VIDEO_PROVIDER_SELECTION_REQUIRED','VIDEO_CATALOG_INVALID','VIDEO_SCRIPT_NOT_PERSISTED',
    'provider_invalid_json', 'invalid_evidence_json', 'invalid_token_usage',
    'analysis_input_limit', 'commercial_request_mismatch', 'output_token_budget_exceeded',
    'commercial_integration_unavailable', 'provider_deadline_insufficient',
})


class ProviderNotSent(EngineError):
    """Trusted transport proof: failure occurred before the HTTP request call."""
