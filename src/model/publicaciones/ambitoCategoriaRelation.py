from flask import Blueprint
from utils.db import db, ma
from sqlalchemy import inspect, Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship




ambitoCategoriaRelation = Blueprint('ambitoCategoriaRelation', __name__)


class AmbitoCategoriaRelation(db.Model):
    __tablename__ = 'ambitoCategoriaRelation'
    
    # Columnas de la tabla
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)    
    ambito_id = db.Column(db.Integer, nullable=False)   
    ambitoCategoria_id = db.Column(db.Integer, nullable=False)
    estado = db.Column(db.String(500), nullable=True)
    
    
    # Constructor
    def __init__(self, ambito_id,ambitoCategoria_id=None,estado=None):      
        self.ambito_id = ambito_id        
        self.ambitoCategoria_id = ambitoCategoria_id
        self.estado = estado
       
    
    def __repr__(self):
        return f"AmbitoCategoriaRelation(id={self.id},ambito_id={self.ambito_id},ambitoCategoria_id={self.ambitoCategoria_id}, estado={self.estado})"
                                                                                  
    
    @classmethod
    def crear_tabla_ambitoCategoriaRelation(self):
        # Verificar si la tabla 'ambitos' existe antes de crearla
        insp = inspect(db.engine)
        if not insp.has_table("ambitoCategoriaRelation"):
            db.create_all()



# Schema de Marshmallow para serialización
class MerShema(ma.Schema):
    class Meta:       
        fields = ("id", "ambito_id", "ambitoCategoria_id","estado" )  # Campos a serializar

