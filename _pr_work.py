#!/usr/bin/env python3
"""Get PR #36 details and unresolved review comments."""
import json, os, urllib.request, sys

GH_TOKEN = os.environ.get('GITHUB_TOKEN') or os.environ.get('GITHUB_PAT')
if not GH_TOKEN:
    print("NO_TOKEN")
    sys.exit(1)

def api_get(url):
    req = urllib.request.Request(url)
    req.add_header('Authorization', f'Bearer {GH_TOKEN}')
    req.add_header('Accept', 'application/vnd.github.v3+json')
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

# PR info
pr = api_get('https://api.github.com/repos/bendstaples7/B-B-Commercial-RE-Underwriting/pulls/36')
print(f"TITLE: {pr['title']}")
print(f"HEAD_BRANCH: {pr['head']['ref']}")
print(f"HEAD_SHA: {pr['head']['sha']}")
print(f"BASE_BRANCH: {pr['base']['ref']}")
print(f"STATE: {pr['state']}")
print(f"MERGEABLE: {pr.get('mergeable')}")
print(f"BODY: {pr['body'][:500] if pr['body'] else 'N/A'}")
print("===")

# Get all review comments (inline/diff comments)
page = 1
all_comments = []
while True:
    comments = api_get(f'https://api.github.com/repos/bendstaples7/B-B-Commercial-RE-Underwriting/pulls/36/comments?per_page=100&page={page}')
    if not comments:
        break
    all_comments.extend(comments)
    page += 1
    if page > 10:
        break

print(f"TOTAL_INLINE_COMMENTS: {len(all_comments)}")

for c in all_comments:
    comment_id = c['id']
    path = c['path']
    body = c['body'][:200]
    user = c['user']['login']
    created = c['created_at']
    outdated = c.get('position') is None and c.get('original_position') is not None
    replies_to = c.get('in_reply_to_id', None)
    
    status = "OUTDATED" if outdated else "PENDING_CHECK"
    print(f"COMMENT {comment_id}|{user}|{path}|{status}|replies_to={replies_to}|{body}")

print("===")

print("DONE")