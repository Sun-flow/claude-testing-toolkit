#!/usr/bin/env python3
"""PreToolUse hook for the spec-test-writer agent only (wired in its frontmatter).

Keeps the agent away from the implementation so its tests come from the spec,
not from the code (the "AI echo chamber", guidelines TG-05, risk tiers). It is
an ALLOWLIST, so it works for flat repos too (bot.py at the root):
  * Read/Grep/Glob only inside `spec_readable` (docs, specs, README, existing
    tests, type stubs); Grep/Glob need an explicit path
  * Edit/Write only on test paths
  * Bash: only the configured test commands, plus ls/pwd/git status|log
Reduces, doesn't eliminate, leakage.
Known leaks no hook can close: what the parent agent writes in its delegation
prompt, stack traces in test output, and interface stubs the tests must import.
"""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in the repo
sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

SAFE_BASH = re.compile(r"^(?:ls|pwd|git\s+(?:status|log|diff\s+--stat|ls-files))\b")


DEFAULT_READABLE = ["docs/**", "doc/**", "specs/**", "spec/**", "README*", "*.md", "**/*.pyi", "**/*.d.ts",
                    "openapi.*", "**/openapi.*", "**/schema*.json", ".claude/testing-kit.json"]


def readable(value: str, root: Path, cfg: dict) -> bool:
    rel = kitlib.rel_posix(value, root).rstrip("/")
    if rel in ("", "."):
        return False
    globs = cfg.get("spec_readable") or DEFAULT_READABLE
    return kitlib.matches_any(rel, globs) or kitlib.is_test_path(rel, cfg) or \
        kitlib.matches_any(rel + "/x", globs) or kitlib.is_test_path(rel + "/x", cfg)


def under_src(value: str, root: Path, src_dirs: list[str]) -> bool:
    rel = kitlib.rel_posix(value, root)
    return any(rel == d or rel.startswith(d.rstrip("/") + "/") or f"/{d}/" in f"/{rel}/" for d in src_dirs)


def main() -> None:
    hi = kitlib.read_hook_input()
    tool = hi.get("tool_name", "")
    ti = hi.get("tool_input") or {}
    root = kitlib.project_dir(hi)
    cfg = kitlib.load_config(root)
    src = cfg.get("src_dirs", [])
    reason = ("You are the spec-only test writer: derive expected behaviour from the ticket, spec, docs and "
              "public interface, never from the implementation. ")

    if tool == "Read":
        target = ti.get("file_path") or ""
        if target and not readable(target, root, cfg):
            kitlib.block(reason + f"{target} is not spec material (allowed: docs, specs, README, tests, "
                         "type stubs, schemas; set spec_readable in .claude/testing-kit.json).")
    elif tool in {"Edit", "Write", "NotebookEdit"}:
        target = ti.get("file_path") or ti.get("notebook_path") or ""
        if target and not kitlib.is_test_path(kitlib.rel_posix(target, root), cfg):
            kitlib.block(reason + f"You may only write test files; {target} is not one.")
    elif tool in {"Grep", "Glob"}:
        path = ti.get("path") or ""
        if not path or not readable(path, root, cfg):
            kitlib.block(reason + "Give Grep/Glob an explicit path inside docs/, specs/ or the tests.")
    elif tool in {"Bash", "PowerShell"}:
        command = ti.get("command", "")
        allowed = [c for c in (cfg.get("commands") or {}).values() if c]
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()
        if any(under_src(t, root, src) for t in tokens if not t.startswith("-")):
            kitlib.block(reason + "That command touches implementation code.")
        if re.search(r"[;&|`$<>]", command.replace("2>&1", "")) and not any(command.strip().startswith(c) for c in allowed):
            kitlib.block(reason + "Run one test command at a time, without pipes or redirects.")
        cmd = command.strip()
        if not (SAFE_BASH.match(cmd) or any(cmd == c or cmd.startswith(c + " ") for c in allowed)):
            kitlib.block(reason + "Only the project's test commands and read-only git/ls are allowed here: "
                         + "; ".join(allowed or ["(none configured in .claude/testing-kit.json)"]))


if __name__ == "__main__":
    kitlib.run_hook(main, protective=True)
