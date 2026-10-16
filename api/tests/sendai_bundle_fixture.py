"""Synthetic archive builder, never an operational data approval."""
import hashlib
import io
import json
import zipfile
from pathlib import Path
from sendai_transit import SENDAI_MANIFEST_FILENAME, SENDAI_STATIC_URL, SOURCE_ARCHIVE


def write_manifest(root, *, service_date, valid_from='2026-01-01', valid_until='2026-12-31'):
    root=Path(root);data=io.BytesIO();files={p.name:p.read_bytes() for p in root.glob('*.txt')}
    with zipfile.ZipFile(data,'w') as z:
        for name,raw in sorted(files.items()):z.writestr(name,raw)
    archive=data.getvalue();(root/SOURCE_ARCHIVE).write_bytes(archive)
    (root/SENDAI_MANIFEST_FILENAME).write_text(json.dumps({
        'schema_version':2,'source_url':SENDAI_STATIC_URL,'validated_service_date':service_date,
        'fetched_at':'2026-08-21T00:00:00+00:00','sha256':hashlib.sha256(archive).hexdigest(),
        'valid_from':valid_from,'valid_until':valid_until,'published_version':None,
        'file_sha256':{name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()}}),encoding='utf-8')
