"""Internal review orchestrator. No public endpoint or autonomous approvals.

Caller must authenticate/authorize reviewer identity and own the transaction.
Verification requires independently established evidence; this module never
sets evidence_status to VERIFIED based on output shape or user-provided claims.
"""
from sqlalchemy import select
from . import models as m
from .errors import EngineError
from .reviewer import Reviewer
from .verifier import inspect_output


class ReviewCoordinator:
    def __init__(self, conn, *, now=None):
        self.conn = conn
        self.now = now

    def inspect(self, *, owner_id, job_id):
        """Read-only examination of latest result in REVIEWING state."""
        if type(owner_id) is not int or owner_id <= 0:
            raise EngineError('reviewer_authorization_required', 403)
        job = self.conn.execute(select(m.jobs).where(
            m.jobs.c.owner_id == owner_id, m.jobs.c.id == job_id
        )).mappings().first()
        if job is None:
            raise EngineError('job_not_found', 404)
        if job['state'] != 'REVIEWING':
            raise EngineError('job_not_reviewable', 409)
        result = self.conn.execute(select(m.results).where(
            m.results.c.owner_id == owner_id, m.results.c.job_id == job_id
        ).order_by(m.results.c.version.desc()).limit(1)).mappings().first()
        if result is None:
            raise EngineError('result_not_found', 404)
        report = inspect_output(result['payload'], result['schema_version'])
        return {'owner_id': owner_id, 'job_id': job_id, 'result_id': result['id'],
                'revision': job['revision'], 'evidence_status': result['evidence_status'],
                'report': report, 'ready_for_approval': report['structurally_valid']
                and result['evidence_status'] == 'VERIFIED'}

    def decide(self, *, owner_id, job_id, actor_id, decision, reason_codes):
        """Explicit authorized decision; never runs automatically on inspection.

        Caller must commit outer transaction. Concurrency guarded by Reviewer.
        """
        report = self.inspect(owner_id=owner_id, job_id=job_id)
        if decision == 'APPROVED' and not report['ready_for_approval']:
            raise EngineError('review_verification_required', 409)
        return Reviewer(self.conn, now=self.now).review(
            owner_id=owner_id, job_id=job_id, result_id=report['result_id'],
            expected_revision=report['revision'], decision=decision,
            reason_codes=reason_codes, actor_id=actor_id)
