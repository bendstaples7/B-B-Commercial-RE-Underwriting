import urllib.request
import json
import os

token = os.environ.get("GITHUB_PAT", "")
owner_repo = "bendstaples7/B-B-Commercial-RE-Underwriting"
pr_number = 36

req = urllib.request.Request(
    f"https://api.github.com/repos/{owner_repo}/pulls/{pr_number}",
    headers={"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
)
with urllib.request.urlopen(req) as resp:
    pr = json.load(resp)

print(json.dumps({
    "title": pr["title"],
    "state": pr["state"],
    "base": pr["base"]["ref"],
    "head": pr["head"]["ref"],
    "head_sha": pr["head"]["sha"],
    "mergeable": pr.get("mergeable"),
    "draft": pr.get("draft", False),
    "body": pr.get("body", "")[:500]
}, indent=2))