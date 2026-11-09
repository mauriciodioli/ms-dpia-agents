# models/usuario.py

from flask import Blueprint
from utils.db import db, ma
from sqlalchemy import inspect
from datetime import datetime



usuario = Blueprint('usuario', __name__)


class Usuario(db.Model):
    __tablename__ = 'usuarios'

    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    correo_electronico = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.LargeBinary(128), nullable=True)
    token = db.Column(db.String(500), nullable=True)
    roll = db.Column(db.String(20), nullable=False, default='regular')
    refresh_token = db.Column(db.String(500), nullable=True)
    calendly_url = db.Column(db.String(255), nullable=True)
    google_id = db.Column(db.String(255), unique=True, nullable=True)
    google_email = db.Column(db.String(120), nullable=True)
    google_picture = db.Column(db.String(500), nullable=True)
    auth_provider = db.Column(db.String(20), nullable=True, default='email')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    ambito_principal_id = db.Column(db.Integer, nullable=True)

    def __init__(self, correo_electronico, password=None, roll='regular',
                 activo=True, auth_provider='email', google_id=None,
                 google_email=None, google_picture=None):
        self.correo_electronico = correo_electronico
        self.password = password
        self.roll = roll
        self.activo = activo
        self.auth_provider = auth_provider
        self.google_id = google_id
        self.google_email = google_email
        self.google_picture = google_picture

    def is_authenticated(self):
        return True

    def is_active(self):
        return self.activo

    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)

    def __repr__(self):
        return f"<Usuario {self.correo_electronico} ({self.roll})>"

    @classmethod
    def crear_tabla_usuarios(cls):
        insp = inspect(db.engine)
        if not insp.has_table("usuarios"):
            db.create_all()
            print("✅ Tabla 'usuarios' creada")
        else:
            print("ℹ️ Tabla 'usuarios' ya existe")


# ===== SCHEMA CORREGIDO =====
class UsuarioSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = Usuario
        load_instance = True
        sqla_session = db.session
        # ✅ ESPECIFICAR EXPLÍCITAMENTE los campos que quieres mostrar
        # NO incluir password, token, refresh_token (son sensibles)
        fields = (
            'id',
            'activo',
            'correo_electronico',
            'roll',
            'calendly_url',
            'google_id',
            'google_email',
            'google_picture',
            'auth_provider',
            'updated_at',
            'ambito_principal_id'
        )


# ===== INSTANCIAS DEL SCHEMA =====
usuario_schema = UsuarioSchema()
usuarios_schema = UsuarioSchema(many=True)
