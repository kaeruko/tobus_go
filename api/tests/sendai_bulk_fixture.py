"""Explicit compressed original-row fixture for bulk tests only, never runtime."""
import base64
import hashlib
import json
from pathlib import Path
import zlib

F=Path(__file__).parent/'fixtures/sendai_subway'


def read(name):
    return json.loads((F/name).read_text(encoding='utf-8'))


def load_source():
    value=read('municipal_bulk_source_20261006.json')
    if value['encoding']!='zlib-base64-json-utf8-v1':
        raise ValueError('explicit retained-source fixture encoding required')
    payload=zlib.decompress(base64.b64decode(value['data'],validate=True))
    if len(payload)!=value['decoded_bytes'] or hashlib.sha256(payload).hexdigest()!=value['decoded_sha256']:
        raise ValueError('retained bulk fixture bytes changed')
    return json.loads(payload.decode('utf-8'))
