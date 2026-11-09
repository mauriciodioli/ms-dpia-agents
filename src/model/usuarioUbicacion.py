from flask import Blueprint
from utils.db import db, ma
from sqlalchemy import inspect, Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from model.usuario import Usuario
from model.usuarioRegion import UsuarioRegion




usuarioUbicacion = Blueprint('usuarioUbicacion', __name__)

class UsuarioUbicacion(db.Model):
    __tablename__ = 'usuarioUbicacion'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer,  nullable=False)  # Relación con Usuario
    id_region = db.Column(db.Integer,  nullable=False)  # Relación con UsuarioRegion   
    codigoPostal = db.Column(db.String(120), nullable=False)
    latitud = db.Column(db.Float, nullable=False)
    longitud = db.Column(db.Float, nullable=False)

    # constructor
    def __init__(self, user_id, id_region, codigoPostal, latitud, longitud):
        self.user_id = user_id
        self.id_region = id_region       
        self.codigoPostal = codigoPostal
        self.latitud = latitud
        self.longitud = longitud

    def __repr__(self):
        return f"UsuarioUbicacion(id={self.id}, user_id={self.user_id},id_region={self.id_region}, codigoPostal={self.codigoPostal}, latitud={self.latitud}, longitud={self.longitud})"

    @classmethod
    def crear_tabla_usuarioUbicacion(cls):
        insp = inspect(db.engine)
        if not insp.has_table(cls.__tablename__):  # Usar el nombre de la tabla de la clase
            db.create_all()

class MerShema(ma.SQLAlchemyAutoSchema):  # Usar SQLAlchemyAutoSchema para mayor comodidad
    class Meta:
        model = UsuarioUbicacion  # Especificamos que el schema está basado en la clase UsuarioRegion
        fields = ("id", "user_id","id_region" ,"codigoPostal", "latitud", "longitud")

mer_schema = MerShema()
mer_shema = MerShema(many=True)  # Corregido el nombre del objeto


