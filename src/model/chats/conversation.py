from utils.db import db

class Conversation(db.Model):
    __tablename__ = "conversation"

    id = db.Column(db.BigInteger, primary_key=True)
    scope_id = db.Column(db.BigInteger, db.ForeignKey("chat_scope.id"), nullable=False)
    owner_user_id = db.Column(db.BigInteger, nullable=False)   # dueño del micrositio
    client_user_id = db.Column(db.BigInteger)                  # null = anónimo

    channel = db.Column(db.String(20), default="dpia")         # dpia|wa|telegram...
    status = db.Column(db.String(20), default="open")          # open|closed|snoozed

    a_ver = db.Column(db.Boolean, default=False)               # flag sensible
    auto_mode = db.Column(db.String(10), default="auto")       # interno: auto|copilot|manual
    ia_active = db.Column(db.Boolean, default=True)

    summary_json = db.Column(db.JSON)                          # resumen activo
    ai_confidence_avg = db.Column(db.Float)                    # métrica simple
    sentiment_last = db.Column(db.String(20))
    publicacion_id = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime, server_default=db.func.now(), onupdate=db.func.now()
    )

    # =========================
    # ⭐ STAR: Marcar conversación como favorita
    # =========================
    is_starred = db.Column(db.Boolean, default=False, index=True)
    starred_at = db.Column(db.DateTime, nullable=True)  # cuándo se marcó como favorita
