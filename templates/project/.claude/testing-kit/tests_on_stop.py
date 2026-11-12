#!/usr/bin/env python3
"""Stop hook: don't let Claude finish while the fast test tier fails.

Runs `commands.fast` from .claude/testing-kit.json when the working tree has
changes. On failure it blocks the stop with a grouped summary (via
test_report.py when a JUnit file exists), so Claude keeps working on the cause.
Loop-safe: if this hook already forced a continuation (`stop_hook_active`), it
lets Claude stop and shows the user a warning that tests still fail. Claude can
also stop at any time by giving a report that contains `BLOCKED:` (TG-19), so
the hook never forces it to keep trying until it cheats.
Disable per repo with "stop_hook": {"enabled": false}.
Guidelines: TG-04, TG-13, TG-19, TG-49.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402
import test_report  # noqa: E402


def tree_changed(root: Path) -> bool:
    try:
        out = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True,
                             text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return True  # not a git repo or git missing: be conservative and run
    if out.returncode != 0:
        return True
    return bool(out.stdout.strip())


def main() -> None:
    hi = kitlib.read_hook_input()
    root = kitlib.project_dir(hi)
    cfg = kitlib.load_config(root)
    stop_cfg = cfg.get("stop_hook", {})
    command = (cfg.get("commands") or {}).get("fast", "").strip()
    if not stop_cfg.get("enabled", True) or not command or not tree_changed(root):
        return
    last = hi.get("last_assistant_message") or ""
    if isinstance(last, str) and "BLOCKED:" in last:
        return  # Claude is stopping to report a blocker (TG-19); CI still gates the change
    junit = root / cfg.get("junit_path", ".reports/junit.xml")
    started = time.time()
    try:
        proc = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True,
                              timeout=int(stop_cfg.get("timeout_s", 300)),
                              env={**os.environ, "CI": os.environ.get("CI", "")})
        rc, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        rc, output = 124, f"timed out after {stop_cfg.get('timeout_s', 300)}s"
    if rc == 0:
        return
    if junit.is_file() and junit.stat().st_mtime >= started - 1:
        summary = test_report.render(test_report.parse([junit]))
    else:
        summary = "\n".join(output.strip().splitlines()[-60:])
    if hi.get("stop_hook_active"):
        # Already pushed back once: let Claude stop, and warn the user directly.
        kitlib.emit({"systemMessage": f"Testing kit: fast tests still fail (`{command}`, exit {rc}). "
                                      f"The work is not done.\n{summary[:1500]}"})
    kitlib.emit({"decision": "block", "reason":
                 f"The fast test tier fails (`{command}`, exit {rc}). Fix the code under test (not the "
                 f"tests). If you are stuck, or a test looks wrong, stop and write a report that starts "
                 f"with `BLOCKED:` giving the failing test, your evidence and what you need from the "
                 f"user (TG-19).\n{summary}"})


if __name__ == "__main__":
    main()
