from flask import Blueprint
from utils.db import db, ma
from sqlalchemy import inspect


codigoPostal = Blueprint('codigoPostal', __name__)

class CodigoPostal(db.Model):
    __tablename__ = 'codigo_postal'
    id = db.Column(db.Integer, primary_key=True)
    codigoPostal = db.Column(db.String(20), unique=True, nullable=False)
    ciudad = db.Column(db.String(100), nullable=True)
    pais = db.Column(db.String(100), nullable=True)

    def __init__(self, codigoPostal, ciudad=None, pais=None):
        self.codigoPostal = codigoPostal
        self.ciudad = ciudad
        self.pais = pais

    def __repr__(self):
        return f"<CodigoPostal id={self.id}, codigoPostal={self.codigoPostal}, ciudad={self.ciudad}, pais={self.pais}>"

    @classmethod
    def crear_tabla_si_no_existe(cls):
        insp = inspect(db.engine)
        if not insp.has_table(cls.__tablename__):
            db.create_all()


class MerShema(ma.Schema):
    class Meta:       
        fields =("id", "codigoPostal", "ciudad", "pais")# Campos a serializar


