#!/bin/bash
# Get all review comments on PR #36 (including unresolved ones)
curl -s -H "Authorization: token $GITHUB_PAT" \
  "https://api.github.com/repos/bendstaples7/B-B-Commercial-RE-Underwriting/pulls/36/comments?per_page=100" | python3 -c "
import sys, json
comments = json.load(sys.stdin)
print(f'Total review comments: {len(comments)}')
print()
for c in comments:
    unresolved = c.get('position') is not None or c.get('in_reply_to_id', '') == ''
    # Comments that have been resolved have a resolved_at field
    resolved_at = c.get('resolved_at')
    is_resolved = resolved_at is not None
    print(f'--- COMMENT ID: {c[\"id\"]} ---')
    print(f'  Path: {c.get(\"path\", \"\")}')
    print(f'  Line: {c.get(\"line\", \"\")} / Position: {c.get(\"position\", \"\")}')
    print(f'  Resolved: {is_resolved} (resolved_at: {resolved_at})')
    print(f'  Author: {c.get(\"user\", {}).get(\"login\", \"\")}')
    body = c.get('body', '')
    print(f'  Body: {body[:300]}')
    print()
"