#!/usr/bin/env python3
"""Exercise only a fixed, hash-verified public release against local synthetic data."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / '.tools'
ARTIFACTS = ROOT / 'artifacts'
EXPECTED_BINARY = '83044cfebcafa6ea47775ab31893052f4bb9ff5d090a48b52253edef398e8135'
TOKEN = 'public-disposable-poc-token'
CHILD_ENV = {'PATH': '/usr/bin:/bin'}

def fetch(url, authenticated=False):
    request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + TOKEN} if authenticated else {})
    with urllib.request.urlopen(request, timeout=1) as response:
        return json.load(response)

def wait_ready(process, url, authenticated=False):
    for _ in range(100):
        if process.poll() is not None:
            raise RuntimeError('Fixture process exited before readiness')
        try:
            return fetch(url, authenticated)
        except OSError:
            time.sleep(0.1)
    raise RuntimeError('Fixture readiness timed out')

def main():
    TOOLS.mkdir(exist_ok=True)
    ARTIFACTS.mkdir(exist_ok=True)
    binary = TOOLS / 'delivery-linux-amd64'
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == EXPECTED_BINARY, 'Release digest mismatch: refusing execution'
    demo_digest = hashlib.sha256((ROOT / 'demo').read_bytes()).hexdigest()
    run_id = os.environ.get('GITHUB_RUN_ID', 'local')
    attempt = os.environ.get('GITHUB_RUN_ATTEMPT', '1')
    revision = os.environ.get('GITHUB_SHA', '0' * 40)
    work = Path(tempfile.mkdtemp(prefix='delivery-', dir=TOOLS))
    token = work / 'token'
    token.write_text(TOKEN)
    token.chmod(0o600)
    config = {
        'listen': {'host': '127.0.0.1', 'port': 8787},
        'profiles': {'quote': {
            'command': [str(TOOLS / 'verify-fixture')], 'cwd': str(ROOT),
            'timeoutMs': 10000, 'requiredAssertions': ['quote-total'], 'allowedTargets': ['good', 'bad']
        }},
        'targets': {
            'good': {'endpoint': 'http://127.0.0.1:8080', 'expectedTotal': 2500},
            'bad': {'endpoint': 'http://127.0.0.1:8080', 'expectedTotal': 2501}
        }
    }
    config_path = work / 'config.json'
    config_path.write_text(json.dumps(config))
    processes = []
    try:
        with (ARTIFACTS / 'delivery-app.log').open('w') as app_log, (ARTIFACTS / 'delivery-server.log').open('w') as server_log:
            app = subprocess.Popen([str(ROOT / 'demo')], cwd=ROOT, env=CHILD_ENV, stdout=app_log, stderr=subprocess.STDOUT)
            processes.append(app)
            wait_ready(app, 'http://127.0.0.1:8080/healthz')
            assert fetch('http://127.0.0.1:8080/artifact')['sha256'] == demo_digest
            service = subprocess.Popen([str(binary), 'serve', '--config', str(config_path), '--data-dir', str(work / 'receipts'), '--token-file', str(token)], cwd=ROOT, env=CHILD_ENV, stdout=server_log, stderr=subprocess.STDOUT)
            processes.append(service)
            wait_ready(service, 'http://127.0.0.1:8787/v1/stats', True)
            results = []
            for name, target, digest, expected_exit, expected_conclusion in [
                ('pass', 'good', demo_digest, 0, 'PASS'),
                ('business-negative', 'bad', demo_digest, 1, 'FAIL'),
                ('artifact-mismatch', 'good', '0' * 64, 2, 'ERROR')
            ]:
                request = {
                    'schemaVersion': 1, 'requestId': f'poc-{name}-{run_id}-{attempt}',
                    'candidate': {'repository': 'phodal/ci-poc', 'revision': revision},
                    'artifact': {'uri': 'https://example.invalid/poc/demo', 'digest': 'sha256:' + digest},
                    'profileId': 'quote', 'targetId': target,
                    'origin': {'provider': 'github-actions', 'runId': run_id}
                }
                request_path = work / (name + '-request.json')
                request_path.write_text(json.dumps(request))
                completed = subprocess.run([str(binary), 'verify', '--request', str(request_path), '--server', 'http://127.0.0.1:8787', '--token-file', str(token), '--timeout-ms', '30000', '--poll-interval-ms', '100'], cwd=ROOT, env=CHILD_ENV, capture_output=True, text=True, timeout=40)
                (ARTIFACTS / ('delivery-' + name + '.json')).write_text(completed.stdout)
                output = json.loads(completed.stdout)
                assert completed.returncode == expected_exit, (name, completed.returncode, output, completed.stderr)
                assert output.get('conclusion') == expected_conclusion, (name, output)
                assert output.get('state') == 'completed', (name, output)
                assert output.get('cleanup') == 'confirmed', (name, output)
                assert output.get('requestId') == request['requestId'], (name, output)
                assert output.get('artifactDigest') == request['artifact']['digest'], (name, output)
                assert output.get('profileId') == 'quote' and output.get('targetId') == target, (name, output)
                for field in ['id', 'requestFingerprint', 'profileFingerprint', 'targetFingerprint', 'completedAt', 'reportUrl']:
                    assert output.get(field), (name, field, output)
                if name == 'artifact-mismatch':
                    assert 'observed artifact digest does not match' in output.get('reason', ''), output
                results.append({'case': name, 'expectedExit': expected_exit, 'actualExit': completed.returncode, 'conclusion': output['conclusion']})
            (ARTIFACTS / 'delivery-cases.json').write_text(json.dumps(results, indent=2))
            print(json.dumps(results, indent=2))
    finally:
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

if __name__ == '__main__':
    main()
