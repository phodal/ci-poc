#!/usr/bin/env python3
"""Trusted workflow_run resolver. Candidate archives are data, never scripts.

This is deliberately a single-PR test-merge resolver, not a merge queue or gate.
It rejects changed trusted build definitions and stale base/head/merge identities.
"""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile

POLICY_PATHS = ['.github/workflows/pr-candidate.yml', 'scripts/capture-candidate.py', 'candidate.Dockerfile']
APPROVED_FIXTURES = {
    'poc/pr-gate-promotion': ('fixture_promotion.go', 'fixturePromotionEnabled'),
    'poc/pr-gate-express': ('fixture_express.go', 'fixtureExpressEnabled'),
}
MAX_ARCHIVE = 64 * 1024 * 1024
SHA = re.compile(r'^[a-f0-9]{40}$')
REPO = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')


class Reject(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise Reject(message)


def digest(data):
    return 'sha256:' + hashlib.sha256(data).hexdigest()


def valid_api_path(repository, path):
    prefix = '/repos/' + repository
    return bool(REPO.fullmatch(repository)) and (path == prefix or path.startswith(prefix + '/'))


def fixture_change(repository, trusted_sha, pr, api):
    prefix = '/repos/' + repository
    require(pr['head']['repo']['full_name'] == repository and pr['head']['ref'] in APPROVED_FIXTURES, 'only approved same-repository synthetic fixture PRs may execute acceptance')
    fixture_path, flag = APPROVED_FIXTURES[pr['head']['ref']]
    changed = api(f'{prefix}/pulls/{pr["number"]}/files?per_page=100')
    require(len(changed) == 1 and changed[0]['filename'] == fixture_path and changed[0]['status'] == 'modified', 'fixture PR changes more than its approved feature flag')
    original = api(f'{prefix}/contents/{fixture_path}?ref={trusted_sha}')
    proposed = api(f'{prefix}/contents/{fixture_path}?ref={pr["head"]["sha"]}')
    require(original['type'] == proposed['type'] == 'file' and original['encoding'] == proposed['encoding'] == 'base64', 'invalid fixture feature source')
    original_bytes = base64.b64decode(original['content']); proposed_bytes = base64.b64decode(proposed['content'])
    before = f'const {flag} = false'.encode(); after = f'const {flag} = true'.encode()
    expected = original_bytes.replace(before, after, 1)
    permitted = [expected]
    if flag == 'fixtureExpressEnabled':
        repair = b'const fixtureInteractionFixed = false'
        require(original_bytes.count(repair) == 1, 'trusted repair fixture is missing')
        permitted.append(expected.replace(repair, b'const fixtureInteractionFixed = true', 1))
    require(original_bytes.count(before) == 1 and proposed_bytes in permitted, 'fixture feature change is not an approved exact toggle/repair variant')


def unpack(data):
    require(len(data) <= MAX_ARCHIVE, 'candidate archive too large')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        entries = archive.infolist()
        require(len(entries) == 3 and {x.filename for x in entries} == {'capture.json', 'demo', 'image.tar'}, 'unexpected candidate archive members')
        result = {}
        for item in entries:
            mode = item.external_attr >> 16
            require(not stat.S_ISLNK(mode) and not item.is_dir(), 'non-file archive member')
            limit = 16384 if item.filename == 'capture.json' else MAX_ARCHIVE
            require(0 < item.file_size <= limit and not item.flag_bits & 1, 'invalid archive member size or encryption')
            require(sum(x.file_size for x in entries) <= MAX_ARCHIVE, 'unpacked candidate too large')
            result[item.filename] = archive.read(item)
        return result


def image_identity(data, run_id, attempt, binary):
    """Inspect a fixed scratch image without extracting or loading its bytes."""
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as image:
        members = image.getmembers()
        require(len(members) <= 32 and sum(x.size for x in members) <= MAX_ARCHIVE, 'image archive exceeds limits')
        names = [x.name for x in members]
        require(len(names) == len(set(names)), 'duplicate image archive entries')
        for member in members:
            require(not member.name.startswith('/') and '..' not in member.name.split('/') and (member.isfile() or member.isdir()), 'unsafe image archive entry')
        def read(name):
            member = image.getmember(name)
            require(member.isfile() and member.size <= MAX_ARCHIVE, 'invalid image object')
            return image.extractfile(member).read()
        manifest = json.loads(read('manifest.json'))
        require(len(manifest) == 1, 'candidate archive must contain exactly one image')
        item = manifest[0]
        require(item['RepoTags'] == [f'local/candidate:{run_id}-{attempt}'] and len(item['Layers']) == 1, 'unexpected candidate image tag/layers')
        config_bytes = read(item['Config']); config = json.loads(config_bytes)
        config_digest = digest(config_bytes)
        require(item['Config'].split('/')[-1].removesuffix('.json') == config_digest[7:], 'image config filename digest mismatch')
        runtime = config['config']
        require(runtime['User'] == '65532:65532' and runtime['Entrypoint'] == ['/demo'] and not runtime.get('Cmd'), 'unexpected image execution configuration')
        require(sorted(runtime.get('Env', [])) == ['LISTEN_ADDR=0.0.0.0:8080', 'PATH=/usr/bin:/bin'] and not runtime.get('Volumes') and not runtime.get('OnBuild'), 'unexpected image environment or volumes')
        layer_bytes = read(item['Layers'][0])
        require(config['rootfs']['diff_ids'] == [digest(layer_bytes)], 'image layer digest mismatch')
        with tarfile.open(fileobj=io.BytesIO(layer_bytes), mode='r:') as layer:
            files = layer.getmembers()
            require(len(files) == 1 and files[0].name in ['demo', './demo'] and files[0].isfile(), 'unexpected candidate filesystem')
            require(files[0].size == len(binary) and layer.extractfile(files[0]).read() == binary, 'image executable differs from captured artifact')
        return config_digest


def resolve(repository, trusted_sha, run_id, api, download):
    require(REPO.fullmatch(repository) and SHA.fullmatch(trusted_sha), 'invalid trusted repository/revision')
    require(repository == 'phodal/ci-poc', 'this acceptance slice is restricted to the public synthetic fixture repository')
    require(str(run_id).isdigit(), 'invalid run ID')
    prefix = '/repos/' + repository
    repo = api(prefix)
    default = repo['default_branch']
    require(re.fullmatch(r'[A-Za-z0-9_./-]+', default), 'invalid default branch')
    trusted_current = api(f'{prefix}/git/ref/heads/{default}')['object']['sha']
    require(trusted_current == trusted_sha, 'trusted default policy revision changed')
    run = api(f'{prefix}/actions/runs/{run_id}')
    require(run['repository']['full_name'] == repository and str(run['id']) == str(run_id), 'wrong build repository/run')
    require(run['event'] == 'pull_request' and run['path'].split('@')[0] == POLICY_PATHS[0], 'unexpected build workflow')
    require(run['status'] == 'completed' and run['conclusion'] == 'success', 'candidate build did not succeed')
    require(len(run.get('pull_requests', [])) == 1, 'ambiguous PR association')
    number = run['pull_requests'][0]['number']
    require(isinstance(number, int) and number > 0, 'invalid PR number')
    pr = api(f'{prefix}/pulls/{number}')
    require(pr['state'] == 'open' and not pr.get('merged', False), 'PR is no longer open')
    require(pr['base']['repo']['full_name'] == repository, 'PR base repository changed')
    require(pr['base']['ref'] == default and pr['base']['sha'] == trusted_current, 'first slice requires current default-branch base')
    base, head, merge = pr['base']['sha'], pr['head']['sha'], pr.get('merge_commit_sha', '')
    require(all(SHA.fullmatch(x or '') for x in [base, head, merge]), 'candidate is not mergeable/resolved')
    require(pr['number'] == number, 'PR response number mismatch')
    fixture_change(repository, trusted_sha, pr, api)
    current_ref = api(f'{prefix}/git/ref/pull/{number}/merge')['object']['sha']
    require(current_ref == merge, 'test merge changed during resolution')
    commit = api(f'{prefix}/git/commits/{merge}')
    require(commit['sha'] == merge and [x['sha'] for x in commit['parents']] == [base, head], 'test merge parents do not match current base/head')
    # GitHub run head_sha can identify the PR head rather than its test merge.
    # Neither value alone proves checkout: verify the captured merge below.
    require(run['head_sha'] in [head, merge], 'build run belongs to an older head')
    policy_blobs = {}
    for path in POLICY_PATHS:
        def blob(ref):
            return api(f'{prefix}/contents/{path}?ref={ref}')
        trusted, built = blob(trusted_sha), blob(merge)
        require(trusted['type'] == built['type'] == 'file' and trusted['sha'] == built['sha'], 'candidate modified trusted build policy: ' + path)
        policy_blobs[path] = trusted['sha']
    attempt = str(run['run_attempt'])
    expected_name = f'candidate-{run_id}-{attempt}'
    artifacts = api(f'{prefix}/actions/runs/{run_id}/artifacts?per_page=100')
    require(artifacts['total_count'] <= 100, 'ambiguous artifact pagination')
    matches = [x for x in artifacts['artifacts'] if x['name'] == expected_name]
    require(len(matches) == 1, 'candidate artifact absent or duplicated')
    artifact = matches[0]
    require(not artifact['expired'] and 0 < artifact['size_in_bytes'] <= MAX_ARCHIVE, 'artifact expired or too large')
    require(artifact['workflow_run']['id'] == int(run_id), 'artifact associated with another run')
    data = download(f'{prefix}/actions/artifacts/{artifact["id"]}/zip')
    require(digest(data) == artifact.get('digest'), 'GitHub artifact archive digest mismatch or missing')
    files = unpack(data)
    capture = json.loads(files['capture.json'])
    expected = {'schemaVersion': 1, 'repository': repository, 'number': number,
                'targetRef': 'refs/heads/' + pr['base']['ref'], 'baseSha': base,
                'headSha': head, 'integrationSha': merge, 'runId': str(run_id), 'attempt': attempt}
    require(capture == expected, 'build checkout capture does not match current candidate')
    image_digest = image_identity(files['image.tar'], run_id, attempt, files['demo'])
    # Identity generation changes whenever the candidate tuple changes, and is
    # computed here from API state, not accepted from the PR artifact.
    generation = hashlib.sha256(json.dumps(expected, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    subject = {'kind': 'pr_merge', 'repository': repository, 'targetRef': expected['targetRef'],
               'baseSha': base, 'members': [{'number': number, 'headSha': head}],
               'integrationSha': merge, 'generation': generation}
    return {'schemaVersion': 1, 'subject': subject, 'checkoutSha': merge,
            'binaryDigest': digest(files['demo']), 'imageArchiveDigest': digest(files['image.tar']),
            'imageConfigDigest': image_digest,
            'archiveDigest': digest(data), 'artifactId': artifact['id'],
            'runId': str(run_id), 'attempt': attempt, 'buildProducer': 'github-actions-fixture-v1',
            'trustedRevision': trusted_sha, 'buildPolicyBlobs': policy_blobs}, files


class NoCredentialRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Redirect destinations never receive the GitHub token.
        parsed = urllib.parse.urlparse(newurl)
        if parsed.scheme != 'https' or parsed.username or parsed.password:
            raise Reject('unsafe artifact redirect')
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header('Authorization')
        return redirected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--trusted-sha', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    repository = os.environ['GITHUB_REPOSITORY']
    token = os.environ['GH_READ_TOKEN']
    opener = urllib.request.build_opener(NoCredentialRedirect())
    def request(path, max_bytes):
        require(valid_api_path(repository, path), 'unexpected API destination')
        req = urllib.request.Request('https://api.github.com' + path, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28'})
        with opener.open(req, timeout=30) as response:
            data = response.read(max_bytes + 1)
            require(len(data) <= max_bytes, 'GitHub response too large')
            return data
    out = Path(args.output); out.mkdir(parents=True, exist_ok=False)
    try:
        result, files = resolve(repository, args.trusted_sha, args.run_id,
                                lambda path: json.loads(request(path, 2*1024*1024)),
                                lambda path: request(path, MAX_ARCHIVE))
        (out / 'candidate.json').write_text(json.dumps(result, indent=2) + '\n')
        # Only write known data filenames. Never extract an archive or chmod/run
        # candidate content on this trusted resolver's host.
        (out / 'image.tar').write_bytes(files['image.tar'])
        print(json.dumps({'candidate': result['subject'], 'artifactId': result['artifactId']}))
    except (Reject, KeyError, TypeError, json.JSONDecodeError, zipfile.BadZipFile, tarfile.TarError) as error:
        (out / 'feedback.json').write_text(json.dumps({'decision': 'BLOCK', 'stage': 'candidate-resolution', 'reason': str(error), 'runId': args.run_id}) + '\n')
        raise SystemExit('candidate blocked: ' + str(error))


if __name__ == '__main__':
    main()
