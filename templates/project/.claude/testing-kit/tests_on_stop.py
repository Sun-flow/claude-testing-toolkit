#!/usr/bin/env python3
"""Stop hook: don't let Claude finish while the fast test tier fails.

Runs `commands.fast` from .claude/testing-kit.json when the working tree has
changes. On failure it blocks the stop with a grouped summary (via
test_report.py when a JUnit file exists), so Claude keeps working on the cause.
It also runs when Claude committed during the session (a clean tree isn't proof
nothing changed). Loop-safe: if this hook already forced a continuation
(`stop_hook_active`), or Claude's last message is a question to the user, it
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
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in the repo
sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402
import test_report  # noqa: E402


ENV_ERROR = re.compile(r"No module named|ModuleNotFoundError|command not found|is not recognized as|"
                       r"Cannot find module|collected 0 items|no tests ran|No tests found|ERR_MODULE_NOT_FOUND|"
                       r"error: unrecognized arguments")


def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def head_marker(root: Path, hi: dict) -> Path:
    sid = "".join(c for c in str(hi.get("session_id") or "") if c.isalnum() or c in "-_")[:64] or "default"
    return root / ".claude/testing-kit/.state" / f"{sid}.head"


def committed_since_start(root: Path, hi: dict) -> bool:
    """Claude committed during this session (bash_audit records the starting commit), so a clean tree
    doesn't mean nothing changed."""
    try:
        start = head_marker(root, hi).read_text(encoding="utf-8").strip()
    except OSError:
        return False
    head = _git(root, "rev-parse", "HEAD")
    return bool(head) and head != start


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
    if not stop_cfg.get("enabled", True) or not command:
        return
    dirty = tree_changed(root)
    if not dirty and not committed_since_start(root, hi):
        return
    last = hi.get("last_assistant_message") or ""
    last = last if isinstance(last, str) else ""
    if "BLOCKED:" in last:
        return  # Claude is stopping to report a blocker (TG-19); CI still gates the change
    asking = last.rstrip().endswith("?")  # a question to the user (TG-02): let it stop, but tell the user
    junit = root / cfg.get("junit_path", ".reports/junit.xml")
    try:
        junit.unlink()  # only a report written by this run counts
    except OSError:
        pass
    try:
        proc = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True,
                              timeout=int(stop_cfg.get("timeout_s", 300)),
                              env={**os.environ, "CI": os.environ.get("CI", "")})
        rc, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        rc, output = 124, f"timed out after {stop_cfg.get('timeout_s', 300)}s"
    if rc == 0:
        head = _git(root, "rev-parse", "HEAD")
        if head and not dirty:  # this commit is green: don't re-run for it at the next stop
            try:
                head_marker(root, hi).write_text(head, encoding="utf-8")
            except OSError:
                pass
        return
    fresh_junit = junit.is_file()
    if fresh_junit:
        summary = test_report.render(test_report.parse([junit]))
    else:
        summary = "\n".join(output.strip().splitlines()[-60:])
    env_problem = not fresh_junit and ENV_ERROR.search(output)
    if hi.get("stop_hook_active") or asking:
        # Already pushed back once, or Claude is asking the user something: let it stop, and tell the
        # user directly that the tests fail (so ending on a question can't hide a red suite).
        kitlib.emit({"systemMessage": f"Testing kit: fast tests fail (`{command}`, exit {rc}). "
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
