"""Publish one owned, image-prepared result without Sheets or another scrape."""
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from sqlalchemy import select, update
from services.scraping_quota import operaciones, decode
from services.query_images import raw_product
from services.query_preparation import PreparationError
from model.usuario import Usuario
from model.publicaciones.publicaciones import Publicacion
from model.publicaciones.ambitos import Ambitos
from model.publicaciones.ambitoCategoria import AmbitoCategoria
from model.publicaciones.ambitoCategoriaRelation import AmbitoCategoriaRelation
from model.publicaciones.categoriaPublicacion import CategoriaPublicacion
from model.publicaciones.publicacionCodigoPostal import PublicacionCodigoPostal
from model.publicaciones.ambito_usuario import Ambito_usuario
from model.publicaciones.publicacion_imagen_video import Public_imagen_video
from model.image import Image

CURRENCIES={'EUR','USD','ARS','GBP','AUD','CAD','BRL','MXN','COP'}


def publish_product(quota, operation_id, user_id, body):
    allowed={'product_index','titulo','descripcion','moneda','imagenes'}
    if not isinstance(body,dict) or set(body)-allowed or type(body.get('product_index')) is not int:
        raise PreparationError('Seleccioná un producto preparado.')
    for field,limit in (('titulo',120),('descripcion',1000)):
        if not isinstance(body.get(field),str) or not body[field].strip() or len(body[field])>limit:
            raise PreparationError('Revisá el título y la descripción de la publicación.')
    if body.get('moneda') not in CURRENCIES:
        raise PreparationError('Confirmá la moneda real del precio del producto.')
    index=body['product_index']
    # Same transaction commits publication, images, junctions and its replay marker.
    with quota._engine().begin() as conn:
        quota._lock(conn,user_id)
        row=conn.execute(select(operaciones).where(operaciones.c.operacion_id==operation_id,
            operaciones.c.usuario_id==user_id).with_for_update()).mappings().first()
        if not row:raise PreparationError('Operación no encontrada.',404)
        if row['estado']!='consumed':raise PreparationError('El scraping no está confirmado.',409)
        outcome=decode(row['resultado_json']) or {};prepared=decode(row['contexto_json'])
        item=raw_product({'outcome':json.dumps(outcome),'source':row['origen']},index)
        stage=outcome.get('image_stages',{}).get(str(index),{})
        if stage.get('status')!='complete':raise PreparationError('Prepará primero las imágenes del producto.',409)
        photos=body.get('imagenes')
        if (not isinstance(photos,list) or not 1<=len(photos)<=6 or any(not isinstance(p,str) or p not in stage.get('images',[]) for p in photos)
            or len(set(photos))!=len(photos) or any(len(p)>500 for p in photos) or len(photos[0])>255):
            raise PreparationError('Elegí entre una y seis imágenes preparadas; la principal admite hasta 255 caracteres.')
        price=item.get('precio')
        if isinstance(price,str) and re.fullmatch(r'\d+(?:[.,]\d{1,2})?',price.strip()):price=float(price.replace(',','.'))
        if type(price) not in (int,float) or not math.isfinite(price) or price<=0:
            raise PreparationError('El precio original no es un número válido; no se inventará un precio.')
        payload={**body,'titulo':body['titulo'].strip(),'descripcion':body['descripcion'].strip()}
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        previous=stage.get('publication')
        if previous:
            if previous['fingerprint']!=digest:raise PreparationError('El producto ya tiene una publicación con otro contenido.',409)
            exists=conn.execute(select(Publicacion.id).where(Publicacion.id==previous['id'],Publicacion.user_id==user_id)).first()
            if not exists:raise PreparationError('La publicación fue eliminada y no se volverá a crear con este pedido.',409)
            return {'success':True,'guardado':True,'publicacion_id':previous['id']}
        user=conn.execute(select(Usuario.__table__).where(Usuario.id==user_id,Usuario.activo.is_(True))).mappings().first()
        if not user:raise PreparationError('Iniciá sesión con un usuario activo.',401)
        ids=prepared['ids'];context=prepared['context']
        scope=conn.execute(select(Ambitos.__table__).where(Ambitos.id==ids['ambito_id'])).mappings().first()
        category=conn.execute(select(AmbitoCategoria.id).where(AmbitoCategoria.id==ids['categoria_id'])).first()
        relation=conn.execute(select(AmbitoCategoriaRelation.id).where(
            AmbitoCategoriaRelation.ambito_id==ids['ambito_id'],AmbitoCategoriaRelation.ambitoCategoria_id==ids['categoria_id'])).first()
        if not scope or not category or not relation:raise PreparationError('La categoría ya no corresponde al ámbito seleccionado.',409)
        slug='pwa-'+hashlib.sha256(f'{user_id}:{operation_id}:{index}'.encode()).hexdigest()
        if conn.execute(select(Publicacion.id).where(Publicacion.titulo==payload['titulo'])).first():
            raise PreparationError('Ya existe una publicación con ese título. Elegí un título diferente.',409)
        result=conn.execute(Publicacion.__table__.insert().values(user_id=user_id,titulo=payload['titulo'],texto=slug,
            ambito=scope['valor'] or context['ambito'],categoria_id=ids['categoria_id'],correo_electronico=user['correo_electronico'],
            descripcion=payload['descripcion'],color_texto='black',color_titulo='black',
            fecha_creacion=datetime.now(timezone.utc).replace(tzinfo=None),estado='ACTIVO',
            codigo_postal_id=ids['codigo_postal_id'],codigoPostal=context['codigoPostal'],idioma=context['idioma'],
            botonCompra=True,pagoOnline=False,imagen=photos[0],precio=price,moneda=body['moneda'],afiliado_link=''))
        publication_id=result.inserted_primary_key[0]
        conn.execute(CategoriaPublicacion.__table__.insert().values(categoria_id=ids['categoria_id'],publicacion_id=publication_id,estado='activo'))
        conn.execute(PublicacionCodigoPostal.__table__.insert().values(codigoPostal_id=ids['codigo_postal_id'],publicacion_id=publication_id,estado='ACTIVO'))
        conn.execute(Ambito_usuario.__table__.insert().values(user_id=user_id,ambito_id=ids['ambito_id'],publicacion_id=publication_id,estado='ACTIVO'))
        for i,photo in enumerate(photos):
            image=conn.execute(Image.__table__.insert().values(user_id=user_id,title=f'{slug}-{i}.jpg',description=payload['titulo'],
                colorDescription='black',filepath=photo,randomNumber=0,size=0,mimetype=None))
            conn.execute(Public_imagen_video.__table__.insert().values(publicacion_id=publication_id,
                imagen_id=image.inserted_primary_key[0],video_id=0,media_type='imagen',size=0))
        stage['publication']={'id':publication_id,'fingerprint':digest}
        conn.execute(update(operaciones).where(operaciones.c.operacion_id==operation_id,
            operaciones.c.usuario_id==user_id).values(resultado_json=json.dumps(outcome,ensure_ascii=False)))
        return {'success':True,'guardado':True,'publicacion_id':publication_id}
