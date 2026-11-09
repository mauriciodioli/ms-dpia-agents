from utils.db import db

class ChatScope(db.Model):
    __tablename__ = "chat_scope"

    id = db.Column(db.BigInteger, primary_key=True)

    # Contexto básico
    dominio = db.Column(db.String(120), nullable=False)

    ambito_id = db.Column(db.BigInteger, nullable=True)
    categoria_id = db.Column(db.BigInteger, nullable=True)

    # 👇 CP textual (ej: "52-200") y opcionalmente el ID numérico
    codigo_postal = db.Column(db.String(20), nullable=True)      # "52-200"
    codigo_postal_id = db.Column(db.BigInteger, nullable=True)   # FK si lo tenés

    locale = db.Column(db.String(10), nullable=False)  # ej: "es", "pl", "it-IT"

    # Pueden existir scopes sin una publicación concreta
    publicacion_id = db.Column(db.Integer, nullable=True)
    owner_user_id  = db.Column(db.BigInteger, nullable=True)

    # Hash único del contexto
    hash_contextid = db.Column(
        db.String(64),
        nullable=False,
        unique=True,
        index=True
    )

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime,
        server_default=db.func.now(),
        onupdate=db.func.now()
    )

    __table_args__ = (
        # Índice útil para búsquedas por contexto
        db.Index(
            "ix_chat_scope_ctx",
            "dominio",
            "ambito_id",
            "categoria_id",
            "codigo_postal_id",
            "locale",
        ),
    )
