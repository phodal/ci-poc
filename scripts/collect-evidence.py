#!/usr/bin/env python3
"""Prepare immutable gate inputs; do not decide ALLOW before remote readback."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

parser=argparse.ArgumentParser()
parser.add_argument('--work-dir',required=True)
parser.add_argument('--tools-dir',required=True)
args=parser.parse_args()
work=Path(args.work_dir).resolve(); gate=str(Path(args.tools_dir).resolve()/'delivery-gate-linux-amd64')
target=work/'gate-input';target.mkdir(mode=0o700,exist_ok=False);objects=target/'objects';objects.mkdir()
plan=json.loads((work/'plan.json').read_text());report=json.loads((work/'output/delivery-report.json').read_text())
def fingerprint(value):
    path=work/'fingerprint-input.json';path.write_text(json.dumps(value)+'\n')
    return json.loads(subprocess.check_output([gate,'fingerprint','--input',str(path)]))['fingerprint']
manifest={'schemaVersion':1,'planFingerprint':fingerprint(plan),'verificationId':report['record']['id'],'resultDigest':fingerprint(report['result']),'objects':[]}
for requirement in plan['policy']['requiredEvidence']:
    source=work/'output/evidence'/requirement['name']
    if not source.is_file() or source.is_symlink():continue
    data=source.read_bytes()
    if len(data)>requirement['maxBytes']:raise ValueError('evidence exceeds policy size')
    value='sha256:'+hashlib.sha256(data).hexdigest()
    (objects/value[7:]).write_bytes(data)
    manifest['objects'].append({'name':requirement['name'],'mediaType':requirement['mediaType'],'id':value,'digest':value,'size':len(data)})
(target/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
shutil.copyfile(work/'plan.json',target/'plan.json')
shutil.copyfile(work/'output/delivery-report.json',target/'delivery-report.json')
# Missing required bytes remain missing, so gate rejects them after upload.
