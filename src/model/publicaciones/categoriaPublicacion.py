from flask import Blueprint
from utils.db import db, ma
from sqlalchemy import inspect, Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship




categoriaPublicacion = Blueprint('categoriaPublicacion', __name__)


class CategoriaPublicacion(db.Model):
    __tablename__ = 'categoriaPublicacion'
    
    # Columnas de la tabla
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)    
    categoria_id = db.Column(db.Integer, nullable=False)   
    publicacion_id = db.Column(db.Integer, nullable=False)
    estado = db.Column(db.String(500), nullable=True)
    
    
    # Constructor
    def __init__(self, categoria_id,publicacion_id=None,estado=None):      
        self.categoria_id = categoria_id        
        self.publicacion_id = publicacion_id
        self.estado = estado
       
    
    def __repr__(self):
        return f"CategoriaPublicacion(id={self.id},categoria_id={self.categoria_id},publicacion_id={self.publicacion_id}, estado={self.estado})"
                                                                                  
    
    @classmethod
    def crear_tabla_categoriaPublicacion(self):
        # Verificar si la tabla 'ambitos' existe antes de crearla
        insp = inspect(db.engine)
        if not insp.has_table("categoriaPublicacion"):
            db.create_all()



# Schema de Marshmallow para serialización
class MerShema(ma.Schema):
    class Meta:       
        fields = ("id", "categoria_id", "publicacion_id","estado")  # Campos a serializar

