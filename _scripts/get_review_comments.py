import urllib.request
import json
import os

token = os.environ.get("GITHUB_PAT", "")
owner_repo = "bendstaples7/B-B-Commercial-RE-Underwriting"
pr_number = 36

# Get pull request review comments (inline comments on diffs)
req = urllib.request.Request(
    f"https://api.github.com/repos/{owner_repo}/pulls/{pr_number}/comments?per_page=100",
    headers={"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
)
with urllib.request.urlopen(req) as resp:
    comments = json.load(resp)

print(f"=== PULL REQUEST REVIEW COMMENTS: {len(comments)} ===")
for c in comments:
    print(f"\n---")
    print(f"ID: {c['id']}")
    print(f"User: {c['user']['login']}")
    print(f"File: {c.get('path', 'N/A')}")
    print(f"Line: {c.get('line', c.get('original_line', 'N/A'))}")
    print(f"Created: {c.get('created_at', 'N/A')}")
    print(f"Diff Hunk: {c.get('diff_hunk', 'N/A')[:200]}")
    print(f"Body: {c.get('body', 'N/A')}")
    print(f"State: {c.get('state', 'N/A')}")
    # Check if there's a reply (reactions, etc.)
    print(f"Reactions: {json.dumps(c.get('reactions', {}))}")
    print(f"In reply to: {c.get('in_reply_to_id', 'N/A')}")

# Also get issue-level comments (general PR comments)
req2 = urllib.request.Request(
    f"https://api.github.com/repos/{owner_repo}/issues/{pr_number}/comments?per_page=100",
    headers={"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
)
with urllib.request.urlopen(req2) as resp:
    issue_comments = json.load(resp)

print(f"\n\n=== ISSUE COMMENTS: {len(issue_comments)} ===")
for c in issue_comments:
    print(f"\n---")
    print(f"ID: {c['id']}")
    print(f"User: {c['user']['login']}")
    print(f"Created: {c.get('created_at', 'N/A')}")
    print(f"Body: {c.get('body', 'N/A')[:500]}")