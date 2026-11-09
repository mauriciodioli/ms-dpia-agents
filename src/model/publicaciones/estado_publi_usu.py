from flask import Blueprint
from utils.db import db, ma
from sqlalchemy import inspect, Enum
from sqlalchemy.orm import relationship



estado_publi_usu = Blueprint('estado_publi_usu', __name__)

class Estado_publi_usu(db.Model):
    __tablename__ = 'estado_publi_usu'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    publicacion_id = db.Column(db.Integer, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)
    estado = db.Column(db.String(500), nullable=False)
    visto = db.Column(db.Boolean, nullable=False)
    gusto = db.Column(db.String(500), nullable=False)
    tiempo_visto = db.Column(db.String(500), nullable=False)
    fecha_visto = db.Column(db.Date(), nullable=False) 
    fecha_eliminado = db.Column(db.Date(), nullable=False)
    fecha_gustado = db.Column(db.Date(), nullable=False)
    
    def __init__(self, publicacion_id, user_id, estado, visto, gusto, tiempo_visto, fecha_visto, fecha_eliminado, fecha_gustado):
        self.publicacion_id = publicacion_id
        self.user_id = user_id
        self.estado = estado
        self.visto = visto
        self.gusto = gusto
        self.tiempo_visto = tiempo_visto
        self.fecha_visto = fecha_visto
        self.fecha_eliminado = fecha_eliminado
        self.fecha_gustado = fecha_gustado

    def __repr__(self):
        return (f"Estado_publi_usu(id={self.id}, publicacion_id={self.publicacion_id}, "
                f"user_id={self.user_id}, estado={self.estado}, visto={self.visto}, "
                f"gusto={self.gusto}, tiempo_visto={self.tiempo_visto}, "
                f"fecha_visto={self.fecha_visto}, fecha_eliminado={self.fecha_eliminado}, "
                f"fecha_gustado={self.fecha_gustado})")

    @classmethod
    def crear_tabla_estado_publi_usu(cls):
        # Get the inspector object for the database engine
        insp = inspect(db.engine)
        # Check if the table already exists
        if not insp.has_table("estado_publi_usu"):
            # If the table does not exist, create it
            cls.__table__.create(db.engine)

class EstadoPubliUsuSchema(ma.SQLAlchemyAutoSchema):
    class Meta:
        model = Estado_publi_usu
        fields = ("id", "publicacion_id", "user_id", "estado", "visto", "gusto", "tiempo_visto", "fecha_visto", "fecha_eliminado", "fecha_gustado")


