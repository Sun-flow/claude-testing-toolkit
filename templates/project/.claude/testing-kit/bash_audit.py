#!/usr/bin/env python3
"""Pre/PostToolUse hook pair (Bash): catch shell changes to protected files.

Parsing commands can't catch every route (`python script.py`, `make`, a
generated script ...). So before each Bash call this hook records a hash of
every test and harness file git knows about (tracked, or untracked and not ignored), and after the call it compares. Any
protected file that the command changed or deleted is reported back to Claude
(exit 2 after the fact), with the fix: restore it with `git checkout -- <file>`
or ask the user.

    PreToolUse  Bash: bash_audit.py pre
    PostToolUse Bash: bash_audit.py post
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in the repo
sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402


def protected_files(root: Path, cfg: dict) -> list[str]:
    try:
        # tracked files plus untracked ones that aren't ignored (a new test not yet committed)
        out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             cwd=root, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    if out.returncode != 0:
        return []
    files = [f for f in out.stdout.decode("utf-8", "replace").split("\0") if f]
    return [f for f in files if kitlib.is_test_path(f, cfg) or kitlib.is_harness_path(f, cfg)
            or kitlib.harness_section_patterns(f, cfg)]


def digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "missing"


def snapshot(root: Path, cfg: dict) -> dict:
    return {f: digest(root / f) for f in protected_files(root, cfg)}


def state_file(root: Path, hi: dict) -> Path:
    """One snapshot per tool call, so Bash calls running in parallel don't overwrite each other's."""
    call = "".join(c for c in str(hi.get("tool_use_id") or "") if c.isalnum() or c in "-_")[:64]
    sid = kitlib.session_key(hi)
    return root / kitlib.STATE_DIR / (f"{sid}-{call}.json" if call else f"{sid}.json")


def main(mode: str) -> None:
    hi = kitlib.read_hook_input()
    root = kitlib.project_dir(hi)
    if mode == "pre":
        # In case SessionStart didn't run: the tree as it is before this session's first shell command.
        kitlib.record_baseline(root, hi)
    if kitlib.allow_marker_present(root):
        return
    cfg = kitlib.load_config(root)
    sf = state_file(root, hi)
    if mode == "pre":
        kitlib.ensure_state_dir(root)
        sf.write_text(json.dumps(snapshot(root, cfg)), encoding="utf-8")
        return
    try:
        before = json.loads(sf.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        kitlib.block("Testing kit: the audit snapshot taken before that shell command is missing or damaged "
                     f"({sf.relative_to(root) if sf.is_relative_to(root) else sf}), so changes to protected tests "
                     "can't be checked. Don't touch .claude/testing-kit/. Tell the user and run `git status` "
                     "to show what changed.")
    if hi.get("tool_use_id"):
        sf.unlink(missing_ok=True)  # per-call snapshot: done with it
    after = {f: digest(root / f) for f in before}
    changed = sorted(f for f in before if before[f] != after[f])
    if changed:
        listed = ", ".join(changed[:10]) + (f" (+{len(changed) - 10} more)" if len(changed) > 10 else "")
        kitlib.block(f"Testing kit: that shell command changed protected test/harness file(s): {listed}. "
                     "Existing tests and harness are the specification (TG-14/TG-15). Unless the user asked for "
                     "this change, undo it (for a committed file, `git checkout -- <file>`; the user will "
                     "be asked to approve that) and tell the user what happened.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "post"
    kitlib.run_hook(main, mode, protective=(mode == "pre"))
