from flask import Blueprint, render_template, request, current_app, redirect, url_for, flash, jsonify
from utils.db import db
from utils.db_session import get_db_session
from sqlalchemy import func
from model.usuario import Usuario
from sqlalchemy.exc import SQLAlchemyError
from model.publicaciones.publicaciones import Publicacion
from model.publicaciones.estado_publi_usu import Estado_publi_usu
from model.publicaciones.publicacion_imagen_video import Public_imagen_video
from model.usuarioRegion import UsuarioRegion
from model.usuarioUbicacion import UsuarioUbicacion
from model.usuarioPublicacionUbicacion import UsuarioPublicacionUbicacion
from model.publicaciones.ambitoCategoria import AmbitoCategoria
from model.publicaciones.categoriaPublicacion import CategoriaPublicacion
from model.publicaciones.publicacionCodigoPostal import PublicacionCodigoPostal
from model.publicaciones.ambitos import Ambitos
from model.publicaciones.ambito_usuario import Ambito_usuario
from model.publicaciones.ambitoCategoriaRelation import AmbitoCategoriaRelation
from model.categoriaCodigoPostal import CategoriaCodigoPostal
from model.publicaciones.categoria_general import CategoriaGeneral, CategoriaTraduccion, normalizar_slug
from model.image import Image
from model.video import Video
from model.codigoPostal import CodigoPostal
from model.publicaciones.ambito_general import get_or_create_ambito
from sqlalchemy import and_
import os
import random
import re
from datetime import datetime
from werkzeug.utils import secure_filename

publicaciones = Blueprint('publicaciones', __name__)
SHEET_ID_DETECTOR_TENDENCIA = os.environ.get('SHEET_ID_DETECTOR_TENDENCIA')
# Completar la publicación con datos del sheet y base de datos
def completar_publicaciones(data, *, solo_base_datos=True):
    # La API solicita IDs confirmados y sincroniza Sheet/JSON tras el commit.
    publicaciones_completas = []
    publicaciones_ids = []
    ciudad = data[0]["pais_scrapeado"] if data else None

    if not solo_base_datos:
        raise ValueError("La PWA admite únicamente publicaciones en base de datos, sin Sheets.")

    try:
        with get_db_session() as session:
            for row in data:
                # === Extraer datos ===
                producto = row["Producto"]
                categoria = row["Categoría"]
                pais = row["País"]
                motivo_tendencia = row["Motivo de tendencia"]
                descripcion = row["descripcion"]
                precio_amazon = str(row["precio_amazon"])
                precio_ebay = str(row["precio_ebay"])
                precio_aliexpress = str(row["precio_aliexpress"])
                precio_venta_sugerido = row["precio_venta_sugerido"]
                margen_estimado = row["margen_estimado"]
                fecha = row["fecha"]
                motivo_tendencia_extendido = row["motivo_tendencia_extendido"]
                codigo_postal = row["codigoPostal"]
                user_id = int(row["usuario"])
                estado = row["estado"]
                boton_compra = 1 if str(row["botonCompra"]).strip().upper() == "TRUE" else 0
                idioma = row["idioma"]
                pago_online = 1 if str(row["pagoOnline"]).strip().upper() == "TRUE" else 0
                ambito = row["ambito"]
                afiliado_link = row["afiliado_link"]

                imagenes_urls = [
                    row.get("imagen"), row.get("imagen2"), row.get("imagen3"),
                    row.get("imagen4"), row.get("imagen5"), row.get("imagen6")
                ]
                imagenes_urls = [u for u in imagenes_urls if u and u.strip()]

                slug_base = generar_slug(producto)
                slug = slug_base
                contador = 1
                while session.query(Publicacion).filter_by(titulo=slug).first():
                    contador += 1
                    slug = f"{slug_base}-{contador}"

                ambito_class = machear_ambito_s(session, ambito, idioma)
                categoria_id = machear_ambitoCategoria_s(session, categoria, idioma, ambito_class.id)
                registrar_relacion_categoria_ambito_s(session, categoria_id, ambito_class.id)

                usuario_id = machear_usuario_s(session, user_id)
                usuario = session.get(Usuario, usuario_id) if usuario_id else None
                if not usuario or not usuario.activo:
                    raise ValueError("Usuario no disponible.")
                ubicacion_id = machear_ubicacion_s(session, user_id, codigo_postal)

                precio_formateado, moneda = normalizar_precio(precio_venta_sugerido)
                texto = f"{moneda+' '+precio_formateado} DPI {motivo_tendencia} {producto}"

                publicacion = Publicacion(
                    user_id=usuario_id,
                    titulo=slug,
                    texto=texto,
                    ambito=ambito_class.valor,
                    correo_electronico=usuario.correo_electronico,
                    descripcion=motivo_tendencia,
                    color_texto="black",
                    color_titulo="black",
                    fecha_creacion=fecha,
                    estado=estado,
                    botonCompra=boton_compra,
                    imagen=imagenes_urls[0] if imagenes_urls else None,
                    idioma=idioma,
                    codigoPostal=codigo_postal,
                    afiliado_link=afiliado_link,
                    pagoOnline=pago_online,
                    categoria_id=categoria_id,
                    precio=float(precio_formateado),
                    moneda=moneda
                )
                session.add(publicacion)
                session.flush()  # genera ID

                publicaciones_completas.append(publicacion)

                publicacion_id = publicacion.id
                publicaciones_ids.append(publicacion_id)
                registrar_publicacion_ubicacion_s(session, publicacion_id, codigo_postal, user_id)
                registrar_categoria_publicacion_s(session, categoria_id, publicacion_id)
                codigo_postal_id = machear_codigo_postal_id_s(session, codigo_postal, ciudad, pais)
                registrar_ambito_usuario_s(session, user_id, ambito_class.id, publicacion.id)
                if codigo_postal_id:
                    registrar_codigo_postal_s(session, publicacion_id, codigo_postal_id)
                    machear_categoria_codigoPostal_s(session, categoria_id, codigo_postal_id)

                for index, url in enumerate(imagenes_urls):
                    filename = secure_filename(f"{slug}_{index}.jpg")
                    cargar_imagen_s(session, request, filename, url, publicacion_id,
                                    "black", producto, "image/jpeg", user_id, index)

            # commit lo hace el context manager
    except Exception as e:
        if solo_base_datos:
            raise
        # rollback lo hace el context manager; sólo logueamos
        print(f"❌ Error en completar_publicaciones: {e}")

    return publicaciones_ids if solo_base_datos else publicaciones_completas


def registrar_publicacion_ubicacion(publicacion_id, codigo_postal, user_id):
    try:
        if db.session.query(UsuarioPublicacionUbicacion).filter_by(id_publicacion=publicacion_id).first():
            return True

        region = db.session.query(UsuarioRegion).filter_by(user_id=user_id).first()
        ubicacion = db.session.query(UsuarioUbicacion).filter_by(user_id=user_id).first()

        new = UsuarioPublicacionUbicacion(
            user_id=user_id,
            id_region=region.id if region else None,
            id_publicacion=publicacion_id,
            id_ubicacion=ubicacion.id if ubicacion else 0,
            codigoPostal=codigo_postal
        )
        db.session.add(new)
        return True
    except Exception as e:
        print(f"❌ Error registrar_publicacion_ubicacion: {e}")
        return False
    
    
    
    
def registrar_categoria_publicacion(categoria_id, publicacion_id):
    try:
        new = CategoriaPublicacion(
            categoria_id=categoria_id,
            publicacion_id=publicacion_id,
            estado='activo'
        )
        db.session.add(new)
        return True
    except Exception as e:
        print(f"❌ Error registrar_categoria_publicacion: {e}")
        return False
def cargar_imagen(request, filename,url, id_publicacion, color_texto, titulo, mimetype, userid, index, size=0):
    try:
        existente = db.session.query(Image).filter_by(title=filename).first()
        if existente:
            registrar_media(publicacion_id=id_publicacion, imagen_id=existente.id, video_id=0, tipo='imagen', size=size)
            return filename

        nueva = Image(
            user_id=userid,
            title=filename,
            description=titulo,
            colorDescription=color_texto,
            filepath=url,
            randomNumber=random.randint(1, 1_000_000),
            size=float(size),
            mimetype=mimetype
        )
        db.session.add(nueva)
        db.session.flush()
        registrar_media(id_publicacion, nueva.id, 0, 'imagen', size)
        return filename

    except Exception as e:
        print(f"❌ Error en cargar_imagen: {e}")
        return None
def registrar_media(publicacion_id, imagen_id, video_id, tipo='imagen', size=0):
    try:
        media = Public_imagen_video(
            publicacion_id=publicacion_id,
            imagen_id=imagen_id,
            video_id=video_id,
            fecha_creacion=datetime.now(),
            media_type=tipo,
            size=float(size)
        )
        db.session.add(media)
    except Exception as e:
        print(f"❌ Error en registrar_media: {e}")
        
        
def machear_ambito_id(ambito_input, idioma='es'):
    if not ambito_input:
        return None

    try:
        ambito_id = int(ambito_input)  # Asegura que sea un entero
    except ValueError:
        print(f"❌ ID inválido para ámbito: '{ambito_input}'")
        return None

    ambito = (
        db.session.query(Ambitos)
        .filter(
            Ambitos.id == ambito_id,
            Ambitos.idioma == idioma
        )
        .first()
    )

    if ambito:
        return ambito
    else:
        print(f"⚠️ No se encontró ámbito con ID {ambito_id} e idioma '{idioma}'")
        return None

def machear_ambito(ambito_input, idioma='es'):
    if not ambito_input:
        return None

    ambito_normalizado = ambito_input.strip().lower()

    ambito = (
        db.session.query(Ambitos)
        .filter(
            func.lower(Ambitos.valor) == ambito_normalizado,
            Ambitos.idioma == idioma
        )
        .first()
    )

    if ambito:
        return ambito
    else:
        print(f"⚠️ No se encontró ámbito para la categoría: '{ambito_normalizado}'")
        return None 
    
    
def machear_ambitoCategoria(categoria, idioma='es', ambito_id=None):
    if not categoria:
        print("❌ Categoría vacía")
        return None

    categoria_normalizada = categoria.strip().lower()
    print(f"🔍 Buscando categoría: '{categoria_normalizada}'")

    try:
        with db.session.no_autoflush:
            ambito_categoria = db.session.query(AmbitoCategoria).filter_by(valor=categoria_normalizada,idioma=idioma).first()

        if ambito_categoria:
            categoria_id = ambito_categoria.id
            print(f"✅ Categoría encontrada: ID {ambito_categoria.id}")         
            # Crear categoría general y obtener ID
        categoria_general_id = get_or_create_categoria(categoria, idioma)

        # Crear color aleatorio
        COLORES_DISPONIBLES = ["red", "green", "blue", "orange", "purple", "yellow", "cyan", "teal", "brown"]
        color_aleatorio = random.choice(COLORES_DISPONIBLES)
        
        if not ambito_categoria:
            # Crear nueva categoría específica
            nueva_categoria = AmbitoCategoria(
                nombre=categoria.strip().capitalize(),
                descripcion=f"Categoría generada automáticamente para '{categoria}'",
                idioma=idioma,
                valor=categoria_normalizada,
                estado="ACTIVO",
                color=color_aleatorio,
                categoria_general_id=categoria_general_id
            )
            db.session.add(nueva_categoria)
            db.session.commit()
            categoria_id = nueva_categoria.id
    
        return categoria_id

    except SQLAlchemyError as e:
        print(f"❌ Error creando categoría '{categoria}': {e}")
        db.session.rollback()
        return None
    
    
    
 
def machear_ambitoCategoria_id(categoria, idioma='es'):
    if not categoria:
        print("❌ Categoría vacía")
        return None

    try:
        cat_id = int(categoria)
    except ValueError:
        print(f"❌ ID de categoría inválido: '{categoria}'")
        return None

    try:
        with db.session.no_autoflush:
            ambito_categoria = (
                db.session.query(AmbitoCategoria)
                .filter_by(id=cat_id, idioma=idioma)
                .first()
            )

        if ambito_categoria:
            print(f"✅ Categoría encontrada: ID {ambito_categoria.id}")
            return ambito_categoria.id

        print("⚠️ No se encontró la categoría")
        return None

    except SQLAlchemyError as e:
        print(f"❌ Error consultando categoría '{categoria}': {e}")
        return None
 
    

def machear_usuario(user_id):
    try:
        usuario = db.session.query(Usuario).filter(Usuario.id == int(user_id)).first()
        if usuario:
            return usuario.id
        else:
            print(f"⚠️ No se encontró usuario para el ID: '{user_id}'")
            return None
    except ValueError:
        print(f"❌ user_id inválido: '{user_id}'")
        return None
def machear_imagen(imagen):
    if not imagen:
        return None

    imagen_normalizada = imagen.strip().lower()

    imagen = db.session.query(Image).filter(
        (Image.url.ilike(f"%{imagen_normalizada}%")) |
        (Image.producto.ilike(f"%{imagen_normalizada}%"))
    ).first()

    if imagen:
        return imagen.id
    else:
        print(f"⚠️ No se encontró imagen para la URL: '{imagen}'")
        return None
def machear_video(video):
    if not video:
        return None

    video_normalizado = video.strip().lower()

    video = db.session.query(Video).filter(
        (Video.url.ilike(f"%{video_normalizado}%")) |
        (Video.producto.ilike(f"%{video_normalizado}%"))
    ).first()

    if video:
        return video.id
    else:
        print(f"⚠️ No se encontró video para la URL: '{video}'")
        return None
def machear_ubicacion(user_id, codigoPostal):    
    if not codigoPostal:
        return None

    try:
        ubicacion = db.session.query(UsuarioUbicacion).filter_by( user_id=int(user_id),  codigoPostal=codigoPostal ).first()
    except Exception as e:
        print(f"❌ Error al machear ubicación: {e}")
        return None

    if ubicacion:
        return ubicacion
    else:
        print(f"⚠️ No se encontró ubicación para el código postal: '{codigoPostal}'")
        return None
    
    
def machear_categoria_codigoPostal(categoria_id, codigo_postal_id):
    """
    Verifica si existe la relación categoria-codigo_postal.
    Si no existe, la crea. Devuelve True si todo va bien, False si hay error.
    """
    if not codigo_postal_id:
        return False

    try:
       

        # Verificar si ya existe la relación
        relacion = (
            db.session.query(CategoriaCodigoPostal)
            .filter_by(categoria_id=categoria_id, codigo_postal_id=int(codigo_postal_id))
            .first()
        )

        if not relacion:
            # Crear la relación
            relacion = CategoriaCodigoPostal(categoria_id=categoria_id, codigo_postal_id=int(codigo_postal_id))
            db.session.add(relacion)

        db.session.commit()
        return True

    except Exception as e:
        db.session.rollback()
        print(f"❌ Error en machear_categoria_codigoPostal: {e}")
        return False

    
def machear_publicacion(publicacion):
    if not publicacion:
        return None

    publicacion_normalizada = publicacion.strip().lower()

    publicacion = db.session.query(Publicacion).filter(
        (Publicacion.titulo.ilike(f"%{publicacion_normalizada}%")) |
        (Publicacion.descripcion.ilike(f"%{publicacion_normalizada}%"))
    ).first()

    if publicacion:
        return publicacion.id
    else:
        print(f"⚠️ No se encontró publicación para el título: '{publicacion}'")
        return None
def machear_estado_publicacion(estado):
    if not estado:
        return None

    estado_normalizado = estado.strip().lower()

    estado_publicacion = db.session.query(Estado_publi_usu).filter(
        (Estado_publi_usu.estado.ilike(f"%{estado_normalizado}%")) |
        (Estado_publi_usu.descripcion.ilike(f"%{estado_normalizado}%"))
    ).first()

    if estado_publicacion:
        return estado_publicacion.id
    else:
        print(f"⚠️ No se encontró estado de publicación para el estado: '{estado}'")
        return None
def machear_publicacion_ubicacion(publicacion_ubicacion):   
    if not publicacion_ubicacion:
        return None

    publicacion_ubicacion_normalizada = publicacion_ubicacion.strip().lower()

    publicacion_ubicacion = db.session.query(UsuarioPublicacionUbicacion).filter(
        (UsuarioPublicacionUbicacion.codigoPostal.ilike(f"%{publicacion_ubicacion_normalizada}%")) |
        (UsuarioPublicacionUbicacion.pais.ilike(f"%{publicacion_ubicacion_normalizada}%"))
    ).first()

    if publicacion_ubicacion:
        return publicacion_ubicacion.id
    else:
        print(f"⚠️ No se encontró publicación de ubicación para el código postal: '{publicacion_ubicacion}'")
        return None
    







def registrar_relacion_categoria_ambito(categoria_id, ambito_id):
    try:
        existe = db.session.query(AmbitoCategoriaRelation).filter_by(
            ambito_id=ambito_id,
            ambitoCategoria_id=categoria_id
        ).first()
        if not existe:
            relacion = AmbitoCategoriaRelation(
                ambito_id=ambito_id,
                ambitoCategoria_id=categoria_id,
                estado="ACTIVO"
            )
            db.session.add(relacion)
    except Exception as e:
        print(f"❌ Error al registrar relación categoría-ámbito: {e}")




def registrar_codigo_postal(publicacion_id, codigo_postal_id):
    try:
        existe = db.session.query(PublicacionCodigoPostal).filter_by(
            publicacion_id=publicacion_id,
            codigoPostal_id=codigo_postal_id
        ).first()
        if not existe:
            rel = PublicacionCodigoPostal(
                publicacion_id=publicacion_id,
                codigoPostal_id=codigo_postal_id,
                estado="ACTIVO"
            )
            db.session.add(rel)
    except Exception as e:
        print(f"❌ Error en registrar_codigo_postal: {e}")

    
    
    
    
def machear_codigo_postal_id(codigo_postal_texto,ciudad,pais, existe=False):
    try:
        
        codigo = db.session.query(CodigoPostal).filter_by(codigoPostal=codigo_postal_texto).first()
        if codigo:
            return codigo.id
        else:
           if not existe:
                rel = CodigoPostal(
                    codigoPostal=codigo_postal_texto,
                    ciudad=ciudad,
                    pais=pais
                   )
                db.session.add(rel)
                db.session.flush()
                return rel.id

    except Exception as e:
        print(f"❌ Error en machear_codigo_postal_id: {e}")
        return None


def registrar_ambito_usuario(user_id, ambito_id, publicacion_id):
    try:
        existe = db.session.query(Ambito_usuario).filter_by(
            user_id=user_id,
            ambito_id=ambito_id,
            publicacion_id=publicacion_id
        ).first()
        if not existe:
            rel = Ambito_usuario(
                user_id=user_id,
                ambito_id=ambito_id,
                publicacion_id=publicacion_id,
                estado="ACTIVO"
            )
            db.session.add(rel)
    except Exception as e:
        print(f"❌ Error en registrar_ambito_usuario: {e}")












        





def allowed_file(filename):
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4', 'avi', 'mov'}
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def es_formato_imagen(filepath):
    # Extensiones de archivo de imagen comunes
    extensiones_imagen = ['.jpg', '.jpeg', '.png', '.gif', '.bmp']

    # Verificar si la extensión del archivo está en la lista de extensiones de imagen
    return any(filepath.lower().endswith(ext) for ext in extensiones_imagen)



def cargar_id_publicacion_id_imagen_video(id_publicacion,nueva_imagen_id,nuevo_video_id,media_type,size=0):
    nuevo_ids= Public_imagen_video(
        publicacion_id=id_publicacion,
        imagen_id=nueva_imagen_id,
        video_id=nuevo_video_id,
        fecha_creacion=datetime.now(),
        media_type=media_type,
        size=float(size)
    )
    db.session.add(nuevo_ids)
    db.session.commit()
    db.session.close()
    return True



def generar_slug(texto):
    texto = texto.lower()
    texto = re.sub(r'[^\w\s-]', '', texto)  # quita símbolos raros
    texto = re.sub(r'[\s_]+', '-', texto)   # reemplaza espacios/guiones bajos por guiones
    return texto.strip('-')
















def get_or_create_categoria(valor_original, idioma):
    slug = normalizar_slug(valor_original)
    categoria = db.session.query(CategoriaGeneral).filter_by(slug=slug).first()
    if not categoria:
        categoria = CategoriaGeneral(slug=slug, descripcion=valor_original.strip())
        db.session.add(categoria)
        db.session.flush()

    traduccion = db.session.query(CategoriaTraduccion).filter_by(categoria_id=categoria.id, idioma=idioma).first()
    if not traduccion:
        nueva = CategoriaTraduccion(categoria_id=categoria.id, idioma=idioma, valor=valor_original.strip())
        db.session.add(nueva)
    db.session.commit()    
    return categoria.id






def normalizar_precio(precio):
    if not precio:
        return "0", None  # precio, moneda

    precio_str = str(precio).strip()

    # Eliminar caracteres invisibles (espacios raros, NO-BREAK SPACE, etc.)
    precio_str = re.sub(r"[\u202f\u00a0]", "", precio_str)

    # Mapas de símbolos a códigos de moneda
    monedas_detectadas = {
        "EUR": "EUR",
        "€": "EUR",
        "USD": "USD",
        "$": "USD",
        "ARS": "ARS",
        "GBP": "GBP",
        "£": "GBP",
        "AUD": "AUD",
        "CAD": "CAD",
        "BRL": "BRL",
        "MXN": "MXN",
        "COP": "COP",
    }

    moneda = "USD"  # por defecto
    for clave, codigo in monedas_detectadas.items():
        if clave in precio_str:
            moneda = codigo
            break

    # Extraer valor numérico
    match = re.search(r"[\d]+[.,]?\d*", precio_str)
    if match:
        try:
            valor_float = float(match.group(0).replace(",", "."))
            valor_formateado = (
                f"{int(valor_float)}" if valor_float.is_integer() else f"{valor_float:.2f}"
            )
            return valor_formateado, moneda
        except ValueError:
            pass

    return "0", None


























# --------- machear_* ----------
def machear_ambito_s(session, ambito_input, idioma='es'):
    if not ambito_input: return None
    ambito_normalizado = ambito_input.strip().lower()
    return (
        session.query(Ambitos)
        .filter(func.lower(Ambitos.valor)==ambito_normalizado, Ambitos.idioma==idioma)
        .first()
    )

def machear_ambitoCategoria_s(session, categoria, idioma='es', ambito_id=None):
    if not categoria: return None
    categoria_normalizada = categoria.strip().lower()
    print(f"🔍 Buscando categoría: '{categoria_normalizada}'")
    try:
        with session.no_autoflush:
            ambito_categoria = (
                session.query(AmbitoCategoria)
                .filter_by(valor=categoria_normalizada, idioma=idioma)
                .first()
            )
        if ambito_categoria:
            print(f"✅ Categoría encontrada: ID {ambito_categoria.id}")
            categoria_id = ambito_categoria.id
        else:
            categoria_general_id = get_or_create_categoria_s(session, categoria, idioma)
            color_aleatorio = random.choice(["red","green","blue","orange","purple","yellow","cyan","teal","brown"])
            nueva = AmbitoCategoria(
                nombre=categoria.strip().capitalize(),
                descripcion=f"Categoría generada automáticamente para '{categoria}'",
                idioma=idioma, valor=categoria_normalizada, estado="ACTIVO",
                color=color_aleatorio, categoria_general_id=categoria_general_id
            )
            session.add(nueva)
            session.flush()
            categoria_id = nueva.id
        return categoria_id
    except SQLAlchemyError as e:
        print(f"❌ Error creando categoría '{categoria}': {e}")
        return None

def machear_usuario_s(session, user_id):
    try:
        u = session.query(Usuario).filter(Usuario.id==int(user_id)).first()
        return u.id if u else None
    except ValueError:
        print(f"❌ user_id inválido: '{user_id}'"); return None

def machear_ubicacion_s(session, user_id, codigoPostal):
    if not codigoPostal: return None
    try:
        return session.query(UsuarioUbicacion).filter_by(user_id=int(user_id), codigoPostal=codigoPostal).first()
    except Exception as e:
        print(f"❌ Error al machear ubicación: {e}")
        return None

def machear_codigo_postal_id_s(session, codigo_postal_texto, ciudad, pais, existe=False):
    try:
        codigo = session.query(CodigoPostal).filter_by(codigoPostal=codigo_postal_texto).first()
        if codigo:
            return codigo.id
        if not existe:
            rel = CodigoPostal(codigoPostal=codigo_postal_texto, ciudad=ciudad, pais=pais)
            session.add(rel); session.flush()
            return rel.id
    except Exception as e:
        print(f"❌ Error en machear_codigo_postal_id: {e}")
        return None



# --------- registrar_* ----------
def registrar_publicacion_ubicacion_s(session, publicacion_id, codigo_postal, user_id):
    try:
        if session.query(UsuarioPublicacionUbicacion).filter_by(id_publicacion=publicacion_id).first():
            return True
        region = session.query(UsuarioRegion).filter_by(user_id=user_id).first()
        ubicacion = session.query(UsuarioUbicacion).filter_by(user_id=user_id).first()
        new = UsuarioPublicacionUbicacion(
            user_id=user_id,
            id_region=region.id if region else None,
            id_publicacion=publicacion_id,
            id_ubicacion=ubicacion.id if ubicacion else 0,
            codigoPostal=codigo_postal
        )
        session.add(new)
        return True
    except Exception as e:
        print(f"❌ Error registrar_publicacion_ubicacion: {e}")
        return False

def registrar_categoria_publicacion_s(session, categoria_id, publicacion_id):
    try:
        session.add(CategoriaPublicacion(categoria_id=categoria_id, publicacion_id=publicacion_id, estado='activo'))
        return True
    except Exception as e:
        print(f"❌ Error registrar_categoria_publicacion: {e}")
        return False

def registrar_media_s(session, publicacion_id, imagen_id, video_id, tipo='imagen', size=0):
    try:
        session.add(Public_imagen_video(
            publicacion_id=publicacion_id,
            imagen_id=imagen_id,
            video_id=video_id,
            fecha_creacion=datetime.now(),
            media_type=tipo,
            size=float(size)
        ))
    except Exception as e:
        print(f"❌ Error en registrar_media: {e}")

def registrar_relacion_categoria_ambito_s(session, categoria_id, ambito_id):
    try:
        existe = session.query(AmbitoCategoriaRelation).filter_by(
            ambito_id=ambito_id, ambitoCategoria_id=categoria_id
        ).first()
        if not existe:
            session.add(AmbitoCategoriaRelation(
                ambito_id=ambito_id, ambitoCategoria_id=categoria_id, estado="ACTIVO"
            ))
    except Exception as e:
        print(f"❌ Error al registrar relación categoría-ámbito: {e}")

def registrar_codigo_postal_s(session, publicacion_id, codigo_postal_id):
    try:
        existe = session.query(PublicacionCodigoPostal).filter_by(
            publicacion_id=publicacion_id, codigoPostal_id=codigo_postal_id
        ).first()
        if not existe:
            session.add(PublicacionCodigoPostal(
                publicacion_id=publicacion_id, codigoPostal_id=codigo_postal_id, estado="ACTIVO"
            ))
    except Exception as e:
        print(f"❌ Error en registrar_codigo_postal: {e}")

def registrar_ambito_usuario_s(session, user_id, ambito_id, publicacion_id):
    try:
        existe = session.query(Ambito_usuario).filter_by(
            user_id=user_id, ambito_id=ambito_id, publicacion_id=publicacion_id
        ).first()
        if not existe:
            session.add(Ambito_usuario(
                user_id=user_id, ambito_id=ambito_id, publicacion_id=publicacion_id, estado="ACTIVO"
            ))
    except Exception as e:
        print(f"❌ Error en registrar_ambito_usuario: {e}")



# --------- imágenes ----------
def cargar_imagen_s(session, request, filename, url, id_publicacion, color_texto, titulo, mimetype, userid, index, size=0):
    try:
        existente = session.query(Image).filter_by(title=filename).first()
        if existente:
            registrar_media_s(session, id_publicacion, existente.id, 0, 'imagen', size)
            return filename

        nueva = Image(
            user_id=userid, title=filename, description=titulo, colorDescription=color_texto,
            filepath=url, randomNumber=random.randint(1, 1_000_000), size=float(size), mimetype=mimetype
        )
        session.add(nueva)
        session.flush()
        registrar_media_s(session, id_publicacion, nueva.id, 0, 'imagen', size)
        return filename
    except Exception as e:
        print(f"❌ Error en cargar_imagen: {e}")
        return None


# --------- categorías generales / traducciones ----------
def get_or_create_categoria_s(session, valor_original, idioma):
    slug = normalizar_slug(valor_original)
    categoria = session.query(CategoriaGeneral).filter_by(slug=slug).first()
    if not categoria:
        categoria = CategoriaGeneral(slug=slug, descripcion=valor_original.strip())
        session.add(categoria)
        session.flush()

    traduccion = session.query(CategoriaTraduccion).filter_by(categoria_id=categoria.id, idioma=idioma).first()
    if not traduccion:
        session.add(CategoriaTraduccion(categoria_id=categoria.id, idioma=idioma, valor=valor_original.strip()))
    # commit NO acá; lo hace quien llamó
    return categoria.id


def machear_categoria_codigoPostal_s(session, categoria_id, codigo_postal_id):
    """
    Crea (si no existe) la relación categoría–código postal.
    No hace commit: lo maneja quien llama (get_db_session()).
    """
    if not categoria_id or not codigo_postal_id:
        return False
    try:
        cat_id = int(categoria_id)
        cp_id  = int(codigo_postal_id)
    except (TypeError, ValueError):
        print("❌ IDs inválidos en machear_categoria_codigoPostal_s")
        return False

    try:
        rel = (
            session.query(CategoriaCodigoPostal)
            .filter_by(categoria_id=cat_id, codigo_postal_id=cp_id)
            .first()
        )
        if not rel:
            session.add(CategoriaCodigoPostal(categoria_id=cat_id, codigo_postal_id=cp_id))
        return True
    except Exception as e:
        print(f"❌ Error en machear_categoria_codigoPostal_s: {e}")
        return False


# PWA endpoints. Legacy helpers above are retained, without Sheets dependencies.
from flask import session as flask_session
from werkzeug.exceptions import HTTPException
from services.publication_deletion import delete_owned_publication


@publicaciones.after_request
def private_publications(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


def authenticated_publication_user():
    user_id = flask_session.get('user_id')
    if type(user_id) is not int:
        return None
    user = db.session.get(Usuario, user_id)
    return user if user and user.activo else None


@publicaciones.get('/api/publicaciones/mias')
def my_publications():
    try:
        user = authenticated_publication_user()
        if user is None:
            return jsonify(success=False, error='Iniciá sesión.'), 401
        offset = request.args.get('offset', '0')
        if not offset.isdecimal() or len(offset) > 6:
            return jsonify(success=False, error='Página inválida.'), 400
        rows = Publicacion.query.filter_by(user_id=user.id).order_by(
            Publicacion.fecha_creacion.desc(), Publicacion.id.desc()).offset(int(offset)).limit(25).all()
        return jsonify(success=True, has_more=len(rows)>24, publicaciones=[{
            'id': row.id, 'titulo': row.titulo, 'descripcion': row.descripcion,
            'imagen': row.imagen, 'precio': row.precio, 'moneda': row.moneda,
            'estado': row.estado, 'can_delete': True,
        } for row in rows[:24]])
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.warning('Failed to load owned publications')
        return jsonify(success=False, error='No se pudieron consultar tus publicaciones.'), 503


@publicaciones.get('/api/publicaciones/<int:publication_id>')
def publication_detail(publication_id):
    try:
        row=db.session.get(Publicacion,publication_id)
        user=authenticated_publication_user()
        if not row or (str(row.estado).strip().lower()!='activo' and (not user or row.user_id!=user.id)):
            return jsonify(success=False,error='Publicación no encontrada.'),404
        photos=db.session.query(Image.filepath).join(Public_imagen_video,Public_imagen_video.imagen_id==Image.id).filter(
            Public_imagen_video.publicacion_id==row.id,Public_imagen_video.media_type=='imagen').order_by(Public_imagen_video.id).all()
        images=list(dict.fromkeys([url for url in [row.imagen,*[photo[0] for photo in photos]] if url]))
        postal=db.session.get(CodigoPostal,row.codigo_postal_id) if row.codigo_postal_id else None
        category=db.session.get(AmbitoCategoria,row.categoria_id) if row.categoria_id else None
        return jsonify(success=True,publicacion={'id':row.id,'titulo':row.titulo,'texto':row.texto,'descripcion':row.descripcion,
            'precio':row.precio,'moneda':row.moneda,'imagenes':images,'imagen':row.imagen,'ambito':row.ambito,
            'categoria':(category.valor or category.nombre) if category else None,
            'codigoPostal':postal.codigoPostal if postal else row.codigoPostal,'ciudad':postal.ciudad if postal else None,
            'pais':postal.pais if postal else None,'idioma':row.idioma,
            'fecha':row.fecha_creacion.isoformat() if row.fecha_creacion else None,'afiliado_link':row.afiliado_link})
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify(success=False,error='No se pudo consultar la publicación.'),503


@publicaciones.delete('/api/publicaciones/<int:publication_id>')
def delete_publication(publication_id):
    try:
        user = authenticated_publication_user()
        if user is None:
            return jsonify(success=False, error='Iniciá sesión.'), 401
        if request.headers.get('X-DPIA-Action') != 'delete-publication':
            return jsonify(success=False, error='Solicitud de eliminación inválida.'), 400
        if not 1 <= publication_id <= 2147483647:
            return jsonify(success=False, error='Publicación no encontrada.'), 404
        return jsonify(delete_owned_publication(publication_id, user.id))
    except HTTPException as exc:
        return jsonify(success=False, error=exc.description), exc.code
    except SQLAlchemyError:
        db.session.rollback()
        current_app.logger.warning('Publication deletion rolled back')
        return jsonify(success=False, error='No se pudo eliminar la publicación. No se confirmaron cambios.'), 503


@publicaciones.get('/api/publicaciones/promociones')
def promotion_balance():
    try:
        user = authenticated_publication_user()
        if user is None:
            return jsonify(success=False, error='Iniciá sesión.'), 401
        from services.publication_promotions import summary
        return jsonify(success=True, **summary(user.id))
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify(success=False, error='No se pudieron consultar los puntos de promoción.'), 503


@publicaciones.post('/api/publicaciones/<int:publication_id>/destacar')
def promote_publication(publication_id):
    try:
        user = authenticated_publication_user()
        if user is None:
            return jsonify(success=False, error='Iniciá sesión.'), 401
        if request.headers.get('X-DPIA-Action')!='promote-publication':
            return jsonify(success=False, error='Solicitud inválida.'), 400
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or set(body)!={'operacion_id'}:
            return jsonify(success=False, error='Solicitud inválida.'), 400
        from services.publication_promotions import activate
        return jsonify(activate(publication_id, user.id, body['operacion_id']))
    except HTTPException as exc:
        return jsonify(success=False, error=exc.description), exc.code
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify(success=False, error='No se confirmó la promoción. Actualizá tu perfil antes de reintentar.'), 503
