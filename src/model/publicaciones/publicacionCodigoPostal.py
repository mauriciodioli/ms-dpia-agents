from flask import Blueprint
from utils.db import db, ma
from sqlalchemy import inspect, Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship




publicacionCodigoPostal = Blueprint('publicacionCodigoPostal', __name__)


class PublicacionCodigoPostal(db.Model):
    __tablename__ = 'publicacionCodigoPostal'
    
    # Columnas de la tabla
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)      
    publicacion_id = db.Column(db.Integer, nullable=False)
    codigoPostal_id = db.Column(db.Integer, nullable=False)    
    estado = db.Column(db.String(500), nullable=True)
    
    
    # Constructor
    def __init__(self, publicacion_id, codigoPostal_id, estado=None):
        self.publicacion_id = publicacion_id
        self.codigoPostal_id = codigoPostal_id
        self.estado = estado      
       
    
    def __repr__(self):
        return f"PublicacionCodigoPostal(id={self.id},publicacion_id={self.publicacion_id}, codigoPostal_id={self.codigoPostal_id}, estado={self.estado})"
                                                                                  
    
    @classmethod
    def crear_tabla_publicacionCodigoPostal(self):
        # Verificar si la tabla 'ambitos' existe antes de crearla
        insp = inspect(db.engine)
        if not insp.has_table("publicacionCodigoPostal"):
            db.create_all()



# Schema de Marshmallow para serialización
class MerShema(ma.Schema):
    class Meta:       
        fields = ("id", "ambito_id", "publicacion_id","estado")  # Campos a serializar

