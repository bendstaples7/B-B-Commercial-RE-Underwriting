.PHONY: pre-pr pre-pr-quick

# Full pre-PR gate: clean ports, start servers, targeted tests, checklist
pre-pr:
	bash scripts/pre-pr-check.sh

# Skip server startup (tests + checklist only)
pre-pr-quick:
	PRE_PR_START_SERVERS=0 bash scripts/pre-pr-check.sh
