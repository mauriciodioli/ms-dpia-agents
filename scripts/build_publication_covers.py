"""Manually build static covers using SELECT and bucket GET only.
Run from repository root: python scripts/build_publication_covers.py
Requires development dependencies and the application's existing database config.
"""
import hashlib
import io
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
import requests
from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from services.publication_covers import (bucket_url, read_snapshot, resolve_snapshot,
                                         build_manifest, coverage_report, coverage_markdown, language_code)


class BucketImages:
    def __init__(self, directory):
        self.directory = directory
        self.directory.mkdir(parents=True,exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=6)
        self.futures = {}
        self.lock = Lock()
        self.failures = []

    def schedule(self, url):
        with self.lock:
            if url not in self.futures:
                self.futures[url] = self.pool.submit(self.fetch,url)
            return self.futures[url]

    def __call__(self,url):
        return self.schedule(url).result()

    def fetch(self,url):
        try:
            if not bucket_url(url): raise ValueError('unsupported_bucket_url')
            with requests.get(url,timeout=(4,12),stream=True,allow_redirects=False) as response:
                if response.status_code != 200: raise ValueError('http_'+str(response.status_code))
                if response.headers.get('Content-Type','').split(';')[0] not in ('image/jpeg','image/png','image/webp'):
                    raise ValueError('unsupported_content_type')
                content = bytearray()
                for chunk in response.iter_content(65536):
                    content.extend(chunk)
                    if len(content) > 12*1024*1024: raise ValueError('image_too_large')
            with Image.open(io.BytesIO(content)) as source:
                if source.width < 160 or source.height < 120: raise ValueError('image_too_small')
                if source.width * source.height > 40000000: raise ValueError('image_too_large')
                picture = ImageOps.exif_transpose(source).convert('RGBA')
                background = Image.new('RGBA',picture.size,'#f3eff7')
                background.alpha_composite(picture)
                picture = ImageOps.fit(background.convert('RGB'),(480,360),Image.Resampling.LANCZOS)
                output = io.BytesIO(); picture.save(output,'WEBP',quality=82,method=6)
            data = output.getvalue()
            digest = hashlib.sha256(data).hexdigest()
            filename = digest[:24]+'.webp'
            path = self.directory/filename
            if not path.exists() or path.read_bytes() != data:
                temporary = path.with_suffix('.tmp')
                # The same content may originate from different bucket URLs.
                with self.lock:
                    temporary.write_bytes(data); temporary.replace(path)
            return {'image':filename,'sha256':digest,'width':480,'height':360,'bytes':len(data)}
        except (requests.RequestException,ValueError,OSError,UnidentifiedImageError,Image.DecompressionBombError) as exc:
            reason = str(exc) if isinstance(exc,ValueError) else type(exc).__name__
            with self.lock:self.failures.append({'source_url':url,'reason':reason})
            return None

    def close(self):
        self.pool.shutdown(wait=True)


def atomic_text(path,content):
    temp=path.with_suffix(path.suffix+'.tmp');temp.write_text(content,encoding='utf-8');temp.replace(path)


def main():
    # Import config only during an explicit manual invocation, never during tests.
    from app import app
    from utils.db import db
    target=ROOT/'src/static/images/publication-covers'
    manifest_path=target/'manifest.json'
    previous=json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    with app.app_context(), db.engine.connect() as connection:
        connection.exec_driver_sql('START TRANSACTION READ ONLY')
        try:snapshot=read_snapshot(connection)
        finally:connection.rollback()
    resolved=resolve_snapshot(snapshot)
    loader=BucketImages(target)
    try:
        # Warm a bounded number of candidates concurrently, not the whole bucket.
        warm=set()
        for candidates in resolved['candidates'].values():
            if candidates:warm.add(candidates[0]['source_url'])
            places={place for row in candidates for place in row['locations']}
            for place in places:
                warm.add(next(row['source_url'] for row in candidates if place in row['locations']))
        for url in sorted(warm):loader.schedule(url)
        manifest=build_manifest(resolved,previous,loader,datetime.now(timezone.utc).isoformat())
    finally:loader.close()
    report=coverage_report(manifest,resolved,sorted(loader.failures,key=lambda row:row['source_url']))
    report['unsupported_catalog_records'] = {kind:[{'id':row['id'],'nombre':row['nombre'],'idioma':row['idioma']} for row in snapshot[kind] if not language_code(row['idioma'])] for kind in ('categories','scopes')}
    atomic_text(target/'catalog-reference.json',json.dumps({key:snapshot[key] for key in ('categories','scopes','scope_links')},ensure_ascii=False,indent=2)+'\n')
    atomic_text(manifest_path,json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    atomic_text(target/'coverage.json',json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    atomic_text(target/'coverage.md',coverage_markdown(report))
    # JSON is the source of truth; JS avoids runtime fetches or async render races.
    atomic_text(ROOT/'src/static/publication-covers-map.js',
                'window.DPIAPublicationCovers = '+json.dumps(manifest,ensure_ascii=False,separators=(',',':'))+';\n')
    for lang,row in report['global'].items():
        print(lang, {k:v for k,v in row.items() if not isinstance(v,list)})
    print('Excluded publications:',len(resolved['excluded']),'Failed image URLs:',len(loader.failures))
    print('Full report: src/static/images/publication-covers/coverage.json')


if __name__=='__main__':
    main()
