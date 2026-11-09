from utils.db import db

class CommEndpoint(db.Model):
    __tablename__ = "comm_endpoint"

    id = db.Column(db.BigInteger, primary_key=True)
    owner_user_id = db.Column(db.BigInteger, nullable=False)
    publicacion_id = db.Column(db.BigInteger)        # null = default del usuario

    tipo = db.Column(db.String(32), nullable=False)  # 'whatsapp'
    valor = db.Column(db.String(32), nullable=False) # E.164 sin '+'

    locale = db.Column(db.String(10))                # opcional
    categoria_id = db.Column(db.BigInteger)
    codigo_postal_id = db.Column(db.BigInteger)

    is_default = db.Column(db.Boolean, default=False)
    activo = db.Column(db.Boolean, default=True)
    tags = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, server_default=db.func.now())
    updated_at = db.Column(
        db.DateTime, server_default=db.func.now(), onupdate=db.func.now()
    )
