from flask import Blueprint
from utils.db import db, ma
from sqlalchemy import inspect, Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship




ambitos = Blueprint('ambitos', __name__)


class Ambitos(db.Model):
    __tablename__ = 'ambitos'
    
    # Columnas de la tabla
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)  
    nombre = db.Column(db.String(500), unique=True, nullable=False)
    descripcion = db.Column(db.String(500), nullable=True)
    idioma = db.Column(db.String(500), nullable=True)
    valor = db.Column(db.String(500), nullable=True)
    estado = db.Column(db.String(500), nullable=True)
    categoria_general_id = db.Column(db.Integer, db.ForeignKey('categoria_general.id'), nullable=True)
    categoria_general = relationship("CategoriaGeneral", lazy='joined')
   
    
    # Constructor
    def __init__(self, nombre, descripcion, idioma=None, valor=None, estado=None):
        self.nombre = nombre
        self.descripcion = descripcion
        self.idioma = idioma
        self.valor = valor
        self.estado = estado
    
    def __repr__(self):
        return f"Ambitos(id={self.id}, nombre={self.nombre}, descripcion={self.descripcion}, idioma={self.idioma}, valor={self.valor}, estado={self.estado})"
    
    @classmethod
    def crear_tabla_ambitos(self):
        # Verificar si la tabla 'ambitos' existe antes de crearla
        insp = inspect(db.engine)
        if not insp.has_table("ambitos"):
            db.create_all()



# Schema de Marshmallow para serialización
class MerShema(ma.Schema):
    class Meta:       
        fields = ("id", "nombre", "descripcion", "idioma", "valor", "estado")  # Campos a serializar


from model.publicaciones.categoria_general import CategoriaGeneral
from model.publicaciones.ambito_general import AmbitoGeneral