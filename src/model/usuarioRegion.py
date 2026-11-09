from flask import Blueprint
from utils.db import db, ma
from sqlalchemy import inspect, Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship

from model.usuario import Usuario




usuarioRegion = Blueprint('usuarioRegion', __name__)

class UsuarioRegion(db.Model):
    __tablename__ = 'usuarioRegion'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer,  nullable=False)  # Relación con Usuario
    idioma = db.Column(db.String(120), nullable=False)
    codigoPostal = db.Column(db.String(120), nullable=False)
    pais = db.Column(db.String(120), nullable=False)
    region = db.Column(db.String(120), nullable=False)
    provincia = db.Column(db.String(120), nullable=False)
    ciudad = db.Column(db.String(120), nullable=False)
    

    # constructor
    def __init__(self, user_id, idioma, codigoPostal, pais, region, provincia, ciudad):
        self.user_id = user_id
        self.idioma = idioma
        self.codigoPostal = codigoPostal
        self.pais = pais
        self.region = region
        self.provincia = provincia
        self.ciudad = ciudad

    def __repr__(self):
        return f"UsuarioRegion(id={self.id}, user_id={self.user_id}, idioma={self.idioma}, codigoPostal={self.codigoPostal}, pais={self.pais}, region={self.region}, provincia={self.provincia}, ciudad={self.ciudad})"

    @classmethod
    def crear_tabla_usuarioRegion(cls):
        insp = inspect(db.engine)
        if not insp.has_table(cls.__tablename__):  # Usar el nombre de la tabla de la clase
            db.create_all()

class MerShema(ma.SQLAlchemyAutoSchema):  # Usar SQLAlchemyAutoSchema para mayor comodidad
    class Meta:
        model = UsuarioRegion  # Especificamos que el schema está basado en la clase UsuarioRegion
        fields = ("id", "user_id", "idioma", "codigoPostal", "pais", "region", "provincia", "ciudad")

mer_schema = MerShema()
mer_shema = MerShema(many=True)  # Corregido el nombre del objeto


