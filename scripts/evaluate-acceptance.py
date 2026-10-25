#!/usr/bin/env python3
"""Evaluate only after remote evidence readback and fresh SCM resolution."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

parser=argparse.ArgumentParser()
parser.add_argument('--work-dir',required=True)
parser.add_argument('--tools-dir',required=True)
parser.add_argument('--current-candidate',required=True)
args=parser.parse_args()
root=Path(__file__).resolve().parents[1];work=Path(args.work_dir).resolve();tools=Path(args.tools_dir).resolve()
gate=str(tools/'delivery-gate-linux-amd64');acceptance=str(tools/'delivery-acceptance-linux-amd64')
remote=json.loads((work/'remote-evidence.json').read_text())
if remote.get('evidenceUpload')!='COMPLETE':raise SystemExit('required evidence has not completed remote readback')
candidate=json.loads(Path(args.current_candidate).read_text())
description=json.loads(subprocess.check_output([acceptance,'--config',str(work/'recipe.json'),'--describe']))
definition=json.loads((root/'acceptance-policy.json').read_text())
def fingerprint(value):
    path=work/'fingerprint-input.json';path.write_text(json.dumps(value)+'\n')
    return json.loads(subprocess.check_output([gate,'fingerprint','--input',str(path)]))['fingerprint']
policy={'digest':fingerprint(definition),**description['bindings'],
        'profileFingerprint':description['profileFingerprint'],'targetFingerprint':description['targetFingerprint'],
        'buildProducer':definition['buildProducer'],'requiredAssertions':description['requiredAssertions'],
        'requiredEvidence':definition['requiredEvidence']}
(work/'current-policy.json').write_text(json.dumps(policy)+'\n')
(work/'current-subject.json').write_text(json.dumps(candidate['subject'])+'\n')
source=work/'gate-input'
result=subprocess.run([gate,'evaluate','--plan',str(source/'plan.json'),'--report',str(source/'delivery-report.json'),
                       '--manifest',str(source/'manifest.json'),'--current',str(work/'current-subject.json'),
                       '--current-policy',str(work/'current-policy.json'),'--evidence-dir',str(source/'objects')],capture_output=True,text=True)
(work/'decision.json').write_text(result.stdout)
if result.stderr:print(result.stderr,file=sys.stderr)
decision=json.loads(result.stdout)
spec=importlib.util.spec_from_file_location('advisory',root/'scripts/advisory-decision.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
advisory=module.format_advisory(candidate,decision,fingerprint(candidate['subject']),fingerprint(policy))
advisory['remoteEvidence']=remote
(work/'feedback.json').write_text(json.dumps(advisory,indent=2)+'\n')
print(json.dumps({'decision':advisory['verificationDecision'],'scmEnforced':False,'mode':'advisory'}))
raise SystemExit(result.returncode)
