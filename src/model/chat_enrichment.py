"""Persistent records for private, conversation-scoped enrichment."""

from datetime import datetime, timezone

from utils.db import db


ENRICHMENT_STATUSES = {
    "queued",
    "running",
    "succeeded",
    "partial",
    "failed",
    "cancelled",
    "stale",
}


class ChatEnrichmentRequest(db.Model):
    __tablename__ = "chat_enrichment_request"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    owner_user_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    conversation_id = db.Column(
        db.BigInteger,
        db.ForeignKey("conversation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    message_id = db.Column(
        db.BigInteger,
        db.ForeignKey("message.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    request_type = db.Column(db.String(64), nullable=False, default="factual_explanation")
    status = db.Column(db.String(16), nullable=False, default="queued", index=True)
    idempotency_key = db.Column(db.String(128), nullable=True, unique=True)
    context_version = db.Column(db.String(128), nullable=False)
    cancel_requested_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now(), index=True)
    started_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)

    result = db.relationship(
        "ChatEnrichmentResult",
        back_populates="request",
        uselist=False,
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        db.Index(
            "ix_chat_enrichment_request_owner_created",
            "owner_user_id",
            "created_at",
        ),
        db.Index(
            "ix_chat_enrichment_request_conversation_status",
            "conversation_id",
            "status",
        ),
    )

    def __init__(self, **kwargs):
        kwargs.setdefault("request_type", "factual_explanation")
        kwargs.setdefault("status", "queued")
        super().__init__(**kwargs)

    def transition_to(self, status):
        if status not in ENRICHMENT_STATUSES:
            raise ValueError(f"Unknown enrichment status: {status}")
        self.status = status
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        if status == "running" and self.started_at is None:
            self.started_at = now
        if status in {"succeeded", "partial", "failed", "cancelled", "stale"}:
            self.finished_at = now


class ChatEnrichmentResult(db.Model):
    __tablename__ = "chat_enrichment_result"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    request_id = db.Column(
        db.BigInteger,
        db.ForeignKey("chat_enrichment_request.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    answer_text = db.Column(db.Text, nullable=True)
    claims_json = db.Column(db.JSON, nullable=False, default=list)
    provider = db.Column(db.String(64), nullable=True)
    model = db.Column(db.String(128), nullable=True)
    failure_code = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, server_default=db.func.now())

    request = db.relationship("ChatEnrichmentRequest", back_populates="result")
    sources = db.relationship(
        "ChatEnrichmentSource",
        back_populates="result",
        cascade="all, delete-orphan",
    )


class ChatEnrichmentSource(db.Model):
    __tablename__ = "chat_enrichment_source"

    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    result_id = db.Column(
        db.BigInteger,
        db.ForeignKey("chat_enrichment_result.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url = db.Column(db.String(2048), nullable=False)
    title = db.Column(db.String(512), nullable=True)
    claim_ids_json = db.Column(db.JSON, nullable=False, default=list)
    retrieved_at = db.Column(db.DateTime, nullable=False)
    published_at = db.Column(db.DateTime, nullable=True)

    result = db.relationship("ChatEnrichmentResult", back_populates="sources")