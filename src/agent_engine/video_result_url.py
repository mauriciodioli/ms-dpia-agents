"""Refresh a completed video's temporary provider URL without creating a video."""
import json
import re
from urllib.parse import urlsplit
from flask import current_app
from .rest_providers.service import Service


def refresh(conn, job, projection):
    payload=projection.get('result')
    video=payload.get('video') if isinstance(payload,dict) else None
    if not isinstance(video,dict) or video.get('provider')!='heygen' or video.get('state')!='COMPLETED':return projection
    remote=video.get('remote_id')
    if not isinstance(remote,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',remote):return projection
    from .shared_video_provider import resolve
    try:row=resolve(conn,job['owner_id'])
    except Exception:return projection
    if not row['credential_ciphertext'] or row['credential_origin']!=row['base_url']:return projection
    try:
        service=Service(conn.engine,current_app.config);secret=json.loads(service.secrets.decrypt(row))
        if not isinstance(secret,str) or not secret:return projection
        status,data=service.http.get(row['base_url'],'/v3/videos/'+remote,secret,'X-Api-Key',row['timeout_seconds'])
        result=data.get('data') or {};url=result.get('video_url');parsed=urlsplit(url) if isinstance(url,str) else None
        if status!=200 or result.get('id')!=remote or result.get('status')!='completed' or not parsed or parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or secret in url:return projection
    except Exception:
        return projection
    old=video.get('url');new_payload={**payload,'video':{**video,'url':url}}
    if isinstance(payload.get('items'),list):new_payload['items']=[{**item,'url':url} if isinstance(item,dict) and item.get('url')==old else item for item in payload['items']]
    return {**projection,'result':new_payload}
