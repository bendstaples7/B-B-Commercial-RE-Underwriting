.PHONY: pre-pr pre-pr-quick hooks

# Full pre-PR gate: clean ports, start servers, targeted tests, checklist
pre-pr:
	bash scripts/pre-pr-check.sh

# Skip server startup (tests + checklist only)
pre-pr-quick:
	PRE_PR_START_SERVERS=0 bash scripts/pre-pr-check.sh

# Install versioned git hooks (.githooks via core.hooksPath).
# Windows without make: powershell -File scripts/install-git-hooks.ps1
hooks:
	git config core.hooksPath .githooks
	@echo core.hooksPath=$$(git config --get core.hooksPath)
	@echo Git hooks installed. Pre-commit is slim/mapped; CI owns the full suite.
