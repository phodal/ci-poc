#!/usr/bin/env python3
"""Download only explicitly enabled, immutable, digest-pinned trusted tools."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import urllib.request

root=Path(__file__).resolve().parents[1]
pin=json.loads((root/'acceptance-release.json').read_text())
if pin.get('schemaVersion')!=1 or pin.get('enabled') is not True:
    sys.exit('BLOCK: acceptance binary release has not been configured')
if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}',pin.get('tag','')):
    sys.exit('invalid release tag')
assets=pin.get('assets',{})
if set(assets)!={'delivery-gate-linux-amd64','delivery-acceptance-linux-amd64'}:
    sys.exit('invalid fixed release assets')
out=Path(os.environ['RUNNER_TEMP'])/'trusted-acceptance-tools'
out.mkdir(mode=0o700,exist_ok=False)
for name,expected in assets.items():
    if not re.fullmatch(r'[a-f0-9]{64}',expected):sys.exit('invalid release digest')
    url=f'https://github.com/phodal/ci-poc/releases/download/{pin["tag"]}/{name}'
    with urllib.request.urlopen(url,timeout=60) as response:data=response.read(64*1024*1024+1)
    if len(data)>64*1024*1024 or hashlib.sha256(data).hexdigest()!=expected:sys.exit('release asset digest mismatch')
    path=out/name;path.write_bytes(data);path.chmod(0o500)
