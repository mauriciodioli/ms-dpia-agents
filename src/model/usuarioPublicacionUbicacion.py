from flask import Blueprint
from utils.db import db, ma
from sqlalchemy import inspect, Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from model.usuario import Usuario
from model.usuarioRegion import UsuarioRegion




usuarioPublicacionUbicacion = Blueprint('usuarioPublicacionUbicacion', __name__)

class UsuarioPublicacionUbicacion(db.Model):
    __tablename__ = 'usuarioPublicacionUbicacion'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer,  nullable=False)  # Relación con Usuario
    id_region = db.Column(db.Integer,  nullable=False)  # Relación con UsuarioRegion
    id_publicacion = db.Column(db.Integer,  nullable=False)  # Relación con Publicacion
    id_ubicacion = db.Column(db.Integer,  nullable=False)  # Relación con UsuarioUbicacion
    codigoPostal = db.Column(db.String(120), nullable=False)
   

    # constructor
    def __init__(self, user_id, id_region, id_publicacion, id_ubicacion, codigoPostal):
        self.user_id = user_id
        self.id_region = id_region
        self.id_publicacion = id_publicacion
        self.id_ubicacion = id_ubicacion
        self.codigoPostal = codigoPostal

    def __repr__(self):
        return f"UsuarioPublicacionUbicacion(id={self.id}, user_id={self.user_id},id_region={self.id_region}, id_publicacion={self.id_publicacion}, id_ubicacion={self.id_ubicacion}, codigoPostal={self.codigoPostal})"

    @classmethod
    def crear_tabla_usuarioPublicacionUbicacion(cls):
        insp = inspect(db.engine)
        if not insp.has_table(cls.__tablename__):  # Usar el nombre de la tabla de la clase
            db.create_all()

class MerShema(ma.SQLAlchemyAutoSchema):  # Usar SQLAlchemyAutoSchema para mayor comodidad
    class Meta:
        model = UsuarioPublicacionUbicacion  # Especificamos que el schema está basado en la clase UsuarioRegion
        fields = ("id", "user_id","id_region" ,"id_publicacion", "id_ubicacion", "codigoPostal")

mer_schema = MerShema()
mer_shema = MerShema(many=True)  # Corregido el nombre del objeto


