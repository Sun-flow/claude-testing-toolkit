#!/usr/bin/env python3
"""CI/local check: did this branch weaken the test suite?  Standard library only.

    python .claude/testing-kit/test_diff_guard.py [--base BRANCH] [--json]

Compares HEAD with the merge base (of BRANCH; default: the repo's default branch) and reports:
  BLOCK  deleted or renamed-away test files; test functions that disappeared;
         added skip/xfail/only markers; snapshot/golden files changed; harness
         files changed (runner/coverage config, conftest, CI, .claude/ kit);
         production code that checks whether it runs under a test
  WARN   removed assertion lines; added sleeps/retries; new test files with no
         recognisable test; changed test files with no failure-path test;
         changes to a file the test command goes through (`runner_files`)
Exit 1 when there is any BLOCK finding, unless ALLOW_TEST_CHANGES=1 is set
(e.g. from a PR label a human adds). Guidelines: TG-14..TG-18, TG-35.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
import os
import re
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in the repo
sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402
from protect_tests import section_changed  # noqa: E402

ASSERT_LINE = re.compile(r"\bassert\b|\bexpect\(|\bassert[A-Z]\w*\(|\bt\.(?:Error|Fatal)|\brequire\.|\bshould\b")
FAILURE_PATH = re.compile(r"pytest\.raises|assertRaises|\.toThrow|\.rejects\b|assertThrows|require\.Error|"
                          r"if err == nil|\b(?:4\d\d|5\d\d)\b|invalid|reject|error|fail|empty|missing|"
                          r"overflow|unauthori[sz]ed|forbidden|denied", re.I)
TEST_ENV_RE = kitlib.TEST_ENV_RE  # shared with the guard_test_edits hook; a heuristic, see TG-16
IGNORED = ["**/__pycache__/**", "**/*.pyc"]


def git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=root, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if out.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def show(root: Path, rev: str, path: str) -> str:
    out = subprocess.run(["git", "show", f"{rev}:{path}"], cwd=root, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    return out.stdout if out.returncode == 0 else ""


def diff_lines(root: Path, base: str, path: str, old_path: str | None = None) -> tuple[list[str], list[str]]:
    if old_path and old_path != path:  # a rename: diff the new file against the old one
        patch = git(root, "diff", "--unified=0", "-M", f"{base}...HEAD", "--", old_path, path)
    else:
        patch = git(root, "diff", "--unified=0", f"{base}...HEAD", "--", path)
    added = [l[1:] for l in patch.splitlines() if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:] for l in patch.splitlines() if l.startswith("-") and not l.startswith("---")]
    return added, removed


def analyse(root: Path, base: str) -> dict:
    merge_base = git(root, "merge-base", base, "HEAD").strip()
    cfg = kitlib.load_config_at(root, merge_base)  # the base's config: the branch can't redefine what a test is
    status = git(root, "diff", "--name-status", "-M", f"{merge_base}...HEAD")
    block, warn = [], []
    base_files = git(root, "ls-tree", "-r", "--name-only", merge_base).splitlines()
    base_has_tests = kitlib.has_tests(base_files, cfg)
    for line in status.splitlines():
        parts = line.split("\t")
        code, paths = parts[0], parts[1:]
        old_path, new_path = paths[0], paths[-1]
        if kitlib.matches_any(new_path, IGNORED):
            continue  # bytecode the hooks may leave behind; not a harness change
        junit_dir = str(Path(cfg.get("junit_path", ".reports/junit.xml")).parent.as_posix())
        if code[0] in "AMR" and junit_dir not in ("", ".") and new_path.startswith(junit_dir + "/"):
            block.append(f"test report committed: {new_path} (reports must come from the CI run)")
            continue
        is_test_old = kitlib.is_test_path(old_path, cfg)
        is_test_new = kitlib.is_test_path(new_path, cfg)
        harness = kitlib.is_harness_path(new_path, cfg) or kitlib.is_harness_path(old_path, cfg)
        if harness:
            if code[0] == "A" and not base_has_tests and not new_path.startswith((".claude/", ".github/")):
                warn.append(f"harness file added: {new_path} (no tests on the base yet, so nothing to weaken)")
            else:
                block.append(f"harness file changed: {new_path} ({code})")
            continue
        if kitlib.matches_any(new_path, cfg.get("runner_files") or []):
            warn.append(f"test runner file changed: {new_path} (the test command goes through it; the "
                        "base-tests gate runs with the base's copy)")
        sections = kitlib.harness_section_patterns(new_path, cfg)
        if sections and code[0] in "AMD":
            # an added file counts too: a new setup.cfg can carry a [tool:pytest] section
            before_text = show(root, merge_base, old_path) if code[0] != "A" else ""
            after_text = show(root, "HEAD", new_path) if code[0] != "D" else ""
            if section_changed(new_path, before_text, after_text, sections):
                block.append(f"test/coverage configuration section changed in {new_path}")
        if code.startswith("D") and is_test_old:
            block.append(f"test file deleted: {old_path}")
            continue
        if code.startswith("R") and is_test_old and not is_test_new:
            block.append(f"test file renamed out of test discovery: {old_path} -> {new_path}")
            continue
        if not (is_test_old or is_test_new):
            if code[0] in "AM" and not kitlib.is_prose(new_path):
                added, _ = diff_lines(root, merge_base, new_path)
                if any(TEST_ENV_RE.search(a) for a in added):
                    block.append(f"production code checks for a test environment: {new_path} (TG-16)")
                if any(kitlib.NO_COVER_RE.search(a) for a in added):
                    block.append(f"coverage-exclusion pragma added in {new_path} (TG-33)")
            continue
        if kitlib.matches_any(new_path, ["**/__snapshots__/**", "**/*.snap", "**/snapshots/**", "**/*.approved.*",
                                         "**/*.golden", "**/golden/**"]) and code[0] in "MD":
            block.append(f"snapshot/golden file changed: {new_path} (needs a human to approve each hunk)")
            continue
        before = show(root, merge_base, old_path) if code[0] != "A" else ""
        after = show(root, "HEAD", new_path)
        added, removed = diff_lines(root, merge_base, new_path, old_path)
        before_names, after_names = kitlib.qualified_test_names(before), kitlib.qualified_test_names(after)
        before_c, after_c = Counter(before_names), Counter(after_names)
        lost = sorted(n for n in before_c if after_c[n] < before_c[n])
        if lost:
            block.append(f"tests removed from {new_path}: {', '.join(lost[:8])}")
        if any(kitlib.SKIP_RE.search(a) for a in added):
            block.append(f"skip/xfail/only marker added in {new_path}")
        removed_asserts = [r for r in removed if ASSERT_LINE.search(r)]
        if removed_asserts:
            warn.append(f"{len(removed_asserts)} assertion line(s) removed or changed in {new_path}")
        if any(kitlib.SLEEP_RE.search(a) or kitlib.RETRY_RE.search(a) for a in added):
            warn.append(f"sleep or retry added in {new_path}")
        if code[0] == "A" and not kitlib.test_names(after) and not kitlib.matches_any(
                new_path, ["**/fixtures/**", "**/testdata/**", "**/__snapshots__/**", "**/*.snap", "**/conftest.py",
                           "**/helpers/**", "**/utils/**", "**/*.json", "**/*.md"]):
            warn.append(f"new test file with no recognisable test: {new_path}")
        new_tests = set(kitlib.test_names(after)) - set(kitlib.test_names(before))
        if new_tests and not FAILURE_PATH.search("\n".join(added)):
            warn.append(f"{new_path}: {len(new_tests)} new test(s), none on an error/boundary path (TG-10, TG-35)")
    return {"base": base, "merge_base": merge_base, "block": block, "warn": warn}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="Did this branch weaken the test suite?")
    ap.add_argument("--base", help="branch or commit to compare with (default: the repo's default branch)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    kitlib.tolerant_output()
    root = Path(git(Path.cwd(), "rev-parse", "--show-toplevel").strip())
    base = a.base or kitlib.default_base(root)
    r = analyse(root, base)
    if a.json:
        print(json.dumps(r, indent=2))
    else:
        print(f"Test diff guard against {base} (merge base {r['merge_base'][:10]})")
        for b in r["block"]:
            print(f"  BLOCK {b}")
        for w in r["warn"]:
            print(f"  WARN  {w}")
        if not r["block"] and not r["warn"]:
            print("  OK    no weakening of the test suite found")
    if r["block"] and os.environ.get("ALLOW_TEST_CHANGES") != "1":
        print("\nIf these changes are intended, a human approves them by adding the `allow-test-changes` label "
              "to the PR (CI re-runs with ALLOW_TEST_CHANGES=1). Otherwise revert them.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
