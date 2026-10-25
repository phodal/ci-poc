#!/usr/bin/env python3
"""Capture checkout identity before compilation; never execute candidate code here."""
import json
import os
from pathlib import Path
import re
import subprocess


def capture(event, environ, git):
    pr = event['pull_request']
    repository = environ['GITHUB_REPOSITORY']
    number = int(event['number'])
    if environ['GITHUB_EVENT_NAME'] != 'pull_request' or number <= 0:
        raise ValueError('only pull_request test merges are supported')
    if pr['base']['repo']['full_name'] != repository:
        raise ValueError('base repository mismatch')
    integration = git(['rev-parse', 'HEAD']).strip()
    parents = git(['show', '-s', '--format=%P', 'HEAD']).strip().split()
    base, head = pr['base']['sha'], pr['head']['sha']
    if any(not re.fullmatch(r'[0-9a-f]{40}', x) for x in [integration, base, head]):
        raise ValueError('invalid commit identity')
    if integration != environ['GITHUB_SHA'] or parents != [base, head]:
        raise ValueError('checkout is not the event test merge')
    if environ['GITHUB_REF'] != f'refs/pull/{number}/merge':
        raise ValueError('not the test-merge ref')
    return {'schemaVersion': 1, 'repository': repository, 'number': number,
            'targetRef': 'refs/heads/' + pr['base']['ref'], 'baseSha': base,
            'headSha': head, 'integrationSha': integration,
            'runId': environ['GITHUB_RUN_ID'], 'attempt': environ['GITHUB_RUN_ATTEMPT']}


if __name__ == '__main__':
    event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
    result = capture(event, os.environ, lambda args: subprocess.check_output(['git', *args], text=True))
    # Candidate checkout may contain symlinks or pre-created output paths. Use a
    # fresh runner-owned directory instead; never write artifacts into checkout.
    output = Path(os.environ['RUNNER_TEMP']) / 'candidate-output'
    output.mkdir(exist_ok=False)
    (output / 'capture.json').write_text(json.dumps(result, sort_keys=True) + '\n')
