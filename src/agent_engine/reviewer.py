"""Explicit, transactional review gate for completed agent results.

No LLM calls, provider calls, or automatic factual approval occur here.
A trusted internal caller must supply the decision; this is NOT a public API.
"""
from uuid import uuid4
from sqlalchemy import select, insert, update
from . import models as m
from .auth import now_utc
from .errors import EngineError
from .state_store import transition_job

DECISIONS = frozenset({'APPROVED', 'REJECTED', 'CORRECTION_REQUIRED'})
MAX_REVIEW_CYCLE = 2  # ae_reviews database CHECK constraint


def validate_review_decision(decision, reason_codes, evidence_status):
    """Pure policy validation. Approval requires separately verified evidence."""
    if not isinstance(decision, str) or decision not in DECISIONS:
        raise EngineError('invalid_review_decision')
    if not isinstance(reason_codes, list) or len(reason_codes) > 20 or any(
        not isinstance(code, str) or not 1 <= len(code) <= 80 or
        not all(c.isupper() or c.isdigit() or c == '_' for c in code)
        for code in reason_codes
    ):
        raise EngineError('invalid_review_reasons')
    if decision == 'APPROVED' and evidence_status != 'VERIFIED':
        raise EngineError('review_evidence_not_verified', 409)
    if decision != 'APPROVED' and not reason_codes:
        raise EngineError('review_reason_required')


class Reviewer:
    """Review a result in an existing transaction; caller controls authorization.

    The caller MUST authenticate and authorize a human reviewer or an independently
    trusted verification process for owner_id before calling review(). The engine
    deliberately does not expose this method through HTTP or auto-approve output.
    """

    def __init__(self, conn, *, now=None):
        self.conn = conn
        self.now = now or now_utc()

    def review(self, *, owner_id, job_id, result_id, decision, reason_codes,
               actor_id, expected_revision):
        if type(owner_id) is not int or owner_id <= 0 or not isinstance(actor_id, str) or not actor_id.strip():
            raise EngineError('reviewer_authorization_required', 403)
        if type(expected_revision) is not int or expected_revision < 1:
            raise EngineError('invalid_revision')
        # Savepoint keeps review insert, approval stamp and state transition atomic
        # even if the caller catches an EngineError in its outer transaction.
        with self.conn.begin_nested():
            job = self.conn.execute(select(m.jobs).where(
                m.jobs.c.owner_id == owner_id, m.jobs.c.id == job_id
            ).with_for_update()).mappings().first()
            if job is None:
                raise EngineError('job_not_found', 404)
            if job['revision'] != expected_revision:
                raise EngineError('revision_conflict', 409)
            if job['state'] != 'REVIEWING':
                raise EngineError('job_not_reviewable', 409)
            result = self.conn.execute(select(m.results).where(
                m.results.c.owner_id == owner_id, m.results.c.job_id == job_id,
                m.results.c.id == result_id
            ).with_for_update()).mappings().first()
            if result is None:
                raise EngineError('result_not_found', 404)
            latest = self.conn.execute(select(m.results.c.id).where(
                m.results.c.owner_id == owner_id, m.results.c.job_id == job_id
            ).order_by(m.results.c.version.desc()).limit(1)).scalar_one()
            if latest != result_id or result['approved_at'] is not None:
                raise EngineError('stale_review_result', 409)
            validate_review_decision(decision, reason_codes, result['evidence_status'])
            cycle = self.conn.execute(select(m.reviews.c.cycle).where(
                m.reviews.c.owner_id == owner_id, m.reviews.c.job_id == job_id
            ).order_by(m.reviews.c.cycle.desc()).limit(1)).scalar()
            cycle = 0 if cycle is None else cycle + 1
            if cycle > MAX_REVIEW_CYCLE:
                raise EngineError('review_cycles_exhausted', 409)
            # Rejected results fail closed. Correction requests enter a separate
            # state; re-queueing is intentionally not automatic.
            target = {'APPROVED': 'APPROVED', 'REJECTED': 'FAILED',
                      'CORRECTION_REQUIRED': 'CORRECTION_REQUIRED'}[decision]
            review_id = str(uuid4())
            self.conn.execute(insert(m.reviews).values(
                id=review_id, owner_id=owner_id, job_id=job_id, result_id=result_id,
                cycle=cycle, decision=decision, reason_codes=reason_codes,
                created_at=self.now))
            if decision == 'APPROVED':
                self.conn.execute(update(m.results).where(
                    m.results.c.owner_id == owner_id, m.results.c.id == result_id,
                    m.results.c.job_id == job_id, m.results.c.approved_at.is_(None)
                ).values(approved_at=self.now))
            revision = transition_job(self.conn, owner_id=owner_id, job_id=job_id,
                expected_revision=expected_revision, target=target,
                actor_id=actor_id, actor_type='SYSTEM',
                reason_code=reason_codes[0] if reason_codes else None, now=self.now)
            if decision == 'CORRECTION_REQUIRED':
                self.conn.execute(update(m.jobs).where(
                    m.jobs.c.owner_id == owner_id, m.jobs.c.id == job_id,
                    m.jobs.c.revision == revision
                ).values(correction_count=job['correction_count'] + 1))
            if decision == 'REJECTED':
                self.conn.execute(update(m.jobs).where(
                    m.jobs.c.owner_id == owner_id, m.jobs.c.id == job_id,
                    m.jobs.c.revision == revision
                ).values(error_code=reason_codes[0]))
            return {'review_id': review_id, 'job_id': job_id, 'result_id': result_id,
                    'decision': decision, 'cycle': cycle, 'revision': revision}
