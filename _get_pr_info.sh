#!/bin/bash
curl -s -H "Authorization: token $GITHUB_PAT" \
  https://api.github.com/repos/bendstaples7/B-B-Commercial-RE-Underwriting/pulls/36 | python3 -c "
import sys, json
pr = json.load(sys.stdin)
print('TITLE:', pr.get('title', ''))
print('HEAD REF:', pr.get('head', {}).get('ref', ''))
print('HEAD SHA:', pr.get('head', {}).get('sha', ''))
print('BASE:', pr.get('base', {}).get('ref', ''))
print('STATE:', pr.get('state', ''))
print('MERGEABLE:', pr.get('mergeable', ''))
"