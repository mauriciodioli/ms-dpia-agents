    # models/notification.py
from utils.db import db
from sqlalchemy.sql import func

class Notification(db.Model):
    __tablename__ = 'notification'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # 🎯 Destino
    user_id = db.Column(db.Integer, nullable=False, index=True)

    # 🧠 Tipo
    type = db.Column(db.String(32), nullable=False, index=True)
    # CHAT_MESSAGE / INVEST_SIGNAL / NEW_PUBLICATION / INCOMING_REQUEST / TASK_FINISHED / TIME_CONTEXT_SUGGESTION

    # 🔗 Referencia al evento real (polimórfico)
    ref_type = db.Column(db.String(32), nullable=False)
    ref_id = db.Column(db.Integer, nullable=False)

    # 🌍 Contexto DPIA (opcionales)
    codigo_postal = db.Column(db.String(16), nullable=True)
    idioma = db.Column(db.String(8), nullable=True)

    dominio_id = db.Column(db.Integer, nullable=True)
    ambito_id = db.Column(db.Integer, nullable=True)
    categoria_id = db.Column(db.Integer, nullable=True)
    publication_id = db.Column(db.Integer, nullable=True)
    chat_id = db.Column(db.Integer, nullable=True)

    # 🔔 Estado
    sent = db.Column(db.Boolean, default=False, nullable=False, index=True)
    sent_at = db.Column(db.DateTime, nullable=True)
    read_at = db.Column(db.DateTime, nullable=True)

    # ⚙️ Control
    priority = db.Column(db.SmallInteger, default=0, nullable=False)
    requires_push = db.Column(db.Boolean, default=True, nullable=False)

    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False, index=True)

    # Índices compuestos (para el worker)
    __table_args__ = (
        db.Index('idx_notification_user_sent', 'user_id', 'sent'),
        db.Index('idx_notification_type_created', 'type', 'created_at'),
        db.Index('idx_notification_ref', 'ref_type', 'ref_id'),
    )

    def __init__(
        self,
        user_id: int,
        type: str,
        ref_type: str,
        ref_id: int,
        codigo_postal: str = None,
        idioma: str = None,
        dominio_id: int = None,
        ambito_id: int = None,
        categoria_id: int = None,
        publication_id: int = None,
        chat_id: int = None,
        priority: int = 0,
        requires_push: bool = True,
    ):
        self.user_id = user_id
        self.type = type
        self.ref_type = ref_type
        self.ref_id = ref_id

        self.codigo_postal = codigo_postal
        self.idioma = idioma

        self.dominio_id = dominio_id
        self.ambito_id = ambito_id
        self.categoria_id = categoria_id
        self.publication_id = publication_id
        self.chat_id = chat_id

        self.priority = priority
        self.requires_push = requires_push

    def __repr__(self):
        return f"Notification(id={self.id}, user_id={self.user_id}, type={self.type}, ref={self.ref_type}:{self.ref_id}, sent={self.sent})"
