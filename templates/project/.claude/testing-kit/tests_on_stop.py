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
import re
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in the repo
sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402
import test_report  # noqa: E402


ENV_ERROR = re.compile(r"No module named|ModuleNotFoundError|command not found|is not recognized as|"
                       r"Cannot find module|collected 0 items|no tests ran|No tests found|ERR_MODULE_NOT_FOUND|"
                       r"error: unrecognized arguments")


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
    if isinstance(last, str) and ("BLOCKED:" in last or last.rstrip().endswith("?")):
        return  # reporting a blocker (TG-19) or asking the user (TG-02) is a fine place to stop; CI still gates
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
    fresh_junit = junit.is_file() and junit.stat().st_mtime >= started - 1
    if fresh_junit:
        summary = test_report.render(test_report.parse([junit]))
    else:
        summary = "\n".join(output.strip().splitlines()[-60:])
    env_problem = not fresh_junit and ENV_ERROR.search(output)
    if hi.get("stop_hook_active"):
        # Already pushed back once: let Claude stop, and warn the user directly.
        kitlib.emit({"systemMessage": f"Testing kit: fast tests still fail (`{command}`, exit {rc}). "
                                      f"The work is not done.\n{summary[:1500]}"})
    if env_problem:
        kitlib.emit({"decision": "block", "reason":
                     f"The fast test command could not run (`{command}`, exit {rc}): this looks like an "
                     f"environment or configuration problem, not a test failure. Fix the environment (install "
                     f"dependencies, check commands.fast in .claude/testing-kit.json), or stop with a report "
                     f"starting `BLOCKED:` saying what is missing. Don't change tests to work around it.\n{summary}"})
    kitlib.emit({"decision": "block", "reason":
                 f"The fast test tier fails (`{command}`, exit {rc}). Fix the code under test (not the "
                 f"tests). If you are stuck, or a test looks wrong, stop and write a report that starts "
                 f"with `BLOCKED:` giving the failing test, your evidence and what you need from the "
                 f"user (TG-19). If you are showing a new test failing first (red before green, TG-04), say so and "
                 f"go on to the fix.\n{summary}"})


if __name__ == "__main__":
    kitlib.run_hook(main, protective=False)
