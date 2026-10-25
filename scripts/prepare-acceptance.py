#!/usr/bin/env python3
"""Build a gate plan using trusted binaries, policy and resolved SCM facts."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--candidate-dir',required=True)
    parser.add_argument('--tools-dir',required=True)
    parser.add_argument('--work-dir',required=True)
    parser.add_argument('--database-image',required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    source=Path(args.candidate_dir).resolve();work=Path(args.work_dir).resolve();work.mkdir(mode=0o700,exist_ok=False)
    candidate=json.loads((source/'candidate.json').read_text())
    tools=Path(args.tools_dir).resolve();gate=str(tools/'delivery-gate-linux-amd64');acceptance=str(tools/'delivery-acceptance-linux-amd64')
    def write(name,value):
        path=work/name;path.write_text(json.dumps(value,sort_keys=True)+'\n');return str(path)
    def fingerprint(value):
        path=write('fingerprint-input.json',value)
        return json.loads(subprocess.check_output([gate,'fingerprint','--input',path]))['fingerprint']
    # Import only the exact validated, single scratch candidate. Do not run it.
    subprocess.run(['/usr/bin/docker','load','--input',str(source/'image.tar')],check=True)
    actual=subprocess.check_output(['/usr/bin/docker','image','inspect','--format','{{.Id}}',f'local/candidate:{candidate["runId"]}-{candidate["attempt"]}'],text=True).strip()
    if actual!=candidate['imageConfigDigest']:raise ValueError('loaded candidate image identity differs')
    run_id=f'pr-{candidate["subject"]["members"][0]["number"]}-{candidate["runId"]}-{candidate["attempt"]}'
    config={'executionScope':'disposable-synthetic-ci','fixtureRepository':'phodal/ci-poc',
            'runId':run_id,'appImage':actual,'databaseImage':args.database_image,'docker':'/usr/bin/docker',
            'node':str(Path(shutil.which('node')).resolve()),'chrome':'/opt/google/chrome/chrome',
            'playwrightModule':str(root/'node_modules/playwright-core/index.mjs'),'workDir':str(work/'runtime')}
    config_path=write('recipe.json',config)
    description=json.loads(subprocess.check_output([acceptance,'--config',config_path,'--describe']))
    definition=json.loads((root/'acceptance-policy.json').read_text())
    policy={'digest':fingerprint(definition),**description['bindings'],
            'profileFingerprint':description['profileFingerprint'],'targetFingerprint':description['targetFingerprint'],
            'buildProducer':definition['buildProducer'],'requiredAssertions':description['requiredAssertions'],
            'requiredEvidence':definition['requiredEvidence']}
    subject=candidate['subject']
    build={'subjectFingerprint':fingerprint(subject),'checkoutSha':candidate['checkoutSha'],
           'artifactDigest':actual,'producer':candidate['buildProducer'],'runId':candidate['runId']}
    request={'schemaVersion':1,'requestId':run_id,'candidate':{'repository':subject['repository'],'revision':subject['integrationSha'],'baseRevision':subject['baseSha']},
             'artifact':{'uri':'docker-image://'+actual,'digest':actual},'profileId':description['profileId'],'targetId':description['targetId'],
             'origin':{'provider':'github-actions','runId':candidate['runId'],'attempt':int(candidate['attempt'])}}
    prepared=write('prepare.json',{'subject':subject,'build':build,'policy':policy,'request':request})
    plan=json.loads(subprocess.check_output([gate,'prepare','--input',prepared]))
    write('plan.json',plan);write('policy.json',policy);write('subject.json',subject);write('description.json',description)


if __name__=='__main__':main()
