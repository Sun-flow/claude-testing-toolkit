#!/usr/bin/env python3
"""PreToolUse hook for the spec-test-writer agent only (wired in its frontmatter).

Keeps the agent away from the implementation so its tests come from the spec,
not from the code (the "AI echo chamber", guidelines TG-05, risk tiers):
  * Read/Edit/Write/NotebookEdit under a source directory -> denied
  * Grep/Glob under a source directory, or with no path (which would search the
    whole project, source included) -> denied
  * Bash: only the configured test commands, plus read-only git/ls on non-source
    paths; anything mentioning a source directory -> denied
Known leaks no hook can close: what the parent agent writes in its delegation
prompt, stack traces in test output, and interface stubs the tests must import.
"""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

SAFE_BASH = re.compile(r"^(?:ls|pwd|git\s+(?:status|log|diff\s+--stat|ls-files))\b")


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

    if tool in {"Read", "Edit", "Write", "NotebookEdit"}:
        target = ti.get("file_path") or ti.get("notebook_path") or ""
        if target and under_src(target, root, src):
            kitlib.block(reason + f"{target} is implementation code.")
    elif tool in {"Grep", "Glob"}:
        path = ti.get("path") or ""
        if not path:
            kitlib.block(reason + "Give Grep/Glob an explicit path outside the source directories "
                         f"({', '.join(src)}), e.g. tests/ or docs/.")
        if under_src(path, root, src):
            kitlib.block(reason + f"{path} is implementation code.")
    elif tool == "Bash":
        command = ti.get("command", "")
        allowed = [c for c in (cfg.get("commands") or {}).values() if c]
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = command.split()
        if any(under_src(t, root, src) for t in tokens if not t.startswith("-")):
            kitlib.block(reason + "That command touches implementation code.")
        if not (SAFE_BASH.match(command.strip()) or any(command.strip().startswith(c.split(" -")[0]) for c in allowed)):
            kitlib.block(reason + "Only the project's test commands and read-only git/ls are allowed here: "
                         + "; ".join(allowed or ["(none configured in .claude/testing-kit.json)"]))


if __name__ == "__main__":
    main()
