# Creating  Routes
from utils.db import db
import unidecode
import re

# =======================
# Categorías
# =======================

class CategoriaGeneral(db.Model):
    __tablename__ = 'categoria_general'

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(255), unique=True, nullable=False)
    descripcion = db.Column(db.String(255), nullable=True)
    color = db.Column(db.String(50), nullable=True)

    traducciones = db.relationship('CategoriaTraduccion', backref='categoria', lazy=True)


class CategoriaTraduccion(db.Model):
    __tablename__ = 'categoria_traduccion'

    id = db.Column(db.Integer, primary_key=True)
    categoria_id = db.Column(db.Integer, db.ForeignKey('categoria_general.id'), nullable=False)
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

def get_or_create_categoria(valor_original, idioma):
    slug = normalizar_slug(valor_original)
    categoria = db.session.query(CategoriaGeneral).filter_by(slug=slug).first()
    if not categoria:
        categoria = CategoriaGeneral(slug=slug)
        db.session.add(categoria)
        db.session.flush()

    traduccion = db.session.query(CategoriaTraduccion).filter_by(categoria_id=categoria.id, idioma=idioma).first()
    if not traduccion:
        nueva = CategoriaTraduccion(categoria_id=categoria.id, idioma=idioma, valor=valor_original.strip())
        db.session.add(nueva)
    return categoria.id
