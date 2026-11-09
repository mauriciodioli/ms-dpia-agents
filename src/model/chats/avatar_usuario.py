from datetime import datetime
from sqlalchemy import inspect
from utils.db import db

class AvatarUsuario(db.Model):

    __tablename__ = "avatar_usuario"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        db.ForeignKey("usuarios.id"),
        nullable=False,
        unique=True
    )

    bucket = db.Column(db.String(50))
    blob_name = db.Column(db.String(255))
    public_url = db.Column(db.Text)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<AvatarUsuario user_id={self.user_id}>"

    @classmethod
    def crear_tabla_avatar_usuario(cls):
        insp = inspect(db.engine)
        if not insp.has_table(cls.__tablename__):
            db.create_all()
