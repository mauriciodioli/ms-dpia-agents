from flask import Blueprint, request, jsonify
from utils.db import db, ma
from sqlalchemy import inspect
from sqlalchemy.sql import func


pushDevice = Blueprint('pushDevice', __name__)

class PushDevice(db.Model):
    __tablename__ = "push_device"

    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(20), nullable=False, index=True) # e.g., 'android', 'ios'
    fcm_token = db.Column(db.String(255), unique=True, nullable=False)


    user_id = db.Column(db.Integer, nullable=True)
    active = db.Column(db.Boolean, default=True)

    created_at = db.Column(db.DateTime, server_default=func.now())
    last_seen = db.Column(db.DateTime, server_default=func.now(), onupdate=func.now())


    @classmethod
    def crear_tabla_push_device(cls):
        insp = inspect(db.engine)
        if not insp.has_table(cls.__tablename__):
            db.create_all()


class MerShema(ma.Schema):
    class Meta:
        fields = ("id", "platform", "fcm_token", "user_id", "active", "created_at", "last_seen")

