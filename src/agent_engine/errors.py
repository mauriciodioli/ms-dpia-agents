class EngineError(Exception):
    """Only fixed public messages belong in this exception."""

    def __init__(self, code: str, status: int = 400):
        self.code = code
        self.status = status
        super().__init__(code)


# Deterministic local failures: repeating the same input cannot repair them.
LOCAL_NON_RETRYABLE = frozenset({
    'provider_invalid_json', 'invalid_evidence_json', 'invalid_token_usage',
    'analysis_input_limit', 'commercial_request_mismatch', 'output_token_budget_exceeded',
    'commercial_integration_unavailable', 'provider_deadline_insufficient',
})
