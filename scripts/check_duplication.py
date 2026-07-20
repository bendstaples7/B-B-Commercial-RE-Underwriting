#!/usr/bin/env python3
"""Structural checks that catch parallel implementations and incomplete migrations."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Files removed during consolidation — must not reappear.
FORBIDDEN_PATHS = [
    "frontend/src/components/LeadCommandCenter.tsx",
    "frontend/src/components/LeadCommandCenter.test.tsx",
    "frontend/src/components/PropertyDetailPage.tsx",
    "frontend/src/components/LeadDetailPage.tsx",
    "frontend/src/components/HubSpotLeadViews.tsx",
    "frontend/src/components/HubSpotLeadViews.test.tsx",
    "frontend/src/components/TimelinePanel.tsx",
    "frontend/src/components/TimelinePanel.test.tsx",
]

# Only these files may assign leads.lead_score / leads.recommended_action.
LEAD_SCORE_WRITER_ALLOWLIST = {
    "backend/app/services/lead_scoring_engine.py",
}

LEAD_RA_ASSIGN_RE = re.compile(
    r"\blead\.recommended_action\s*(?:[-+*/]=|(?!=)=)"
)

# Baseline: handle_errors copies in controllers (should not grow without shared decorator).
MAX_HANDLE_ERRORS_COPIES = 29

# api.ts should shrink over time; threshold allows current size post leadView removal.
API_TS_MAX_LINES = 1600

ROUTE_RE = re.compile(
    r"@\w+\.route\(\s*['\"]([^'\"]+)['\"](?:.*?methods\s*=\s*\[(.*?)\])?",
    re.DOTALL,
)
METHOD_RE = re.compile(r"['\"](\w+)['\"]")
LEAD_SCORE_ASSIGN_RE = re.compile(r"\blead\.lead_score\s*(?:[-+*/]=|(?!=)=)")


def _fail(errors: list[str]) -> None:
    print("Duplication check FAILED:\n", file=sys.stderr)
    for err in errors:
        print(f"  - {err}", file=sys.stderr)
    sys.exit(1)


def check_forbidden_paths() -> list[str]:
    errors: list[str] = []
    for rel in FORBIDDEN_PATHS:
        if (ROOT / rel).exists():
            errors.append(f"Forbidden legacy file still exists: {rel}")
    return errors


def check_duplicate_routes() -> list[str]:
    """Flag full-path route collisions (not blueprint-relative paths)."""
    errors: list[str] = []
    controllers = ROOT / "backend" / "app" / "controllers"
    seen: dict[tuple[str, str], str] = {}

    for path in sorted(controllers.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT).as_posix()
        for match in ROUTE_RE.finditer(text):
            route_path = match.group(1)
            if not route_path.startswith("/api/"):
                continue
            methods_raw = match.group(2)
            methods = METHOD_RE.findall(methods_raw) if methods_raw else ["GET"]
            for method in methods:
                key = (method.upper(), route_path)
                if key in seen:
                    errors.append(
                        f"Duplicate full-path route {method.upper()} {route_path!r}: "
                        f"{seen[key]} and {rel}"
                    )
                else:
                    seen[key] = rel

    return errors


def check_handle_errors_copies() -> list[str]:
    controllers = ROOT / "backend" / "app" / "controllers"
    count = sum(
        1
        for path in controllers.rglob("*.py")
        if "def handle_errors" in path.read_text(encoding="utf-8")
    )
    if count > MAX_HANDLE_ERRORS_COPIES:
        return [
            f"handle_errors defined in {count} controller files "
            f"(max {MAX_HANDLE_ERRORS_COPIES}); extract shared decorator"
        ]
    return []


def check_lead_score_writers() -> list[str]:
    errors: list[str] = []
    services = ROOT / "backend" / "app" / "services"
    for path in sorted(services.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel in LEAD_SCORE_WRITER_ALLOWLIST:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip().startswith("#"):
                continue
            if LEAD_SCORE_ASSIGN_RE.search(line):
                errors.append(
                    f"Unauthorized lead.lead_score write in {rel}:{lineno} "
                    f"(only LeadScoringEngine may set live score)"
                )
            if LEAD_RA_ASSIGN_RE.search(line):
                errors.append(
                    f"Unauthorized lead.recommended_action write in {rel}:{lineno} "
                    f"(only LeadScoringEngine may set recommended action)"
                )
    return errors


def check_api_ts_size() -> list[str]:
    api_ts = ROOT / "frontend" / "src" / "services" / "api.ts"
    if not api_ts.exists():
        return []
    line_count = len(api_ts.read_text(encoding="utf-8").splitlines())
    if line_count > API_TS_MAX_LINES:
        return [
            f"frontend/src/services/api.ts is {line_count} lines "
            f"(max {API_TS_MAX_LINES}); split into domain modules"
        ]
    return []


def check_dead_api_exports() -> list[str]:
    """leadViewService and timelineService were removed with dead components."""
    api_ts = ROOT / "frontend" / "src" / "services" / "api.ts"
    if not api_ts.exists():
        return []
    text = api_ts.read_text(encoding="utf-8")
    errors: list[str] = []
    if "export const leadViewService" in text:
        errors.append("leadViewService still exported in api.ts (use queueService)")
    if "export const timelineService" in text:
        errors.append("timelineService still exported in api.ts (use commandCenterService)")
    return errors


CC_RENDER_RE = re.compile(r"<UnifiedLeadCommandCenter\b([^>]*)/?>", re.DOTALL)
CC_KEY_ATTR_RE = re.compile(r"(^|\s)key\s*=\s*\{(?:numericId|leadId)\}")
CC_LEAD_ID_RE = re.compile(r"<UnifiedLeadCommandCenter\b[^>]*\bleadId\s*=\s*\{(\d+)\}", re.DOTALL)
SCOPE_ROWS_EXPORT_RE = re.compile(r"^export\s+function\s+scopeRowsToLead(?:<|\()", re.MULTILINE)
SCOPE_ROWS_WITH_TOTAL_EXPORT_RE = re.compile(
    r"^export\s+function\s+scopeRowsToLeadWithTotal(?:<|\()",
    re.MULTILINE,
)


def check_lead_command_center_remount_key() -> list[str]:
    """Command Center must remount on lead change so local state cannot bleed.

    Queue advance navigates /leads/:a → /leads/:b without leaving the route.
    Without key={leadId} or key={numericId}, ActivityPanel/dialogs retain prior-lead state.
    """
    app_tsx = ROOT / "frontend" / "src" / "App.tsx"
    if not app_tsx.exists():
        return ["frontend/src/App.tsx missing"]
    text = app_tsx.read_text(encoding="utf-8")
    renders = CC_RENDER_RE.findall(text)
    if not renders:
        return ["UnifiedLeadCommandCenter is not rendered in App.tsx"]
    errors: list[str] = []
    for attrs in renders:
        if not CC_KEY_ATTR_RE.search(attrs):
            errors.append(
                "UnifiedLeadCommandCenter in App.tsx must include "
                "key={numericId} (or key={leadId}) so queue advance remounts "
                "and cannot paint another lead's timeline/tasks"
            )
    return errors


def check_queue_advance_bleed_regression_test() -> list[str]:
    """Require the queue-advance timeline bleed regression to stay in the suite."""
    path = ROOT / "frontend" / "src" / "components" / "UnifiedLeadCommandCenter.test.tsx"
    if not path.exists():
        return ["UnifiedLeadCommandCenter.test.tsx missing"]
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    test_name = "timeline does not bleed across leads"
    test_index = text.find(test_name)
    if test_index < 0:
        errors.append(
            "Missing describe/it for timeline bleed across leads in "
            "UnifiedLeadCommandCenter.test.tsx"
        )
        bleed_test = ""
    else:
        # Keep this scoped to the named regression so an unrelated rerender in
        # the file cannot satisfy the queue-advance guard.
        bleed_test = text[test_index:test_index + 5000]
    if "rerender(" not in bleed_test:
        errors.append(
            "Queue-advance bleed regression must rerender Command Center with a "
            "new leadId (simulates /leads/:a → /leads/:b without remount)"
        )
    rerender_index = bleed_test.find("rerender(")
    before_rerender = bleed_test[:rerender_index] if rerender_index >= 0 else ""
    after_rerender = bleed_test[rerender_index:] if rerender_index >= 0 else ""
    before_lead_ids = set(CC_LEAD_ID_RE.findall(before_rerender))
    after_lead_ids = set(CC_LEAD_ID_RE.findall(after_rerender))
    if not any(before_id != after_id for before_id in before_lead_ids for after_id in after_lead_ids):
        errors.append(
            "Queue-advance bleed regression must rerender with a different leadId"
        )
    util = ROOT / "frontend" / "src" / "utils" / "leadScopedRows.ts"
    if not util.exists():
        errors.append("frontend/src/utils/leadScopedRows.ts missing (fail-closed lead scope)")
    else:
        util_text = util.read_text(encoding="utf-8")
        if not SCOPE_ROWS_EXPORT_RE.search(util_text):
            errors.append("leadScopedRows.ts must export scopeRowsToLead")
        if not SCOPE_ROWS_WITH_TOTAL_EXPORT_RE.search(util_text):
            errors.append("leadScopedRows.ts must export scopeRowsToLeadWithTotal")
    timeline_test = ROOT / "frontend" / "src" / "components" / "LeadTimeline.test.tsx"
    if not timeline_test.exists():
        errors.append("LeadTimeline.test.tsx missing")
    elif "fail-closed lead scope" not in timeline_test.read_text(encoding="utf-8"):
        errors.append(
            "LeadTimeline.test.tsx must keep a 'fail-closed lead scope' regression"
        )
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Check for structural duplication")
    parser.add_argument("--base", default="origin/main", help="Unused; reserved for diff checks")
    args = parser.parse_args()

    errors: list[str] = []
    errors.extend(check_forbidden_paths())
    errors.extend(check_duplicate_routes())
    errors.extend(check_handle_errors_copies())
    errors.extend(check_lead_score_writers())
    errors.extend(check_api_ts_size())
    errors.extend(check_dead_api_exports())
    errors.extend(check_lead_command_center_remount_key())
    errors.extend(check_queue_advance_bleed_regression_test())

    if errors:
        _fail(errors)

    print("Duplication check passed.")


if __name__ == "__main__":
    main()
