#!/usr/bin/env python3
"""Build a transient, controlled two-PR fixture without creating remote refs."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('resolver',root/'scripts/resolve-candidate.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)


def resolve_members(repository,trusted_sha,numbers,api):
    r.require(repository=='phodal/ci-poc' and r.SHA.fullmatch(trusted_sha),'only the fixed public fixture is supported')
    r.require(len(numbers)==2 and numbers[0]!=numbers[1] and all(isinstance(n,int) and n>0 for n in numbers),'exactly two distinct PR numbers required')
    prefix='/repos/'+repository
    default=api(prefix)['default_branch'];base=api(prefix+'/git/ref/heads/'+default)['object']['sha']
    r.require(base==trusted_sha,'trusted default policy/base changed')
    members=[]
    for number,branch in zip(numbers,['poc/pr-gate-promotion','poc/pr-gate-express']):
        pr=api(f'{prefix}/pulls/{number}')
        r.require(pr['number']==number and pr['state']=='open' and not pr.get('merged',False),'fixture PR no longer open')
        r.require(pr['base']['repo']['full_name']==repository and pr['base']['ref']==default and pr['base']['sha']==base,'fixture target/base changed')
        r.require(pr['head']['ref']==branch and r.SHA.fullmatch(pr['head']['sha']),'fixture order/branch differs')
        r.fixture_change(repository,trusted_sha,pr,api)
        members.append({'number':number,'headSha':pr['head']['sha']})
    return {'repository':repository,'targetRef':'refs/heads/'+default,'baseSha':base,'members':members}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--promotion-pr',required=True,type=int);parser.add_argument('--express-pr',required=True,type=int)
    parser.add_argument('--trusted-sha',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--current-only',help='recheck the already built trusted composite candidate JSON')
    args=parser.parse_args();repository=os.environ['GITHUB_REPOSITORY'];token=os.environ['GH_READ_TOKEN']
    def api(path):
        r.require(r.valid_api_path(repository,path),'unexpected API destination')
        request=urllib.request.Request('https://api.github.com'+path,headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'})
        with urllib.request.urlopen(request,timeout=30) as response:data=response.read(2*1024*1024+1)
        r.require(len(data)<=2*1024*1024,'oversized API response');return json.loads(data)
    output=Path(args.output).resolve();output.mkdir(mode=0o700,exist_ok=False)
    try:
        current=resolve_members(repository,args.trusted_sha,[args.promotion_pr,args.express_pr],api)
        if args.current_only:
            candidate=json.loads(Path(args.current_only).read_text())
            r.require(candidate.get('mode')=='controlled-composite' and all(candidate['subject'][key]==value for key,value in current.items()),'composite members/base are stale')
            (output/'candidate.json').write_text(json.dumps(candidate,indent=2)+'\n');return
        source=output/'source';source.mkdir();home=output/'build-home';home.mkdir()
        # No inherited GitHub token or host credentials enter git/build commands.
        env={'PATH':os.environ['PATH'],'HOME':str(home),'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':'/dev/null',
             'GIT_TERMINAL_PROMPT':'0','CGO_ENABLED':'0','GOTOOLCHAIN':'local','GOCACHE':str(output/'go-cache'),
             'GOMODCACHE':str(output/'go-modules'),'GOPATH':str(output/'go-path'),'GOTMPDIR':str(output)}
        def command(argv,cwd=source):
            return subprocess.check_output(argv,cwd=cwd,env=env,text=True,stderr=subprocess.STDOUT).strip()
        def git(*args):return command(['git','-c','protocol.file.allow=never',*args])
        git('init');git('config','user.name','Public fixture CI');git('config','user.email','fixture-ci@example.invalid')
        git('remote','add','origin','https://github.com/phodal/ci-poc.git')
        git('fetch','--no-tags','origin',current['baseSha'],*[m['headSha'] for m in current['members']])
        git('checkout','--detach',current['baseSha'])
        history=[]
        for member in current['members']:
            before=git('rev-parse','HEAD');git('merge','--no-ff','--no-edit','--no-gpg-sign',member['headSha'])
            integration=git('rev-parse','HEAD');parents=git('show','-s','--format=%P','HEAD').split()
            r.require(parents==[before,member['headSha']],'actual local merge parent order differs')
            history.append({'sha':integration,'parents':parents,'treeSha':git('rev-parse','HEAD^{tree}')})
        r.require(not git('status','--porcelain'),'candidate checkout is dirty')
        r.require(set(git('diff','--name-only',current['baseSha'],'HEAD').splitlines())=={'fixture_promotion.go','fixture_express.go'},'composite modified unexpected files')
        integration=git('rev-parse','HEAD')
        run_id=os.environ['GITHUB_RUN_ID'];attempt=os.environ['GITHUB_RUN_ATTEMPT']
        r.require(run_id.isdigit() and attempt.isdigit(),'invalid trusted run identity')
        generation=hashlib.sha256(json.dumps({'current':current,'integrationSha':integration,'runId':run_id,'attempt':attempt},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        subject={'kind':'merge_group',**current,'integrationSha':integration,'generation':generation}
        image_context=output/'image-context';image_context.mkdir()
        binary=image_context/'demo'
        command(['go','build','-trimpath','-o',str(binary),'.'])
        shutil.copyfile(root/'candidate.Dockerfile',image_context/'Dockerfile')
        tag=f'local/candidate:{run_id}-{attempt}'
        command(['/usr/bin/docker','build','--tag',tag,str(image_context)])
        command(['/usr/bin/docker','save',tag,'--output',str(output/'image.tar')])
        image_bytes=(output/'image.tar').read_bytes();binary_bytes=binary.read_bytes()
        identity=r.image_identity(image_bytes,run_id,attempt,binary_bytes)
        candidate={'schemaVersion':1,'mode':'controlled-composite','nativeMergeQueue':False,'subject':subject,'checkoutSha':integration,
                   'binaryDigest':r.digest(binary_bytes),'imageArchiveDigest':r.digest(image_bytes),'imageConfigDigest':identity,
                   'runId':run_id,'attempt':attempt,'buildProducer':'github-actions-fixture-v1','trustedRevision':args.trusted_sha,'localMergeHistory':history}
        (output/'candidate.json').write_text(json.dumps(candidate,indent=2)+'\n')
        # A bundle can reproduce the local-only merge SHA without publishing it.
        git('bundle','create',str(output/'candidate.bundle'),'HEAD')
    except Exception as error:
        (output/'feedback.json').write_text(json.dumps({'decision':'BLOCK','stage':'controlled-composite','reason':str(error)})+'\n')
        raise


if __name__=='__main__':main()
