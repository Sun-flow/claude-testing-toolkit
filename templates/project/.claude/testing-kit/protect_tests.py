#!/usr/bin/env python3
"""PreToolUse hook (Edit|Write|NotebookEdit): protect existing tests and test harness.

Allowed:
  * creating a new test file (not a harness file such as conftest.py)
  * adding to an existing test file, when every existing line is kept in order,
    no skip/xfail/only markers or no-cover pragmas are added, and no existing
    test name is defined a second time (which would shadow the original)
Blocked (exit 2, reason shown to Claude):
  * changing or removing existing lines of a test file
  * hand-editing snapshot/golden files
  * creating or changing harness files (conftest.py, runner/coverage config, CI
    workflows, the kit itself) or the test/coverage sections of shared manifests
By default a protected change is not refused outright: Claude Code asks the
user in its permission prompt, with the reason (config "enforcement": "ask").
With "enforcement": "deny" it is refused; the user then edits the file
themselves or creates `.claude/allow-test-edits` (ignored after 2 hours).
Additions to conftest.py are allowed when they add no autouse fixture and no
pytest_* hook.
Guidelines: TG-14, TG-15, TG-17 in docs/testing/GUIDELINES.md.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

SNAPSHOT_GLOBS = ["**/__snapshots__/**", "**/*.snap", "**/*.snap.new", "**/snapshots/**",
                  "**/*.approved.*", "**/*.golden", "**/golden/**", "**/testdata/**"]

HOW_TO_PROCEED = (
    "Approve only if the user asked for this change or agrees the test/harness is wrong. "
    "Claude: if you believe the test is wrong, stop and tell the user the file, what it expects, "
    "what the code does, your evidence and the change you propose; otherwise fix the code under "
    "test or add a NEW test instead."
)
MARKER_GLOBS = [".claude/allow-test-edits"]
CONFTEST_RISKY = re.compile(r"autouse\s*=\s*True|^\s*def\s+pytest_\w+", re.M)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def proposed_content(tool: str, ti: dict, current: str | None) -> str | None:
    if tool == "Write":
        return ti.get("content", "")
    if tool == "Edit":
        if current is None:
            return None
        old, new = ti.get("old_string", ""), ti.get("new_string", "")
        if not old or old not in current:
            return None  # the Edit tool itself will fail; nothing to judge
        return current.replace(old, new) if ti.get("replace_all") else current.replace(old, new, 1)
    return None  # NotebookEdit and unknown tools: judged as a modification


def is_pure_addition(old: str, new: str) -> bool:
    """Every non-blank old line still appears, in order, in the new text."""
    new_lines = iter(new.splitlines())
    for line in (l for l in old.splitlines() if l.strip()):
        for candidate in new_lines:
            if candidate == line:
                break
        else:
            return False
    return True


def added_text(old: str, new: str) -> str:
    old_counts: dict[str, int] = {}
    for line in old.splitlines():
        old_counts[line] = old_counts.get(line, 0) + 1
    out = []
    for line in new.splitlines():
        if old_counts.get(line, 0) > 0:
            old_counts[line] -= 1
        else:
            out.append(line)
    return "\n".join(out)


def addition_problems(old: str, new: str) -> list[str]:
    problems = []
    if not is_pure_addition(old, new):
        problems.append("it changes or removes existing lines")
    added = added_text(old, new)
    if kitlib.SKIP_RE.search(added):
        problems.append("it adds a skip/xfail/only/todo marker")
    if kitlib.NO_COVER_RE.search(added):
        problems.append("it adds a coverage-exclusion pragma")
    old_names = kitlib.test_names(old)
    new_names = kitlib.test_names(new)
    shadowed = sorted({n for n in old_names if new_names.count(n) > old_names.count(n)})
    if shadowed:
        problems.append("it defines existing test name(s) again, which would shadow them: " + ", ".join(shadowed))
    return problems


def _ini_sections(text: str, patterns: list[str]) -> str:
    out, keep = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("["):
            keep = any(re.match(p, line.strip()) for p in patterns)
        if keep:
            out.append(line.rstrip())
    return "\n".join(out)


def _json_sections(text: str, patterns: list[str]) -> str:
    try:
        data = json.loads(text)
    except ValueError:
        return text  # unparsable: compare whole file conservatively
    keys = [re.sub(r'[^A-Za-z0-9_-]', "", p.split(":")[0]) for p in patterns]
    return json.dumps({k: data.get(k) for k in keys if isinstance(data, dict)}, sort_keys=True)


def section_changed(rel: str, old: str, new: str, patterns: list[str]) -> bool:
    if rel.endswith(".json"):
        return _json_sections(old, patterns) != _json_sections(new, patterns)
    return _ini_sections(old, patterns) != _ini_sections(new, patterns)


def main() -> None:
    hi = kitlib.read_hook_input()
    tool = hi.get("tool_name", "")
    ti = hi.get("tool_input") or {}
    target = ti.get("file_path") or ti.get("notebook_path")
    if not target:
        return
    root = kitlib.project_dir(hi)
    if kitlib.allow_marker_present(root):
        return
    rel = kitlib.rel_posix(target, root)
    if rel.startswith("../"):
        return
    cfg = kitlib.load_config(root)
    path = root / rel
    exists = path.exists()

    if kitlib.matches_any(rel, MARKER_GLOBS):
        kitlib.block("Blocked: only the user may create the test-edit allow marker.")

    if kitlib.is_harness_path(rel, cfg):
        if rel.endswith("conftest.py") and exists:
            current = _read(path)
            new = proposed_content(tool, ti, current)
            if current is not None and new is not None and is_pure_addition(current, new) \
                    and not CONFTEST_RISKY.search(added_text(current, new)):
                return
        kitlib.guard(f"{rel} is test-harness configuration (runner, fixtures, coverage, CI or the testing "
                     f"kit); changing it can make failing tests pass (TG-15). {HOW_TO_PROCEED}", cfg)
        return

    patterns = kitlib.harness_section_patterns(rel, cfg)
    if patterns and exists:
        current = _read(path)
        new = proposed_content(tool, ti, current)
        if current is not None and (new is None and tool == "NotebookEdit" or
                                    new is not None and section_changed(rel, current, new, patterns)):
            kitlib.guard(f"this edit changes the test/coverage configuration section of {rel} (TG-15). "
                         f"{HOW_TO_PROCEED}", cfg)
        return

    if not kitlib.is_test_path(rel, cfg):
        return  # production code
    head = None if exists else kitlib.head_content(root, rel)
    if not exists and head is None:
        return  # a brand-new test file

    if kitlib.matches_any(rel, SNAPSHOT_GLOBS):
        kitlib.guard(f"{rel} is a snapshot/golden file; hand-editing or regenerating it to make a test "
                     f"pass rewrites the expected output (TG-17). {HOW_TO_PROCEED}", cfg)
        return

    current = _read(path) if exists else head
    new = proposed_content(tool, ti, current)
    if current is None or new is None:
        if tool == "Edit" and current is not None:
            return  # old_string not found: the tool call will fail on its own
        kitlib.guard(f"{rel} is an existing test file and this change can't be checked as a pure "
                     f"addition (TG-14). {HOW_TO_PROCEED}", cfg)
        return
    problems = addition_problems(current, new)
    if problems:
        kitlib.guard(f"{rel} is an existing test file and this edit is not a pure addition of new tests: "
                     f"{'; '.join(problems)}. Existing tests are the specification (TG-14). "
                     f"{HOW_TO_PROCEED}", cfg)


if __name__ == "__main__":
    main()
