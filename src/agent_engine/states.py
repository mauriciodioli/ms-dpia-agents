from enum import StrEnum
from .errors import EngineError


class AgentState(StrEnum):
    ENABLED = 'ENABLED'
    DISABLED = 'DISABLED'


class AgentActivity(StrEnum):
    IDLE = 'IDLE'
    WAITING = 'WAITING'
    WORKING = 'WORKING'


class WorkerState(StrEnum):
    AVAILABLE = 'AVAILABLE'
    BUSY = 'BUSY'
    DISCONNECTED = 'DISCONNECTED'


class JobState(StrEnum):
    CREATED = 'CREATED'
    SCHEDULED = 'SCHEDULED'
    QUEUED = 'QUEUED'
    RUNNING = 'RUNNING'
    REVIEWING = 'REVIEWING'
    CORRECTION_REQUIRED = 'CORRECTION_REQUIRED'
    APPROVED = 'APPROVED'
    READY_FOR_DELIVERY = 'READY_FOR_DELIVERY'
    DELIVERED = 'DELIVERED'
    FAILED = 'FAILED'
    CANCELLED = 'CANCELLED'


TRANSITIONS = {
    JobState.CREATED: {JobState.SCHEDULED, JobState.QUEUED, JobState.FAILED, JobState.CANCELLED},
    JobState.SCHEDULED: {JobState.QUEUED, JobState.FAILED, JobState.CANCELLED},
    JobState.QUEUED: {JobState.RUNNING, JobState.FAILED, JobState.CANCELLED},
    JobState.RUNNING: {JobState.REVIEWING, JobState.FAILED, JobState.CANCELLED},
    JobState.REVIEWING: {JobState.APPROVED, JobState.CORRECTION_REQUIRED, JobState.FAILED, JobState.CANCELLED},
    JobState.CORRECTION_REQUIRED: {JobState.QUEUED, JobState.FAILED, JobState.CANCELLED},
    JobState.APPROVED: {JobState.READY_FOR_DELIVERY, JobState.FAILED, JobState.CANCELLED},
    JobState.READY_FOR_DELIVERY: {JobState.DELIVERED, JobState.FAILED, JobState.CANCELLED},
    JobState.DELIVERED: set(), JobState.FAILED: set(), JobState.CANCELLED: set(),
}


def require_transition(previous: str, following: str, *, informational: bool = False) -> None:
    if informational and previous == JobState.REVIEWING and following == JobState.DELIVERED:
        return
    try:
        permitted = JobState(following) in TRANSITIONS[JobState(previous)]
    except (ValueError, KeyError):
        permitted = False
    if not permitted:
        raise EngineError('invalid_transition', 409)
