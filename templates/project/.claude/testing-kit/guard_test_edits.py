#!/usr/bin/env python3
"""PostToolUse hook (Edit|Write): review test code that was just written.

Flags, as feedback to Claude (exit 2 after the edit, so Claude must respond):
  * hard waits (time.sleep, waitForTimeout, Thread.sleep ...)          TG-28
  * retry/flaky decorators and retry settings                          TG-18
  * skip/xfail/only markers in new tests                               TG-14
  * broad `except: pass` that makes a test pass vacuously              TG-21
  * Python tests with no assertion at all                              TG-07
  * production code that checks whether it runs under a test           TG-16
Lines carrying the comment `kit: allow <reason>` are exempt.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402
from protect_tests import added_text  # noqa: E402

TEST_ENV_RE = re.compile(
    r"PYTEST_CURRENT_TEST|['\"]pytest['\"]\s+in\s+sys\.modules|NODE_ENV\s*[!=]==?\s*['\"]test['\"]|"
    r"JEST_WORKER_ID|process\.env\.VITEST\b|import\.meta\.env\.(?:VITEST|MODE\s*===?\s*['\"]test)|"
    r"['\"]test['\"]\s+in\s+sys\.argv|testing\.Testing\(\)")
ASSERT_HINTS = ("assert", "raises", "expect", "check", "verify", "should", "fail")


def _exempt(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if "kit: allow" not in l)


def assertion_free_tests(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    bad = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test"):
            has = False
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assert):
                    has = True
                    break
                if isinstance(sub, ast.Call):
                    name = ast.unparse(sub.func).lower()
                    if any(h in name for h in ASSERT_HINTS):
                        has = True
                        break
                if isinstance(sub, ast.Raise):
                    has = True
                    break
            if not has:
                bad.append(node.name)
    return bad


def main() -> None:
    hi = kitlib.read_hook_input()
    tool = hi.get("tool_name", "")
    ti = hi.get("tool_input") or {}
    target = ti.get("file_path")
    if not target:
        return
    root = kitlib.project_dir(hi)
    rel = kitlib.rel_posix(target, root)
    cfg = kitlib.load_config(root)
    if rel.startswith("../"):
        return
    if tool == "Edit":
        added = added_text(ti.get("old_string", ""), ti.get("new_string", ""))
    elif tool == "Write":
        added = ti.get("content", "")
    else:
        return
    added = _exempt(added)
    if not kitlib.is_test_path(rel, cfg):
        if TEST_ENV_RE.search(added):
            kitlib.block(f"Testing kit review of {rel}: production code now checks whether it is running "
                         "under a test (e.g. PYTEST_CURRENT_TEST, NODE_ENV==='test', JEST_WORKER_ID). Code "
                         "must behave the same under test; implement the general logic instead (TG-16).")
        return
    notes = []
    if kitlib.SLEEP_RE.search(added):
        notes.append("a hard wait (sleep/waitForTimeout). Wait on a condition, poll, or inject the clock instead (TG-28)")
    if kitlib.RETRY_RE.search(added):
        notes.append("a retry/flaky marker. Fix the cause of the flakiness or report it; retries hide real failures (TG-18)")
    if kitlib.SKIP_RE.search(added):
        notes.append("a skip/xfail/only marker. Skipping is a decision for the user, with a reason (TG-14)")
    if kitlib.BROAD_EXCEPT_RE.search(added):
        notes.append("a broad except that swallows errors, so the test can pass vacuously (TG-21)")
    if rel.endswith(".py"):
        full = (root / rel)
        try:
            source = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            source = ""
        names = [n for n in assertion_free_tests(source) if n in added]
        if names:
            notes.append("test(s) with no assertion: " + ", ".join(names) +
                         ". Every test needs an assertion that fails if the behaviour breaks (TG-07)")
    if notes:
        kitlib.block(f"Testing kit review of {rel}: the change adds " + "; ".join(notes) +
                     ". Fix it, or if it is truly needed add `kit: allow <reason>` on that line and "
                     "mention it to the user.")


if __name__ == "__main__":
    main()
