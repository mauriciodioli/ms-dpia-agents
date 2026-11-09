from flask import Blueprint, request, jsonify
from utils.db import db, ma
from sqlalchemy import inspect
from sqlalchemy.sql import func


push = Blueprint('push', __name__)

class PushSubscription(db.Model):
    __tablename__ = 'push_subscription'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    user_id = db.Column(db.Integer, nullable=False, unique=True, index=True)

    endpoint = db.Column(db.Text, nullable=False)
    p256dh = db.Column(db.String(255), nullable=False)
    auth = db.Column(db.String(255), nullable=False)

    created_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)
    updated_at = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    @classmethod
    def crear_tabla_push_subscription(cls):
        insp = inspect(db.engine)
        if not insp.has_table(cls.__tablename__):
            db.create_all()


class Meta(ma.Schema):
    class Meta:
        fields = ("id", "user_id", "endpoint", "p256dh", "auth", "created_at", "updated_at")


