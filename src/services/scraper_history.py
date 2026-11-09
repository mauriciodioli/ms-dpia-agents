"""Existing shared Scrapeador history, accessible only to the service-token owner.

The upstream API additionally enforces its administrator/shared-resource policy.
No credential, arbitrary URL or client-supplied product row is forwarded.
"""
import re
from urllib.parse import quote, urlsplit
import requests
from model.usuario import Usuario
from utils.db import db
from services.dpia_client import DPIAClient
from services.query_execution import COUNTRY_KEYS, normalize_products, safe_product_url
from services.query_images import validate_filters
from services.query_preparation import PreparationError


class ScraperHistory:
    def __init__(self, user_id, config):
        self.user_id=user_id;self.config=config
        key=config.get('SCRAPEADOR_SERVICE_KEY','')
        if not key:raise PreparationError('Falta la credencial de la API DPIA.',503)
        self.headers={'Authorization':'Bearer '+key}
        user=db.session.get(Usuario,user_id)
        if not user or not user.activo:raise PreparationError('Iniciá sesión.',401)
        auth=self.call('GET','/auth/check',params={'permiso':'scraper:read'})
        token=auth.get('token') or {}
        if not isinstance(token,dict):raise PreparationError('No se pudo verificar al titular de la conexión.',403)
        if (str(token.get('usuario_id'))!=str(user_id) or
            not isinstance(token.get('usuario'),str) or token['usuario'].casefold()!=user.correo_electronico.casefold()):
            raise PreparationError('Este historial compartido solo está disponible para el titular autorizado de la conexión DPIA.',403)

    def call(self,method,path,**kwargs):
        try:
            with requests.request(method,DPIAClient.BASE_URL+path,headers=self.headers,
                timeout=(3.05,180 if method=='POST' else 15),allow_redirects=False,**kwargs) as response:
                if response.status_code!=200:
                    status=response.status_code if response.status_code in (400,401,403,404,409) else 502
                    raise PreparationError('La API DPIA no confirmó la operación del historial. No se reintentará automáticamente.',status)
                data=response.json()
            if not isinstance(data,dict) or data.get('success') is not True:
                raise PreparationError('La API DPIA no confirmó el resultado del historial.',502)
            return data
        except (requests.RequestException,ValueError):
            raise PreparationError('No se pudo confirmar la respuesta de DPIA. Consultá el trabajo antes de reintentar.',502) from None

    def listing(self,country):
        if not isinstance(country,str) or country not in COUNTRY_KEYS:raise PreparationError('Elegí un país para consultar los trabajos de la API.')
        data=self.call('GET','/trabajos',params={'lugar':country})
        files=data.get('archivos')
        if not isinstance(files,list):raise PreparationError('La API no devolvió un listado de archivos compatible.',502)
        return [{'archivo':name,'nombre':name[:-5]} for name in files if isinstance(name,str) and
                len(name)<=200 and re.fullmatch(r'[\w .-]+\.json',name) and '..' not in name]

    def load(self,country,filename):
        if not any(row['archivo']==filename for row in self.listing(country)):
            raise PreparationError('Trabajo no encontrado en el historial autorizado.',404)
        data=self.call('GET','/archivos/'+quote(filename,safe=''))
        groups=data.get('datos')
        if not isinstance(groups,list) or any(not isinstance(g,dict) for g in groups):
            raise PreparationError('El archivo no contiene resultados directos compatibles.',409)
        return groups

    def images(self,country,filename,filters):
        if not self.config.get('LIVE_PROVIDER_CALLS_ENABLED',False):
            raise PreparationError('Las llamadas reales están deshabilitadas.',503)
        groups=self.load(country,filename)
        filters=validate_filters(filters)
        names=[g.get('producto') or g.get('Producto') for g in groups]
        if any(not isinstance(name,str) or not name for name in names):
            raise PreparationError('El trabajo no contiene nombres de búsqueda válidos.',409)
        # Same explicit image preparation endpoint used by the existing Scrapeador.
        data=self.call('POST','/scraping/imagenes',json={'sheet_name':COUNTRY_KEYS[country],
            'nombre_archivo':filename,'archivo_base':filename,
            'filtros_por_producto':{name:filters for name in names}})
        rows=data.get('tablaB')
        if not isinstance(rows,list):raise PreparationError('La API no devolvió una selección final compatible.',502)
        selected=[]
        for row in rows:
            if not isinstance(row,dict):continue
            photos=[]
            for key in ('imagen','imagen2','imagen3','imagen4','imagen5','imagen6'):
                url=safe_product_url(row.get(key))
                if url and not urlsplit(url).password and url not in photos:photos.append(url)
            selected.append({'title':row.get('Producto') or '', 'images':photos})
        return {'success':True,'selected':selected,'archivo_relacionado':data.get('archivo_relacionado')}
