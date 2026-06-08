import json
import sys

try:
    with open('prs.json', 'r') as f:
        pr_data = json.load(f)
except FileNotFoundError:
    print("Error: prs.json not found.", file=sys.stderr)
    sys.exit(1)
except json.JSONDecodeError:
    print("Error: Could not decode JSON from prs.json.", file=sys.stderr)
    sys.exit(1)

keywords = ["layout", "nav", "deathclock", "homepage", "reorganize", "sidebar"]

found_prs = []

for pr in pr_data:
    pr_number = pr['number']
    pr_title = pr['title'].lower()
    pr_body = pr['body'].lower() if pr['body'] else ''
    
    # Check for keywords
    is_keyword_match = any(keyword in pr_title or keyword in pr_body for keyword in keywords)
    
    # Check for PR #36
    is_pr_36 = (pr_number == 36)

    if is_keyword_match or is_pr_36:
        opened_at = pr['created_at']
        branch = pr['head']['ref']
        
        # Check for P22 overlaps (Quotes + Social Media nav, deathclock as homepage)
        overlaps = []
        if any(term in pr_title or term in pr_body for term in ["quotes", "social media nav"]):
            overlaps.append("Quotes + Social Media nav")
        if any(term in pr_title or term in pr_body for term in ["deathclock", "homepage"]):
            overlaps.append("deathclock as homepage")

        found_prs.append({
            "number": pr_number,
            "title": pr['title'],
            "opened_at": opened_at,
            "branch": branch,
            "overlaps_p22": overlaps if overlaps else ["No direct overlap detected with P22 card work."]
        })

if found_prs:
    for pr in found_prs:
        print(f"PR #{pr['number']}: {pr['title']}")
        print(f"  Opened: {pr['opened_at']}")
        print(f"  Branch: {pr['branch']}")
        print(f"  P22 Overlap: {', '.join(pr['overlaps_p22'])}")
        print("-" * 30)
else:
    print("No relevant PRs found.")
