"""Immutable generation-verified GCS REST uploads; credentials never serialized."""
import hashlib
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

TRANSIENT = {429,500,502,503,504}

def safe_path(value):
    return bool(value and all(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', p) and p not in ('.','..') for p in value.split('/')))

def is_timeout(exc):
    return isinstance(exc, TimeoutError) or any(c.__name__ in ('Timeout','ReadTimeout','ConnectTimeout') for c in type(exc).__mro__)

class GCSStore:
    def __init__(self, bucket, prefix, session=None):
        prefix = prefix.rstrip('/')
        if not safe_path(prefix) or not re.fullmatch(r'[a-z0-9][a-z0-9._-]{1,220}[a-z0-9]',bucket):
            raise ValueError('Supply a bucket name and safe nonempty relative prefix')
        self.bucket, self.prefix = bucket, prefix
        if session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            credentials, _ = google.auth.default(scopes=['https://www.googleapis.com/auth/cloud-platform'])
            session = AuthorizedSession(credentials)
        self.session = session

    def _get(self, url, params):
        for attempt in range(3):
            try:
                r = self.session.get(url, params=params, timeout=60)
                if r.status_code not in TRANSIENT: return r
            except Exception as e:
                if not is_timeout(e): raise
                if attempt == 2: raise
            if attempt < 2: time.sleep(0.25*2**attempt)
        raise RuntimeError('GET transient retry budget exhausted')

    def put_verified(self, name, data, content_type='application/octet-stream'):
        if not safe_path(name): raise ValueError('Unsafe object name')
        obj = self.prefix+'/'+name
        base = 'https://storage.googleapis.com'
        url = base+'/storage/v1/b/'+quote(self.bucket,safe='')+'/o/'+quote(obj,safe='')
        generation = None
        for attempt in range(3):
            try:
                r = self.session.post(base+'/upload/storage/v1/b/'+quote(self.bucket,safe='')+'/o',
                    params={'uploadType':'media','name':obj,'ifGenerationMatch':'0'}, data=data,
                    headers={'Content-Type':content_type}, timeout=60)
            except Exception as e:
                if not is_timeout(e): raise
                r = None
            if r is not None and r.status_code in (200,201):
                generation = str(r.json()['generation'])
                break
            if r is not None and r.status_code not in TRANSIENT:
                raise RuntimeError('Immutable upload rejected HTTP '+str(r.status_code))
            # Ambiguous commit: inspect existing generation before retrying create-only.
            metadata = self._get(url,{})
            if metadata.status_code == 200:
                generation = str(metadata.json()['generation'])
                break
            if metadata.status_code != 404: raise RuntimeError('Recovery metadata HTTP '+str(metadata.status_code))
            if attempt < 2: time.sleep(0.25*2**attempt)
        if generation is None: raise RuntimeError('Upload transient retry budget exhausted')
        read = self._get(url,{'alt':'media','generation':generation})
        sha = hashlib.sha256(data).hexdigest()
        if read.status_code != 200 or hashlib.sha256(read.content).hexdigest() != sha:
            raise RuntimeError('Generation readback checksum mismatch')
        return dict(object=obj,generation=generation,sha256=sha,bytes=len(data))

    def publish(self, directory):
        directory = Path(directory)
        manifest = json.loads((directory/'manifest.json').read_text())
        metrics = json.loads((directory/'metrics.json').read_text())
        if manifest.get('status') != 'success' or metrics.get('status') != 'success':
            raise ValueError('Cannot publish SUCCESS for a failed generation')
        required = ['image.png','parameters.json','metrics.json']
        payloads = {n:(directory/n).read_bytes() for n in required}
        for name,data in payloads.items():
            entry = manifest.get('files',{}).get(name,{})
            if entry.get('sha256') != hashlib.sha256(data).hexdigest() or entry.get('bytes') != len(data):
                raise ValueError('Local manifest mismatch: '+name)
        if (directory/'result.zip').exists(): payloads['result.zip'] = (directory/'result.zip').read_bytes()
        payloads['manifest.json'] = (directory/'manifest.json').read_bytes()
        objects = {n:self.put_verified(n,data,'application/json' if n.endswith('.json') else 'application/octet-stream') for n,data in payloads.items()}
        success = json.dumps({'status':'success','objects':objects},sort_keys=True).encode()
        objects['SUCCESS.json'] = self.put_verified('SUCCESS.json',success,'application/json')
        return dict(bucket=self.bucket,prefix=self.prefix,objects=objects)
