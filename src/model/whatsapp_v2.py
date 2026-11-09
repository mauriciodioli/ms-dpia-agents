"""Durable WhatsApp state before a DPIA conversation exists."""
from utils.db import db
from sqlalchemy import Integer

_wa_id = db.BigInteger().with_variant(Integer(), "sqlite")


class WhatsAppContact(db.Model):
    __tablename__ = "whatsapp_v2_contact"
    id = db.Column(_wa_id, primary_key=True, autoincrement=True)
    phone_number_id = db.Column(db.String(100), nullable=False)
    sender_phone = db.Column(db.String(20), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=True)
    state = db.Column(db.String(32), nullable=False, default="exploring")
    created_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now(), nullable=False)
    __table_args__ = (db.UniqueConstraint("phone_number_id", "sender_phone", name="uq_wa_v2_contact_number_sender"),)


class WhatsAppEvent(db.Model):
    __tablename__ = "whatsapp_v2_event"
    id = db.Column(_wa_id, primary_key=True, autoincrement=True)
    phone_number_id = db.Column(db.String(100), nullable=False)
    message_id = db.Column(db.String(255), nullable=False)
    contact_id = db.Column(db.BigInteger, db.ForeignKey("whatsapp_v2_contact.id"), nullable=False)
    event_type = db.Column(db.String(32), nullable=False)
    payload_json = db.Column(db.JSON, nullable=False)
    status = db.Column(db.String(24), nullable=False, default="pending")
    received_at = db.Column(db.DateTime, server_default=db.func.now(), nullable=False)
    processed_at = db.Column(db.DateTime, nullable=True)
    __table_args__ = (
        db.UniqueConstraint("phone_number_id", "message_id", name="uq_wa_v2_event_number_message"),
        db.Index("ix_wa_v2_event_status_id", "status", "id"),
    )


class WhatsAppOffer(db.Model):
    __tablename__ = "whatsapp_v2_offer"
    id = db.Column(_wa_id, primary_key=True, autoincrement=True)
    contact_id = db.Column(db.BigInteger, db.ForeignKey("whatsapp_v2_contact.id"), nullable=False)
    event_id = db.Column(db.BigInteger, db.ForeignKey("whatsapp_v2_event.id"), nullable=False)
    option_key = db.Column(db.String(20), nullable=False)
    publication_id = db.Column(db.Integer, db.ForeignKey("publicacion.id"), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    selected_at = db.Column(db.DateTime, nullable=True)
    __table_args__ = (
        db.UniqueConstraint("event_id", "option_key", name="uq_wa_v2_offer_event_option"),
        db.Index("ix_wa_v2_offer_contact_expiry", "contact_id", "expires_at"),
    )
