#!/usr/bin/env python3
"""Build a markdown CI summary from job results and JUnit XML artifacts."""
from __future__ import annotations

import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


PERF_CLASS_NAMES = {
    "TestDashboardPerformance",
    "TestExcelExportPerformance",
    "TestWritePathTiming",
}

TIMING_FAILURE_RE = re.compile(
    r"(took \d+(?:\.\d+)? (?:ms|s)|limit: \d+ (?:ms|s)|under_\d+ms|under_\d+s)",
    re.IGNORECASE,
)


@dataclass
class FailedTest:
    job: str
    name: str
    file: str
    message: str
    tail: list[str] = field(default_factory=list)
    likely_flake: bool = False


@dataclass
class JobResult:
    name: str
    conclusion: str
    url: str = ""


def _tail_lines(text: str, n: int = 20) -> list[str]:
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    return lines[-n:]


def _is_likely_flake(test_name: str, message: str, file_path: str) -> bool:
    if "performance" in test_name.lower():
        return True
    for cls in PERF_CLASS_NAMES:
        if cls in test_name:
            return True
    if "test_multifamily_pro_forma_e2e.py" in file_path and TIMING_FAILURE_RE.search(message):
        return True
    return bool(TIMING_FAILURE_RE.search(message))


def _parse_junit(path: Path, job: str) -> list[FailedTest]:
    failures: list[FailedTest] = []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        failures.append(
            FailedTest(
                job=job,
                name="(junit parse error)",
                file=str(path),
                message=str(exc),
            )
        )
        return failures

    for case in root.iter("testcase"):
        failure = case.find("failure") or case.find("error")
        if failure is None:
            continue
        classname = case.get("classname") or ""
        test_name = case.get("name") or "(unknown)"
        full_name = f"{classname}::{test_name}" if classname else test_name
        file_path = case.get("file") or classname.replace(".", "/") + ".py"
        message = (failure.get("message") or failure.text or "").strip()
        tail = _tail_lines(failure.text or message)
        failures.append(
            FailedTest(
                job=job,
                name=full_name,
                file=file_path,
                message=message.splitlines()[0] if message else "(no message)",
                tail=tail,
                likely_flake=_is_likely_flake(full_name, message, file_path),
            )
        )
    return failures


def _parse_log_failures(path: Path, job: str) -> list[FailedTest]:
    text = path.read_text(encoding="utf-8", errors="replace")
    failures: list[FailedTest] = []
    for match in re.finditer(
        r"^FAILED\s+(\S+)\s+-\s+(.+)$",
        text,
        flags=re.MULTILINE,
    ):
        nodeid = match.group(1)
        message = match.group(2).strip()
        file_path = nodeid.split("::")[0]
        failures.append(
            FailedTest(
                job=job,
                name=nodeid,
                file=file_path,
                message=message,
                tail=_tail_lines(text[match.start() :]),
                likely_flake=_is_likely_flake(nodeid, message, file_path),
            )
        )
    return failures


def build_summary(
    jobs: list[JobResult],
    artifact_dir: Path,
    run_url: str,
    rerun_workflow_url: str,
) -> str:
    failed_jobs = [j for j in jobs if j.conclusion not in ("success", "skipped", "cancelled")]
    blocking_failed = [
        j for j in failed_jobs if j.name != "Backend — performance tests (non-blocking)"
    ]

    lines: list[str] = ["## CI summary", ""]

    if not failed_jobs:
        lines.append("All jobs passed.")
        if run_url:
            lines.append(f"\n[View run]({run_url})")
        return "\n".join(lines)

    if blocking_failed:
        lines.append(f"**{len(blocking_failed)} blocking job(s) failed.**")
    else:
        lines.append("Blocking jobs passed. Performance tests failed (non-blocking).")

    if run_url:
        lines.append(f"\n[View full run]({run_url})")
    if rerun_workflow_url:
        lines.append(
            f" · [Re-run a single job]({rerun_workflow_url}) "
            "(Actions → CI re-run job → Run workflow)"
        )

    lines.append("")
    lines.append("| Job | Result |")
    lines.append("| --- | --- |")
    for job in jobs:
        icon = "✅" if job.conclusion == "success" else "⚠️" if job.conclusion == "failure" and "performance" in job.name.lower() else "❌"
        if job.conclusion == "skipped":
            icon = "⏭️"
        link = f"[{job.name}]({job.url})" if job.url else job.name
        lines.append(f"| {icon} {link} | {job.conclusion} |")

    all_failures: list[FailedTest] = []
    if artifact_dir.is_dir():
        for junit in sorted(artifact_dir.rglob("*.xml")):
            job = junit.parent.name.replace("_", " ")
            all_failures.extend(_parse_junit(junit, job))
        for log in sorted(artifact_dir.rglob("pytest-output.txt")):
            job = log.parent.name.replace("_", " ")
            all_failures.extend(_parse_log_failures(log, job))

    if all_failures:
        lines.append("")
        lines.append("### Failed tests")
        for idx, fail in enumerate(all_failures, 1):
            flake = " — **likely flake** (timing/performance)" if fail.likely_flake else ""
            lines.append(f"\n#### {idx}. `{fail.name}`{flake}")
            lines.append(f"- **Job:** {fail.job}")
            lines.append(f"- **File:** `{fail.file}`")
            lines.append(f"- **Message:** {fail.message}")
            if fail.tail:
                lines.append("- **Last lines:**")
                lines.append("```")
                lines.extend(fail.tail)
                lines.append("```")
    elif blocking_failed:
        lines.append("")
        lines.append("### Failed jobs (no JUnit artifact)")
        for job in blocking_failed:
            lines.append(f"- **{job.name}** — check the [job log]({job.url})")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--jobs-json", required=True, help="JSON array of {name, conclusion, url}")
    parser.add_argument("--artifact-dir", default="ci-artifacts")
    parser.add_argument("--run-url", default="")
    parser.add_argument("--rerun-workflow-url", default="")
    parser.add_argument("--output", default="-")
    args = parser.parse_args()

    jobs = [JobResult(**item) for item in json.loads(Path(args.jobs_json).read_text())]
    summary = build_summary(
        jobs=jobs,
        artifact_dir=Path(args.artifact_dir),
        run_url=args.run_url,
        rerun_workflow_url=args.rerun_workflow_url,
    )

    if args.output == "-":
        sys.stdout.write(summary)
    else:
        Path(args.output).write_text(summary, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
