from flask import Blueprint
from utils.db import db, ma
from sqlalchemy import inspect
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Integer, String, ForeignKey
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema




publicaciones = Blueprint('publicaciones', __name__)

class Publicacion(db.Model):
    __tablename__ = 'publicacion'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey('usuarios.id'))   
    titulo = db.Column(db.String(120), unique=True, nullable=False)
    texto = db.Column(db.Text, nullable=False)
    ambito = db.Column(db.String(120), nullable=False)
    categoria_id = db.Column(db.Integer, nullable=True)
    correo_electronico = db.Column(db.String(120), nullable=False)
    descripcion = db.Column(db.String(1000), nullable=False)
    color_texto = db.Column(db.String(120), nullable=False)
    color_titulo = db.Column(db.String(120), nullable=False)
    fecha_creacion = db.Column(db.DateTime)
    estado = db.Column(db.String(120), nullable=False)
    botonCompra = db.Column(db.Boolean, default=False)
    imagen = db.Column(db.String(255), nullable=True)
    idioma = db.Column(db.String(255), nullable=True)
    codigo_postal_id = db.Column(db.Integer, nullable=True)
    codigoPostal = db.Column(db.String(255), nullable=True)
    pagoOnline = db.Column(db.Boolean, default=True)
    afiliado_link = db.Column(db.String(500), nullable=True)
    # NUEVOS CAMPOS
    precio = db.Column(db.Float, nullable=True)
    moneda = db.Column(db.String(10), nullable=True)
    

    def __init__(
        self, user_id, titulo, texto, ambito, categoria_id, correo_electronico,
        descripcion, color_texto, color_titulo, fecha_creacion, estado,
        codigoPostal, pagoOnline,afiliado_link,  botonCompra=False, imagen=None,
        idioma=None, precio=None, moneda=None
    ):
        self.user_id = user_id       
        self.titulo = titulo
        self.texto = texto
        self.ambito = ambito
        self.categoria_id = categoria_id
        self.correo_electronico = correo_electronico
        self.descripcion = descripcion
        self.color_texto = color_texto
        self.color_titulo = color_titulo
        self.fecha_creacion = fecha_creacion
        self.estado = estado
        self.botonCompra = botonCompra
        self.imagen = imagen
        self.idioma = idioma
        self.codigoPostal = codigoPostal
        self.pagoOnline = pagoOnline
        self.precio = precio
        self.moneda = moneda
        self.afiliado_link = afiliado_link

    def __repr__(self):
        return (
            f"Publicacion(id={self.id}, user_id={self.user_id}, titulo={self.titulo}, "
            f"texto={self.texto}, ambito={self.ambito}, categoria_id={self.categoria_id}, "
            f"correo_electronico={self.correo_electronico}, descripcion={self.descripcion}, "
            f"color_texto={self.color_texto}, color_titulo={self.color_titulo}, "
            f"fecha_creacion={self.fecha_creacion}, botonCompra={self.botonCompra}, "
            f"imagen={self.imagen}, idioma={self.idioma}, codigoPostal={self.codigoPostal}, "
            f"afiliado_link={self.afiliado_link}, estado={self.estado}, "
            f"pagoOnline={self.pagoOnline}, precio={self.precio}, moneda={self.moneda}"
        )
        
    @classmethod
    def crear_tabla_publicacion(cls):
        insp = inspect(db.engine)
        if not insp.has_table("publicaciones"):
            db.create_all()
            
class MerShema(SQLAlchemyAutoSchema):
    class Meta:
        model = Publicacion  # Indica que este esquema está basado en el modelo Image
        load_instance = True  # Permite que las instancias de modelos se carguen directamente
        sqla_session = db.session  # Si usas un `db.session` específico, configúralo aquí

# Instancia del esquema
mer_schema = MerShema()
