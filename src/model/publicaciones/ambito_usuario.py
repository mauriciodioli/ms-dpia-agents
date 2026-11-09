from flask import Blueprint
from utils.db import db, ma
from sqlalchemy import inspect, Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship




ambito_usuario = Blueprint('ambito_usuario', __name__)


class Ambito_usuario(db.Model):
    __tablename__ = 'ambito_usuario'
    
    # Columnas de la tabla
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer, nullable=False)
    ambito_id = db.Column(db.Integer, nullable=False)
    publicacion_id = db.Column(db.Integer, nullable=True)
    estado = db.Column(db.String(500), nullable=True)
    
    
    # Constructor
    def __init__(self, ambito_id, user_id=None,publicacion_id=None,estado=None):      
        self.ambito_id = ambito_id        
        self.user_id = user_id
        self.publicacion_id = publicacion_id
        self.estado = estado
    
    def __repr__(self):
        return f"Ambito_usuario(id={self.id},ambito_id={self.ambito_id},publicacion_id={self.publicacion_id}, user_id={self.user_id}, estado={self.estado})"
                                                                                  
    
    @classmethod
    def crear_tabla_ambito_usuario(self):
        # Verificar si la tabla 'ambitos' existe antes de crearla
        insp = inspect(db.engine)
        if not insp.has_table("ambito_usuario"):
            db.create_all()



# Schema de Marshmallow para serialización
class MerShema(ma.Schema):
    class Meta:       
        fields = ("id", "ambito_id", "user_id","publicacion_id","estado")  # Campos a serializar

