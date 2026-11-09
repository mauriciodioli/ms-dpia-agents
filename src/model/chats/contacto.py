# src/model/chats/contacto.py
from datetime import datetime
from sqlalchemy import inspect
from utils.db import db, ma
from model.codigoPostal import CodigoPostal
from model.publicaciones.publicaciones import Publicacion



TIPOS_VALIDOS = {"whatsapp", "phone", "telegram", "email", "url"}

class Contacto(db.Model):
    __tablename__ = 'contacto'

    id               = db.Column(db.Integer, primary_key=True)
    user_id          = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, index=True)

    # Mantener según tu modelo real de Publicacion
    publicacion_id   = db.Column(db.Integer, db.ForeignKey('publicacion.id'), nullable=True, index=True)

    tipo             = db.Column(db.String(20),  nullable=False, index=True)   # whatsapp|phone|telegram|email|url
    valor            = db.Column(db.String(256), nullable=False)               # E.164 / mail / @handle / URL

    codigo_postal_id = db.Column(db.Integer, db.ForeignKey('codigo_postal.id'), nullable=True, index=True)

    # ✅ FKs (nombres sin "rel", tablas reales)
    ambito_id        = db.Column(db.Integer,    nullable=True, index=True)
    categoria_id     = db.Column(db.Integer,  nullable=True, index=True)

    is_primary       = db.Column(db.Boolean, default=False, nullable=False, index=True)
    is_active        = db.Column(db.Boolean, default=True,  nullable=False, index=True)

    # Usar callables (no llames now() al importar)
    created_at       = db.Column(db.DateTime, default=datetime.now, nullable=False)
    updated_at       = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("user_id","publicacion_id","tipo","valor", name="uix_contacto_basico"),
        db.Index("ix_contacto_resolver", "user_id","tipo","publicacion_id","is_primary","is_active"),
    )

    # Relaciones mínimas (no toco nombres de otras clases)
    usuario        = db.relationship("Usuario", backref="contactos", lazy=True)
    publicacion    = db.relationship("Publicacion", backref="contactos", lazy=True)
    codigo_postal  = db.relationship("CodigoPostal", backref="contactos", lazy=True)

    def __init__(self, user_id, tipo, valor, publicacion_id=None,
                 codigo_postal_id=None, ambito_id=None, categoria_id=None,
                 is_primary=False, is_active=True):
        if tipo not in TIPOS_VALIDOS:
            raise ValueError(f"tipo inválido: {tipo}")
        self.user_id = user_id
        self.publicacion_id = publicacion_id
        self.tipo = tipo
        self.valor = valor
        self.codigo_postal_id = codigo_postal_id
        self.ambito_id = ambito_id
        self.categoria_id = categoria_id
        self.is_primary = is_primary
        self.is_active = is_active

    def __repr__(self):
        return f"<Contacto id={self.id} user={self.user_id} tipo={self.tipo} valor={self.valor}>"

    @classmethod
    def crear_tabla_contacto(cls):
        insp = inspect(db.engine)
        if not insp.has_table(cls.__tablename__):
            db.create_all()


# ===== Schema =====
class ContactoSchema(ma.SQLAlchemySchema):
    class Meta:
        model = Contacto
        load_instance = True

    id = ma.auto_field()
    user_id = ma.auto_field()
    publicacion_id = ma.auto_field()
    tipo = ma.auto_field()
    valor = ma.auto_field()
    codigo_postal_id = ma.auto_field()
    ambito_id = ma.auto_field()
    categoria_id = ma.auto_field()
    is_primary = ma.auto_field()
    is_active = ma.auto_field()
    created_at = ma.auto_field()
    updated_at = ma.auto_field()

contacto_schema  = ContactoSchema()
contactos_schema = ContactoSchema(many=True)
