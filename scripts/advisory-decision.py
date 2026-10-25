#!/usr/bin/env python3
"""Format an exact-candidate decision without granting SCM merge authority.

No network calls, GitHub tokens, or check-write permissions are used. An actual
publisher must be supplied separately with trusted identity and SCM fencing.
"""
import argparse
import json
from pathlib import Path
import re


def format_advisory(candidate, decision, current_subject_fingerprint, current_policy_fingerprint):
    subject = candidate['subject']
    sha = subject['integrationSha']
    if not re.fullmatch(r'[a-f0-9]{40}', sha):
        raise ValueError('invalid integration SHA')
    if decision.get('decision') not in ['ALLOW', 'BLOCK']:
        raise ValueError('missing gate decision')
    if decision['decision'] == 'ALLOW' and (decision.get('businessConclusion') != 'PASS' or decision.get('evidenceState') != 'COMPLETE'):
        raise ValueError('incoherent allow decision')
    feedback = decision.get('feedback') or {}
    if not re.fullmatch(r'sha256:[a-f0-9]{64}', current_subject_fingerprint) or not re.fullmatch(r'sha256:[a-f0-9]{64}', current_policy_fingerprint):
        raise ValueError('trusted current fingerprints required')
    if decision.get('subjectFingerprint') != current_subject_fingerprint or feedback.get('subjectFingerprint') != current_subject_fingerprint or decision.get('policyFingerprint') != current_policy_fingerprint:
        raise ValueError('decision is stale for current candidate or policy')
    if feedback.get('integrationSha') != sha or feedback.get('members') != subject['members']:
        raise ValueError('feedback belongs to another candidate')
    return {'schemaVersion': 1, 'mode': 'advisory', 'scmEnforced': False,
            'reservedCheckName': 'delivery/acceptance', 'candidate': subject,
            'verificationDecision': decision['decision'],
            'businessConclusion': decision.get('businessConclusion', 'UNKNOWN'),
            'evidenceState': decision.get('evidenceState', 'INCOMPLETE'),
            'feedback': feedback,
            'publication': {'state': 'NOT_PUBLISHED', 'reason': 'Dedicated trusted publisher and SCM freshness enforcement are not configured.'}}


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--decision', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--current-subject-fingerprint', required=True)
    parser.add_argument('--current-policy-fingerprint', required=True)
    args=parser.parse_args()
    result=format_advisory(json.loads(Path(args.candidate).read_text()),json.loads(Path(args.decision).read_text()),args.current_subject_fingerprint,args.current_policy_fingerprint)
    Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'mode':'advisory','scmEnforced':False,'decision':result['verificationDecision']}))
