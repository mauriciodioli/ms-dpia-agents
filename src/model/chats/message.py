# models/chats/message.py
from sqlalchemy import DateTime
from utils.db import db
from model.chats.message_media import MessageMedia  # 👈 tu import actual


class Message(db.Model):
    __tablename__ = "message"

    id = db.Column(db.BigInteger, primary_key=True)

    conversation_id = db.Column(
        db.BigInteger,
        db.ForeignKey("conversation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    role = db.Column(db.String(16), nullable=False)   # client|owner|ia
    via  = db.Column(db.String(16), default="dpia")   # dpia|wa|email|webhook

    content_type = db.Column(db.String(12), default="text")  # text|media|mixed

    content  = db.Column(db.Text)  # ⚠️ LEGACY: usar content_encrypted
    content_encrypted = db.Column(db.Text)  # ✅ NUEVO: mensaje encriptado en base64
    blob_ref = db.Column(db.String(255))
    
    # ✅ NUEVO: Usuario asociado (para lazy migration de encriptación)
    user_id = db.Column(
        db.BigInteger,
        db.ForeignKey("usuarios.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    intent      = db.Column(db.String(64))
    emotion     = db.Column(db.String(32))
    confidence  = db.Column(db.Float)
    labels_json = db.Column(db.JSON)

    created_at = db.Column(db.DateTime, server_default=db.func.now())

    delivered_at = db.Column(DateTime, nullable=True)
    read_at      = db.Column(DateTime, nullable=True)

    # =========================
    # ✅ NUEVO: Reply a otro mensaje (WhatsApp-like)
    # - SET NULL para NO borrar replies si se borra el original
    # =========================
    reply_to_msg_id = db.Column(
        db.BigInteger,
        db.ForeignKey("message.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Relación opcional para acceder al mensaje citado (preview fácil)
    reply_to = db.relationship(
        "Message",
        remote_side=[id],
        uselist=False,
        foreign_keys=[reply_to_msg_id],
    )

    # ✅ Relación con usuario (quién envió el mensaje)
    usuario = db.relationship(
        "Usuario",
        backref="messages",
        lazy="select",
        foreign_keys=[user_id],
    )

    # =========================
    # ✅ PIN: Mensaje fijado en la conversación
    # =========================
    is_pinned = db.Column(db.Boolean, default=False, index=True)
    pinned_at = db.Column(db.DateTime, nullable=True)  # cuándo se fijó

    # =========================
    # Media asociada (lo tuyo, intacto)
    # =========================
    media = db.relationship(
        "MessageMedia",        # NO "message_media"
        backref="message",
        lazy="select",
        cascade="all, delete-orphan",
    )
