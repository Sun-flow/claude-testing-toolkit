#!/usr/bin/env python3
"""Summarise JUnit XML into the four-part run report (guidelines TG-49).

    python .claude/testing-kit/test_report.py [junit.xml ...] [--json]

Prints: RAN (counts), FAILED (grouped by root-cause signature, so one broken
fixture shows as one group, not 300 lines), NOT TESTED (skipped/xfail with
reasons) and ANOMALIES (zero tests collected, slow tests, reruns).
Exit code: 0 if no failures/errors, 1 otherwise, 3 if no report was found.
"""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path

DIGITS = re.compile(r"0x[0-9a-fA-F]+|\d+(?:\.\d+)?")
QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")


def signature(kind: str, message: str) -> str:
    first = (message or "").strip().splitlines()[0] if (message or "").strip() else ""
    first = QUOTED.sub("'…'", DIGITS.sub("N", first))[:160]
    return f"{kind or 'Failure'}: {first}".strip()


def parse(paths: list[Path]) -> dict:
    out = {"ran": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0, "files": [],
           "groups": OrderedDict(), "not_tested": [], "slow": [], "reruns": [], "time": 0.0}
    times = []
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as exc:
            out.setdefault("unreadable", []).append(f"{path}: {exc}")
            continue
        out["files"].append(str(path))
        for case in root.iter("testcase"):
            name = f"{case.get('classname', '')}::{case.get('name', '')}".strip(":")
            t = float(case.get("time") or 0)
            times.append((t, name))
            out["ran"] += 1
            out["time"] += t
            failure = case.find("failure")
            error = case.find("error")
            skipped = case.find("skipped")
            if case.find("rerunFailure") is not None or case.find("flakyFailure") is not None:
                out["reruns"].append(name)
            if failure is not None or error is not None:
                node = failure if failure is not None else error
                out["failed" if failure is not None else "errors"] += 1
                sig = signature(node.get("type", ""), node.get("message") or (node.text or ""))
                out["groups"].setdefault(sig, []).append(name)
            elif skipped is not None:
                out["skipped"] += 1
                reason = (skipped.get("message") or skipped.text or "no reason given").strip().splitlines()[0]
                out["not_tested"].append(f"{name} ({skipped.get('type', 'skipped')}: {reason[:120]})")
            else:
                out["passed"] += 1
    if times:
        ordered = sorted(t for t, _ in times)
        p95 = ordered[int(0.95 * (len(ordered) - 1))]
        out["slow"] = [f"{n} {t:.1f}s" for t, n in sorted(times, reverse=True)[:5] if t > max(5.0, 3 * p95)]
    return out


def render(r: dict, limit: int = 8) -> str:
    lines = [f"RAN: {r['ran']} tests in {r['time']:.1f}s | passed {r['passed']}, failed {r['failed']}, "
             f"errors {r['errors']}, skipped {r['skipped']}"]
    if r["groups"]:
        lines.append(f"FAILED ({len(r['groups'])} distinct cause(s)):")
        for sig, names in list(r["groups"].items())[:limit]:
            more = f" (+{len(names) - 3} more)" if len(names) > 3 else ""
            lines.append(f"  - {sig}\n      {', '.join(names[:3])}{more}")
    lines.append("NOT TESTED: " + ("none reported by the runner" if not r["not_tested"] else ""))
    for item in r["not_tested"][:limit]:
        lines.append(f"  - {item}")
    if len(r["not_tested"]) > limit:
        lines.append(f"  - … {len(r['not_tested']) - limit} more")
    anomalies = []
    if r["ran"] == 0:
        anomalies.append("zero tests collected: check the path, file naming and markers")
    if r["slow"]:
        anomalies.append("slow tests: " + "; ".join(r["slow"]))
    if r["reruns"]:
        anomalies.append("passed only on rerun (flaky, not clean): " + ", ".join(r["reruns"][:limit]))
    for u in r.get("unreadable", []):
        anomalies.append("unreadable report " + u)
    lines.append("ANOMALIES: " + ("none" if not anomalies else ""))
    lines += [f"  - {a}" for a in anomalies]
    lines.append("Also state which test tiers or configurations you did not run (e.g. integration, e2e, other OS).")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import kitlib
    kitlib.tolerant_output()
    as_json = "--json" in argv
    paths = [Path(a) for a in argv if not a.startswith("--")]
    if not paths:
        root = kitlib.project_dir()
        junit_path = kitlib.load_config(root).get("junit_path") or ""
        if not junit_path:
            print("No JUnit report is configured for this project (junit_path is empty in "
                  ".claude/testing-kit.json). Report the test runner's own summary line instead.")
            return 3
        paths = [root / junit_path]
    paths = [p for p in paths if p.is_file()]
    if not paths:
        print("No JUnit report found. Configure your runner to write one (see .claude/testing-kit.json junit_path).")
        return 3
    r = parse(paths)
    print(json.dumps(r, indent=2, default=list) if as_json else render(r))
    return 0 if r["failed"] == 0 and r["errors"] == 0 and r["ran"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
