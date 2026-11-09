from flask import Blueprint
from utils.db import db, ma
from sqlalchemy import Column, Integer, String, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy import inspect
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema



image = Blueprint('image', __name__)

class Image(db.Model):
    __tablename__ = 'image'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id = db.Column(db.Integer)
    title = db.Column(db.String(255), unique=True, nullable=False)
    description = db.Column(db.String(255), nullable=False)   
    colorDescription = db.Column(db.String(255), nullable=False) 
    filepath = db.Column(db.String(500), nullable=True)
    randomNumber = db.Column(db.Integer)
    size = db.Column(db.Float)
    mimetype = db.Column(db.String(255), nullable=True)
    
   

    def __init__(self, user_id, title, description, filepath, randomNumber, colorDescription, size,mimetype):
        self.user_id = user_id
        self.title = title
        self.description = description
        self.filepath = filepath
        self.randomNumber = randomNumber
        self.colorDescription = colorDescription
        self.size = size   
        self.mimetype = mimetype 

   
    def __repr__(self):
        return f"Imagen(id={self.id}, user_id={self.user_id}, title={self.title}, description={self.description}, filepath={self.filepath}, randomNumber={self.randomNumber}, colorDescription={self.colorDescription}, size={self.size}, mimetype={self.mimetype})"

    @classmethod
    def crear_tabla_image(cls):
        insp = inspect(db.engine)
        if not insp.has_table("image"):
            cls.__table__.create(db.engine)

class MerShema(SQLAlchemyAutoSchema):
    class Meta:
        model = Image  # Indica que este esquema está basado en el modelo Image
        load_instance = True  # Permite que las instancias de modelos se carguen directamente
        sqla_session = db.session  # Si usas un `db.session` específico, configúralo aquí

# Instancia del esquema
mer_schema = MerShema()
mer_schema_many = MerShema(many=True)  # Para manejar varias instancias de Image