# Creating  Routes
from flask_marshmallow import Marshmallow
from flask import Blueprint
from utils.db import db
import unidecode
import re




ambito_general = Blueprint('ambito_general', __name__)
# =======================
# Ámbitos
# =======================
class AmbitoGeneral(db.Model):
    __tablename__ = 'ambito_general'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(255), unique=True, nullable=False)
    descripcion = db.Column(db.String(255), nullable=True)

    traducciones = db.relationship('AmbitoTraduccion', backref='ambito', lazy=True)


class AmbitoTraduccion(db.Model):
    __tablename__ = 'ambito_traduccion'

    id = db.Column(db.Integer, primary_key=True)
    ambito_id = db.Column(db.Integer, db.ForeignKey('ambito_general.id'), nullable=False)
    idioma = db.Column(db.String(5), nullable=False)
    valor = db.Column(db.String(255), nullable=False)



# =======================
# Funciones auxiliares
# =======================


def normalizar_slug(texto):
    texto = texto.strip().lower()
    texto = unidecode.unidecode(texto)
    texto = re.sub(r'[^a-z0-9\s-]', '', texto)
    texto = re.sub(r'\s+', '-', texto)
    return texto.strip('-')


def get_or_create_ambito(valor_original, idioma):
    slug = normalizar_slug(valor_original)
    ambito = db.session.query(AmbitoGeneral).filter_by(slug=slug).first()
    if not ambito:
        ambito = AmbitoGeneral(slug=slug)
        db.session.add(ambito)
        db.session.flush()

    traduccion = db.session.query(AmbitoTraduccion).filter_by(ambito_id=ambito.id, idioma=idioma).first()
    if not traduccion:
        nueva = AmbitoTraduccion(ambito_id=ambito.id, idioma=idioma, valor=valor_original.strip())
        db.session.add(nueva)
    return ambito.id