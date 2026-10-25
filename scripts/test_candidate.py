import copy
import base64
import importlib.util
import io
import json
import tarfile
import subprocess
import tempfile
import runpy
from unittest import mock
from pathlib import Path
import unittest
import zipfile


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


resolver = load('resolve-candidate')
capture_module = load('capture-candidate')
advisory_module = load('advisory-decision')
composite_module = load('compose-candidate')
BASE, HEAD, MERGE = [x * 40 for x in 'abc']
TRUSTED = BASE


def fixture():
    capture = {'schemaVersion': 1, 'repository': 'phodal/ci-poc', 'number': 12,
               'targetRef': 'refs/heads/master', 'baseSha': BASE, 'headSha': HEAD,
               'integrationSha': MERGE, 'runId': '123', 'attempt': '1'}
    def tar(entries):
        out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w') as t:
            for name,body in entries.items():
                item=tarfile.TarInfo(name);item.size=len(body);t.addfile(item,io.BytesIO(body))
        return out.getvalue()
    layer=tar({'demo':b'candidate-binary'})
    config=json.dumps({'config':{'User':'65532:65532','Entrypoint':['/demo'],'Env':['PATH=/usr/bin:/bin','LISTEN_ADDR=0.0.0.0:8080']},'rootfs':{'diff_ids':[resolver.digest(layer)]}}).encode()
    config_name=resolver.digest(config)[7:]+'.json'
    image=tar({'manifest.json':json.dumps([{'Config':config_name,'RepoTags':['local/candidate:123-1'],'Layers':['layer.tar']}]).encode(),config_name:config,'layer.tar':layer})
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('capture.json', json.dumps(capture)); z.writestr('demo', b'candidate-binary'); z.writestr('image.tar', image)
    data = archive.getvalue()
    p = '/repos/phodal/ci-poc'
    entries = {
        p: {'default_branch':'master'},
        p+'/git/ref/heads/master': {'object':{'sha':TRUSTED}},
        p+'/actions/runs/123': {'id':123,'repository':{'full_name':'phodal/ci-poc'},'event':'pull_request','path':'.github/workflows/pr-candidate.yml','status':'completed','conclusion':'success','head_sha':HEAD,'run_attempt':1,'pull_requests':[{'number':12}]},
        p+'/pulls/12': {'number':12,'state':'open','merged':False,'base':{'repo':{'full_name':'phodal/ci-poc'},'sha':BASE,'ref':'master'},'head':{'sha':HEAD,'repo':{'full_name':'phodal/ci-poc'},'ref':'poc/pr-gate-promotion'},'merge_commit_sha':MERGE},
        p+'/pulls/12/files?per_page=100': [{'filename':'fixture_promotion.go','status':'modified'}],
        p+'/contents/fixture_promotion.go?ref='+TRUSTED: {'type':'file','encoding':'base64','content':base64.b64encode(b'package main\nconst fixturePromotionEnabled = false\n').decode()},
        p+'/contents/fixture_promotion.go?ref='+HEAD: {'type':'file','encoding':'base64','content':base64.b64encode(b'package main\nconst fixturePromotionEnabled = true\n').decode()},
        p+'/git/ref/pull/12/merge': {'object':{'sha':MERGE}},
        p+'/git/commits/'+MERGE: {'sha':MERGE,'parents':[{'sha':BASE},{'sha':HEAD}]},
        p+'/actions/runs/123/artifacts?per_page=100': {'total_count':1,'artifacts':[{'id':456,'name':'candidate-123-1','expired':False,'size_in_bytes':len(data),'digest':resolver.digest(data),'workflow_run':{'id':123}}]},
    }
    for path in resolver.POLICY_PATHS:
        for ref in [TRUSTED,MERGE]: entries[p+'/contents/'+path+'?ref='+ref]={'type':'file','sha':'e'*40}
    return entries, data


class ResolverTests(unittest.TestCase):
    def test_remote_evidence_readback_exact_bytes_and_directories(self):
        with tempfile.TemporaryDirectory() as td:
            directory=Path(td);(directory/'objects').mkdir();(directory/'objects/object').write_bytes(b'evidence');(directory/'manifest.json').write_bytes(b'{}')
            out=io.BytesIO()
            with zipfile.ZipFile(out,'w') as z:
                z.writestr('objects/',b'');z.writestr('objects/object',b'evidence');z.writestr('manifest.json',b'{}')
            data=out.getvalue()
            script=Path(__file__).with_name('verify-evidence-upload.py')
            argv=[str(script),'--artifact-id','123','--expected-digest',resolver.digest(data),'--directory',td]
            opener=mock.Mock();opener.open.side_effect=lambda *a,**k:io.BytesIO(data)
            with mock.patch('sys.argv',argv),mock.patch.dict('os.environ',{'GITHUB_REPOSITORY':'phodal/ci-poc','GH_READ_TOKEN':'test-only'}),mock.patch('urllib.request.build_opener',return_value=opener):
                runpy.run_path(str(script),run_name='__main__')
                (directory/'objects/object').write_bytes(b'altered!')
                with self.assertRaises(SystemExit):runpy.run_path(str(script),run_name='__main__')

    def test_controlled_composite_uses_ordered_live_heads(self):
        entries,data=fixture();p='/repos/phodal/ci-poc'
        second=copy.deepcopy(entries[p+'/pulls/12']);second['number']=13
        second['head'].update(ref='poc/pr-gate-express',sha='d'*40)
        entries[p+'/pulls/13']=second
        entries[p+'/pulls/13/files?per_page=100']=[{'filename':'fixture_express.go','status':'modified'}]
        entries[p+'/contents/fixture_express.go?ref='+TRUSTED]={'type':'file','encoding':'base64','content':base64.b64encode(b'package main\nconst fixtureExpressEnabled = false\nconst fixtureInteractionFixed = false\n').decode()}
        entries[p+'/contents/fixture_express.go?ref='+'d'*40]={'type':'file','encoding':'base64','content':base64.b64encode(b'package main\nconst fixtureExpressEnabled = true\nconst fixtureInteractionFixed = false\n').decode()}
        current=composite_module.resolve_members('phodal/ci-poc',TRUSTED,[12,13],entries.__getitem__)
        self.assertEqual(current['members'],[{'number':12,'headSha':HEAD},{'number':13,'headSha':'d'*40}])
        with self.assertRaises(composite_module.r.Reject):composite_module.resolve_members('phodal/ci-poc',TRUSTED,[13,12],entries.__getitem__)
        with self.assertRaises(composite_module.r.Reject):composite_module.resolve_members('phodal/ci-poc',TRUSTED,[12,12],entries.__getitem__)
        entries[p+'/contents/fixture_express.go?ref='+'d'*40]['content']=base64.b64encode(b'package main\nconst fixtureExpressEnabled = true\nconst fixtureInteractionFixed = true\n').decode()
        self.assertEqual(len(composite_module.resolve_members('phodal/ci-poc',TRUSTED,[12,13],entries.__getitem__)['members']),2)

    def test_api_destination_is_exact_repository(self):
        self.assertTrue(resolver.valid_api_path('phodal/ci-poc','/repos/phodal/ci-poc'))
        self.assertTrue(resolver.valid_api_path('phodal/ci-poc','/repos/phodal/ci-poc/pulls/1'))
        self.assertFalse(resolver.valid_api_path('phodal/ci-poc','/repos/phodal/ci-poc-other'))
        self.assertFalse(resolver.valid_api_path('phodal/ci-poc','https://example.com'))

    def test_capture_command_isolated_from_candidate_modules(self):
        workflow = Path(__file__).parents[1] / '.github/workflows/pr-candidate.yml'
        self.assertIn('python3 -I scripts/capture-candidate.py', workflow.read_text())
        with tempfile.TemporaryDirectory() as name:
            directory=Path(name)
            (directory/'json.py').write_text('raise RuntimeError("candidate module executed")\n')
            (directory/'probe.py').write_text('import json; print(json.dumps({"isolated":True}))\n')
            result=subprocess.run(['python3','-I',str(directory/'probe.py')],cwd=name,capture_output=True,text=True,check=True)
            self.assertEqual(json.loads(result.stdout),{'isolated':True})

    def call(self, entries, data):
        return resolver.resolve('phodal/ci-poc', TRUSTED, '123', entries.__getitem__, lambda path:data)

    def test_positive(self):
        entries,data=fixture(); result,files=self.call(entries,data)
        self.assertEqual(result['subject']['integrationSha'],MERGE)
        self.assertEqual(result['subject']['members'],[{'number':12,'headSha':HEAD}])
        self.assertEqual(result['binaryDigest'],resolver.digest(b'candidate-binary'))
        self.assertTrue(result['imageConfigDigest'].startswith('sha256:'))

    def test_image_wrong_binary_rejected(self):
        entries,data=fixture();files=resolver.unpack(data)
        with self.assertRaises(resolver.Reject):resolver.image_identity(files['image.tar'],'123','1',b'other-binary')
        with self.assertRaises(resolver.Reject):resolver.image_identity(files['image.tar'],'999','1',files['demo'])

    def test_negative_controls(self):
        p='/repos/phodal/ci-poc'
        mutations=[
            lambda e:e[p+'/pulls/12']['head'].update(ref='unapproved'),
            lambda e:e[p+'/pulls/12']['head']['repo'].update(full_name='attacker/fork'),
            lambda e:e[p+'/pulls/12/files?per_page=100'].append({'filename':'main.go','status':'modified'}),
            lambda e:e[p+'/contents/fixture_promotion.go?ref='+HEAD].update(content=base64.b64encode(b'package main\nconst fixturePromotionEnabled = true\nfunc evil(){}').decode()),
            lambda e:e[p+'/git/ref/heads/master']['object'].update(sha='f'*40),
            lambda e:e[p+'/actions/runs/123'].update(event='push'),
            lambda e:e[p+'/actions/runs/123'].update(conclusion='failure'),
            lambda e:e[p+'/actions/runs/123'].update(head_sha='f'*40),
            lambda e:e[p+'/actions/runs/123'].update(pull_requests=[]),
            lambda e:e[p+'/pulls/12'].update(state='closed'),
            lambda e:e[p+'/pulls/12']['base'].update(sha='f'*40),
            lambda e:e[p+'/git/ref/pull/12/merge']['object'].update(sha='f'*40),
            lambda e:e[p+'/git/commits/'+MERGE].update(parents=[{'sha':HEAD},{'sha':BASE}]),
            lambda e:e[p+'/contents/'+resolver.POLICY_PATHS[0]+'?ref='+MERGE].update(sha='f'*40),
            lambda e:e[p+'/actions/runs/123/artifacts?per_page=100']['artifacts'][0].update(expired=True),
            lambda e:e[p+'/actions/runs/123/artifacts?per_page=100']['artifacts'][0].update(digest='sha256:'+'0'*64),
            lambda e:e[p+'/actions/runs/123/artifacts?per_page=100']['artifacts'][0]['workflow_run'].update(id=999),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                entries,data=fixture(); mutate(entries)
                with self.assertRaises(resolver.Reject):self.call(entries,data)

    def test_zip_traversal_rejected(self):
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w') as z:z.writestr('../escape',b'x')
        with self.assertRaises(resolver.Reject):resolver.unpack(out.getvalue())

    def test_capture_before_compilation(self):
        event={'number':12,'pull_request':{'base':{'repo':{'full_name':'phodal/ci-poc'},'sha':BASE,'ref':'master'},'head':{'sha':HEAD}}}
        env={'GITHUB_REPOSITORY':'phodal/ci-poc','GITHUB_EVENT_NAME':'pull_request','GITHUB_SHA':MERGE,'GITHUB_REF':'refs/pull/12/merge','GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}
        git=lambda args:MERGE if args[0]=='rev-parse' else BASE+' '+HEAD
        result=capture_module.capture(event,env,git);self.assertEqual(result['integrationSha'],MERGE)
        env['GITHUB_SHA']=HEAD
        with self.assertRaises(ValueError):capture_module.capture(event,env,git)

    def test_advisory_never_claims_enforcement(self):
        entries,data=fixture();candidate,_=self.call(entries,data)
        sf,pf='sha256:'+'1'*64,'sha256:'+'2'*64
        feedback={'integrationSha':MERGE,'members':candidate['subject']['members'],'failedAssertions':[],'subjectFingerprint':sf}
        decision={'decision':'ALLOW','businessConclusion':'PASS','evidenceState':'COMPLETE','feedback':feedback,'subjectFingerprint':sf,'policyFingerprint':pf}
        result=advisory_module.format_advisory(candidate,decision,sf,pf)
        self.assertFalse(result['scmEnforced']);self.assertEqual(result['publication']['state'],'NOT_PUBLISHED')
        decision['evidenceState']='INCOMPLETE'
        with self.assertRaises(ValueError):advisory_module.format_advisory(candidate,decision,sf,pf)
        decision.update(decision='BLOCK',businessConclusion='FAIL')
        result=advisory_module.format_advisory(candidate,decision,sf,pf);self.assertEqual(result['verificationDecision'],'BLOCK')
        with self.assertRaises(ValueError):advisory_module.format_advisory(candidate,decision,'sha256:'+'3'*64,pf)
        with self.assertRaises(ValueError):advisory_module.format_advisory(candidate,decision,sf,'sha256:'+'3'*64)
        feedback['integrationSha']=HEAD
        with self.assertRaises(ValueError):advisory_module.format_advisory(candidate,decision,sf,pf)


if __name__=='__main__':unittest.main()
