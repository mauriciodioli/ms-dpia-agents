"""One-time email login. Redis stores only keyed code digests, never codes."""
import hashlib
import hmac
import os
import re
import secrets
import smtplib
from email.message import EmailMessage
from flask import current_app, jsonify, request, session
from model.usuario import Usuario

EMAIL = re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')
VERIFY = """
local value=redis.call('HGET',KEYS[1],'digest')
if not value then return 0 end
local attempts=redis.call('HINCRBY',KEYS[1],'attempts',1)
if attempts > 5 then redis.call('DEL',KEYS[1]); return 0 end
if value ~= ARGV[1] then return 0 end
redis.call('DEL',KEYS[1]); return 1
"""


def setup():
    import redis
    url=os.getenv('DPIA_LOGIN_REDIS_URL','').strip()
    secret=os.getenv('DPIA_LOGIN_CODE_SECRET','').strip()
    host=os.getenv('DPIA_LOGIN_SMTP_HOST','').strip()
    sender=os.getenv('DPIA_LOGIN_SMTP_FROM','').strip()
    if not url or len(secret)<32 or not host or not sender:
        raise RuntimeError('email_login_not_configured')
    return redis.Redis.from_url(url, socket_connect_timeout=3, socket_timeout=3),secret.encode(),host,sender


def digest(secret, *parts):
    return hmac.new(secret, '\0'.join(parts).encode(), hashlib.sha256).hexdigest()


def same_origin():
    from urllib.parse import urlsplit
    origin=request.headers.get('Origin')
    return (request.headers.get('X-DPIA-Action')=='email-login' and
            request.headers.get('Sec-Fetch-Site')!='cross-site' and
            (not origin or urlsplit(origin).netloc==request.host))


def send_mail(host,sender,email,code):
    msg=EmailMessage();msg['Subject']='Tu código de acceso a DPIA';msg['From']=sender;msg['To']=email
    msg.set_content('Tu código de acceso es: '+code+'\n\nVence en 10 minutos y se puede usar una sola vez.')
    port=int(os.getenv('DPIA_LOGIN_SMTP_PORT','587'))
    with smtplib.SMTP(host,port,timeout=10) as smtp:
        smtp.ehlo();smtp.starttls();smtp.ehlo()
        username=os.getenv('DPIA_LOGIN_SMTP_USER','');password=os.getenv('DPIA_LOGIN_SMTP_PASSWORD','')
        if username:smtp.login(username,password)
        smtp.send_message(msg)


def start():
    if not same_origin():return jsonify(error='Solicitud no autorizada.'),403
    body=request.get_json(silent=True)
    email=body.get('email','').strip().lower() if isinstance(body,dict) and isinstance(body.get('email'),str) else ''
    if len(email)>120 or not EMAIL.fullmatch(email):return jsonify(error='Ingresá un correo válido.'),400
    try:
        redis,secret,host,sender=setup()
        ip=request.remote_addr or 'unknown'
        for name,limit in [('email:'+email,4),('ip:'+ip,20)]:
            key='dpia:email-login:limit:'+digest(secret,name)
            count=redis.incr(key)
            if count==1:redis.expire(key,600)
            if count>limit:return jsonify(error='Demasiados intentos. Probá más tarde.'),429
        challenge=secrets.token_urlsafe(32);code=str(secrets.randbelow(100000000)).zfill(8)
        user=Usuario.query.filter_by(correo_electronico=email,activo=True).one_or_none()
        session.pop('email_login_challenge',None)
        if user:
            key='dpia:email-login:code:'+digest(secret,challenge)
            redis.hset(key,mapping={'digest':digest(secret,challenge,code),'user_id':str(user.id),'attempts':'0'})
            redis.expire(key,600)
            try:send_mail(host,sender,email,code)
            except Exception:
                redis.delete(key);raise
            session['email_login_challenge']=challenge
        return jsonify(message='Si la cuenta está activa, recibirás un código por correo.')
    except Exception:
        current_app.logger.warning('Email login unavailable')
        return jsonify(error='El acceso por correo no está disponible. Intentá más tarde.'),503


def verify():
    if not same_origin():return jsonify(error='Solicitud no autorizada.'),403
    body=request.get_json(silent=True)
    code=body.get('code') if isinstance(body,dict) else None
    challenge=session.get('email_login_challenge')
    if not isinstance(code,str) or not re.fullmatch(r'[0-9]{8}',code) or not isinstance(challenge,str):
        return jsonify(error='Código inválido o vencido.'),401
    try:
        redis,secret,_,_=setup();key='dpia:email-login:code:'+digest(secret,challenge)
        user_id=redis.hget(key,'user_id')
        if not user_id or redis.eval(VERIFY,1,key,digest(secret,challenge,code))!=1:
            return jsonify(error='Código inválido o vencido.'),401
        user=Usuario.query.filter_by(id=int(user_id),activo=True).one_or_none()
        if not user:return jsonify(error='Código inválido o vencido.'),401
        session.clear();session['user_id']=user.id;session['email']=user.correo_electronico
        return jsonify(email=user.correo_electronico,authenticated=True)
    except Exception:
        current_app.logger.warning('Email login verification unavailable')
        return jsonify(error='El acceso por correo no está disponible. Intentá más tarde.'),503
