from flask import Blueprint
from utils.db import db, ma
from sqlalchemy import inspect, Column, Integer, String




categoriaCodigoPostal = Blueprint('categoriaCodigoPostal', __name__)


class CategoriaCodigoPostal(db.Model):
    __tablename__ = 'categoriaCodigoPostal'

    # Columnas de la tabla
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)   
    estado = db.Column(db.String(500), nullable=True)
    codigo_postal_id = db.Column(db.Integer, db.ForeignKey('codigo_postal.id'), nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey('ambitoCategoria.id'), nullable=False)
    # Constructor
    def __init__(self, categoria_id, codigo_postal_id, estado=None):
        self.categoria_id = categoria_id
        self.codigo_postal_id = codigo_postal_id
        self.estado = estado

    def __repr__(self):
        return f"CategoriaCodigoPostal(id={self.id}, categoria_id={self.categoria_id}, codigo_postal_id={self.codigo_postal_id}, estado={self.estado})"

    @classmethod
    def crear_tabla_categoriaCodigoPostal(self):
        # Verificar si la tabla existe antes de crearla
        insp = inspect(db.engine) 
        if not insp.has_table("categoriaCodigoPostal"):
            db.create_all()




# Schema de Marshmallow para serialización
class MerShema(ma.Schema):
    class Meta:       
        fields = ("id", "categoria_id", "codigo_postal_id","estado" )  # Campos a serializar