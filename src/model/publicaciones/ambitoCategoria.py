from flask import Blueprint
from utils.db import db, ma
from sqlalchemy import inspect, Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship




ambitoCategoria = Blueprint('ambitoCategoria', __name__)


class AmbitoCategoria(db.Model):
    __tablename__ = 'ambitoCategoria'
    
    # Columnas de la tabla
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)  
    nombre = db.Column(db.String(500), unique=True, nullable=False)
    descripcion = db.Column(db.String(500), nullable=True)
    idioma = db.Column(db.String(500), nullable=True)
    valor = db.Column(db.String(500), nullable=True)
    color = db.Column(db.String(50), nullable=True)
    estado = db.Column(db.String(500), nullable=True)
    categoria_general_id = db.Column(db.Integer, db.ForeignKey("categoria_general.id"), nullable=True)
    categoria_general = relationship("CategoriaGeneral", lazy='joined')
    # Constructor
    def __init__(self, nombre, descripcion,color, idioma=None, valor=None, estado=None, categoria_general_id=None):
        self.nombre = nombre
        self.descripcion = descripcion
        self.idioma = idioma
        self.valor = valor
        self.color = color
        self.estado = estado
        self.categoria_general_id = categoria_general_id
       
    
    def __repr__(self):
        return f"AmbitoCategoria(id={self.id}, nombre={self.nombre}, descripcion={self.descripcion}, idioma={self.idioma},color={self.color}, valor={self.valor}, estado={self.estado} , categoria_general_id={self.categoria_general_id})"
    
    @classmethod
    def crear_tabla_ambitoCategoria(self):
        # Verificar si la tabla 'ambitos' existe antes de crearla
        insp = inspect(db.engine)
        if not insp.has_table("ambitoCategoria"):
            db.create_all()



# Schema de Marshmallow para serialización
class MerShema(ma.Schema):
    class Meta:       
        fields = ("id", "nombre", "descripcion", "idioma", "color", "valor", "estado")
  # Campos a serializar


from model.publicaciones.categoria_general import CategoriaGeneral
from model.publicaciones.ambito_general import AmbitoGeneral