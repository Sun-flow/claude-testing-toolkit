#!/usr/bin/env python3
"""CI gate: the base branch's tests must still pass against this branch's code.

    python .claude/testing-kit/base_tests.py --base origin/main

1. Runs the fast test command in a worktree of the merge base -> the test IDs
   that passed there.
2. Builds a second worktree from HEAD, then puts back the merge base's copy of
   every test and harness file and removes test/harness files that only exist
   on HEAD (so new conftest files or import-time monkeypatches can't interfere).
   Runs the same command -> the test IDs that pass now.
3. Fails if any test ID that passed on the base doesn't pass now.

Because both runs use the base's tests and harness, editing, skipping,
deleting or renaming tests on the branch can't make this gate pass. It needs
the runner to write JUnit XML to `junit_path` (.claude/testing-kit.json) and
uses `commands.setup` (optional) to install dependencies in each worktree.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402


def run(cmd, cwd: Path, check=True, shell=False) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=cwd, shell=shell, capture_output=True, text=True, errors="replace")
    if check and proc.returncode != 0:
        raise SystemExit(f"command failed: {cmd}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    return proc


def passing_ids(junit: Path) -> tuple[set[str], int]:
    if not junit.is_file():
        return set(), 0
    ok, total = set(), 0
    for case in ET.parse(junit).getroot().iter("testcase"):
        total += 1
        if all(case.find(t) is None for t in ("failure", "error", "skipped")):
            ok.add(f"{case.get('classname', '')}::{case.get('name', '')}")
    return ok, total


def protected(path: str, cfg: dict) -> bool:
    return kitlib.is_test_path(path, cfg) or kitlib.is_harness_path(path, cfg)


def run_suite(tree: Path, cfg: dict) -> tuple[set[str], int, int]:
    setup = (cfg.get("commands") or {}).get("setup")
    if setup:
        run(setup, tree, shell=True)
    junit = tree / cfg.get("junit_path", ".reports/junit.xml")
    junit.parent.mkdir(parents=True, exist_ok=True)
    proc = run(cfg["commands"]["fast"], tree, check=False, shell=True)
    ids, total = passing_ids(junit)
    return ids, total, proc.returncode


def main(argv: list[str]) -> int:
    base = argv[argv.index("--base") + 1] if "--base" in argv else "origin/main"
    root = Path(run(["git", "rev-parse", "--show-toplevel"], Path.cwd()).stdout.strip())
    cfg = kitlib.load_config(root)
    if not (cfg.get("commands") or {}).get("fast"):
        print("No commands.fast in .claude/testing-kit.json; nothing to run.")
        return 2
    merge_base = run(["git", "merge-base", base, "HEAD"], root).stdout.strip()
    work = Path(tempfile.mkdtemp(prefix="base-tests-"))
    base_tree, head_tree = work / "base", work / "head"
    try:
        run(["git", "worktree", "add", "--detach", str(base_tree), merge_base], root)
        run(["git", "worktree", "add", "--detach", str(head_tree), "HEAD"], root)
        base_files = [f for f in run(["git", "ls-tree", "-r", "--name-only", merge_base], root).stdout.splitlines()
                      if protected(f, cfg)]
        head_files = [f for f in run(["git", "ls-tree", "-r", "--name-only", "HEAD"], root).stdout.splitlines()
                      if protected(f, cfg)]
        for f in set(head_files) - set(base_files):
            (head_tree / f).unlink(missing_ok=True)
        if base_files:
            run(["git", "checkout", merge_base, "--", *base_files], head_tree)
        before, total_before, _ = run_suite(base_tree, cfg)
        after, total_after, rc = run_suite(head_tree, cfg)
    finally:
        for tree in (base_tree, head_tree):
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=root, capture_output=True)
        shutil.rmtree(work, ignore_errors=True)
    lost = sorted(before - after)
    report = {"merge_base": merge_base, "base_passed": len(before), "base_total": total_before,
              "head_passed": len(after), "head_total": total_after, "now_failing": lost}
    if "--json" in argv:
        print(json.dumps(report, indent=2))
    else:
        print(f"Base tests on this branch's code: {len(before)} passed on base, {len(after)} pass now.")
        for t in lost[:50]:
            print(f"  NOW FAILING  {t}")
    if total_before == 0:
        print("No tests were collected on the base: check junit_path and commands.fast.")
        return 2
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
