# models/chats/user_activity.py

from datetime import datetime
from sqlalchemy import inspect
from utils.db import db




class UserActivity(db.Model):
    __tablename__ = "user_activity"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(
        db.Integer,
        nullable=False,
        index=True
    )

    last_seen_at = db.Column(
        db.DateTime,
        nullable=False,
        default=datetime.now(),
        index=True
    )

    device_id = db.Column(
        db.String(128),
        nullable=True
    )

    source = db.Column(
        db.String(32),   # web / pwa / android
        default="web"
    )

    ip = db.Column(
        db.String(45)
    )

    created_at = db.Column(
        db.DateTime,
        default=datetime.now()
    )

    def __repr__(self):
        return f"<UserActivity user_id={self.user_id} last_seen_at={self.last_seen_at}>"


    # ✅ Crear tabla si no existe
    @classmethod
    def crear_tabla_user_activity(cls):
        insp = inspect(db.engine)
        if not insp.has_table(cls.__tablename__):
            db.create_all()