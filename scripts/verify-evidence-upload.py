#!/usr/bin/env python3
"""Read back one GitHub artifact and compare every uploaded gate-input byte."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import urllib.request
import zipfile

parser=argparse.ArgumentParser()
parser.add_argument('--artifact-id',required=True)
parser.add_argument('--expected-digest',required=True)
parser.add_argument('--directory',required=True)
args=parser.parse_args()
if not args.artifact_id.isdigit():raise SystemExit('invalid artifact ID')
repo=os.environ['GITHUB_REPOSITORY'];token=os.environ['GH_READ_TOKEN']
class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not newurl.startswith('https://'):raise ValueError('unsafe redirect')
        result=super().redirect_request(req,fp,code,msg,headers,newurl)
        if result is not None:result.remove_header('Authorization')
        return result
request=urllib.request.Request(f'https://api.github.com/repos/{repo}/actions/artifacts/{args.artifact_id}/zip',headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json'})
with urllib.request.build_opener(Redirect()).open(request,timeout=60) as response:data=response.read(64*1024*1024+1)
expected=args.expected_digest.removeprefix('sha256:')
if len(data)>64*1024*1024 or hashlib.sha256(data).hexdigest()!=expected:raise SystemExit('remote evidence archive digest mismatch')
root=Path(args.directory).resolve()
local={p.relative_to(root).as_posix():p for p in root.rglob('*') if p.is_file() and not p.is_symlink()}
with zipfile.ZipFile(io.BytesIO(data)) as z:
    entries=z.infolist()
    if len({i.filename for i in entries})!=len(entries):raise SystemExit('duplicate remote evidence entry')
    directories={str(Path(name).parent).replace('\\','/')+'/' for name in local if str(Path(name).parent)!='.'}
    for item in entries:
        if item.is_dir() and (item.filename not in directories or item.file_size!=0):raise SystemExit('unexpected evidence directory')
    entries=[item for item in entries if not item.is_dir()]
    if len(entries)!=len(local) or {i.filename for i in entries}!=set(local):raise SystemExit('remote evidence file set mismatch')
    for item in entries:
        if stat.S_ISLNK(item.external_attr>>16) or item.file_size>33554432:raise SystemExit('unsafe evidence entry')
        original=local[item.filename]
        if item.file_size!=original.stat().st_size or z.read(item)!=original.read_bytes():raise SystemExit('remote evidence bytes differ')
print(json.dumps({'evidenceUpload':'COMPLETE','artifactId':args.artifact_id,'archiveDigest':'sha256:'+expected,'files':len(local)}))
