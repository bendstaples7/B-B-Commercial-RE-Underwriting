#!/usr/bin/env python3
import json, subprocess, sys, os

token = os.environ.get('GITHUB_PAT') or os.environ.get('GITHUB_TOKEN')
if not token:
    print("No token found")
    sys.exit(1)

result = subprocess.run([
    'curl', '-s', '-H', f'Authorization: token {token}',
    'https://api.github.com/repos/bendstaples7/B-B-Commercial-RE-Underwriting/pulls/36'
], capture_output=True, text=True)
pr = json.loads(result.stdout)
print('TITLE:', pr.get('title', ''))
print('HEAD REF:', pr.get('head', {}).get('ref', ''))
print('HEAD SHA:', pr.get('head', {}).get('sha', ''))
print('BASE:', pr.get('base', {}).get('ref', ''))
print('STATE:', pr.get('state', ''))
print('MERGEABLE:', pr.get('mergeable', ''))