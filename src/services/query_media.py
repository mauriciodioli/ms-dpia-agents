"""Validate bounded image inputs and video keyframes; never fetch client URLs."""
import base64
import binascii
import io
from PIL import Image, ImageOps, UnidentifiedImageError
from services.query_preparation import PreparationError


def validate_attachments(value):
    if value is None:return []
    if not isinstance(value,list) or len(value)>4:
        raise PreparationError('Adjuntá hasta 4 imágenes o videos.')
    result=[];frame_count=0;total=0
    for item in value:
        if (not isinstance(item,dict) or set(item)-{'type','name','frames'}
            or item.get('type') not in ('image','video') or not isinstance(item.get('name'),str)
            or len(item['name'])>180 or not isinstance(item.get('frames'),list)
            or not 1<=len(item['frames'])<=(1 if item['type']=='image' else 4)):
            raise PreparationError('Adjunto inválido.')
        frames=[]
        for frame in item['frames']:
            frame_count+=1
            if frame_count>8 or not isinstance(frame,str) or len(frame)>1500000:
                raise PreparationError('Los adjuntos superan el tamaño permitido.')
            if not frame.startswith(('data:image/jpeg;base64,','data:image/png;base64,','data:image/webp;base64,')):
                raise PreparationError('Formato de imagen no permitido.')
            try:
                data=base64.b64decode(frame.split(',',1)[1],validate=True);total+=len(data)
                if total>5000000:raise ValueError()
                with Image.open(io.BytesIO(data)) as image:
                    if image.width*image.height>16000000:raise ValueError()
                    image=ImageOps.exif_transpose(image).convert('RGB');image.thumbnail((1024,1024))
                    output=io.BytesIO();image.save(output,'JPEG',quality=82)
                frames.append('data:image/jpeg;base64,'+base64.b64encode(output.getvalue()).decode())
            except (ValueError,binascii.Error,OSError,UnidentifiedImageError,Image.DecompressionBombError):
                raise PreparationError('No se pudo leer una imagen adjunta.') from None
        result.append({'type':item['type'],'name':item['name'],'frames':frames})
    return result


def model_input(prepared):
    if not prepared.get('attachments'):return prepared['user_message']
    content=[{'type':'input_text','text':prepared['user_message'] or 'Identificá el producto de los adjuntos usando el contexto seleccionado.'}]
    for item in prepared['attachments']:
        content.append({'type':'input_text','text':f"Adjunto {item['type']}: {item['name']}. Los videos se representan mediante fotogramas, sin audio."})
        content.extend({'type':'input_image','image_url':frame} for frame in item['frames'])
    return [{'role':'user','content':content}]
