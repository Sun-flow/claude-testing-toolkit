#!/usr/bin/env python3
"""Stop hook: don't let Claude finish while the fast test tier fails.

    Stop          tests_on_stop.py            run the fast tier if this session changed something
    SessionStart  tests_on_stop.py baseline   remember what the working tree looked like at the start

Runs `commands.fast` from .claude/testing-kit.json when the working tree (or the
commit checked out) differs from what it was when the session started, and from
what it was at the last run. So a turn in which Claude only read files or
answered a question costs nothing, and changes the user had lying around before
the session don't trigger a run by themselves. If the start of the session
wasn't recorded, it runs whenever there are uncommitted changes.

On failure it blocks the stop with a grouped summary (via test_report.py when a
JUnit file exists), so Claude keeps working on the cause. Loop-safe: if this
hook already forced a continuation (`stop_hook_active`), or Claude's last
message is a question to the user, it lets Claude stop and shows the user a
warning that tests still fail. In later turns, while nothing changes after a
failed run, it repeats that warning instead of running again. Claude can also
stop at any time by giving a report that contains `BLOCKED:` (TG-19), so the
hook never forces it to keep trying until it cheats.
Disable per repo with "stop_hook": {"enabled": false}.
Guidelines: TG-04, TG-13, TG-19, TG-49.
"""
from __future__ import annotations

import json
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


def last_run(root: Path, hi: dict) -> dict:
    try:
        data = json.loads(kitlib.read_state(root, hi, "ran") or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def remember_run(root: Path, hi: dict, rc: int) -> None:
    """The tree as the run left it (a run can write files of its own) and how the run ended."""
    after = kitlib.tree_fingerprint(root)
    try:
        kitlib.ensure_state_dir(root)
        kitlib.state_path(root, hi, "ran").write_text(
            json.dumps({"fingerprint": after[0] if after else None, "rc": rc}), encoding="utf-8")
    except OSError:
        pass


def main(mode: str = "stop") -> None:
    hi = kitlib.read_hook_input()
    root = kitlib.project_dir(hi)
    if mode == "baseline":
        kitlib.record_baseline(root, hi)
        return
    cfg = kitlib.load_config(root)
    stop_cfg = cfg.get("stop_hook", {})
    command = (cfg.get("commands") or {}).get("fast", "").strip()
    if not stop_cfg.get("enabled", True) or not command:
        return
    now = kitlib.tree_fingerprint(root)
    start = kitlib.read_state(root, hi, "base")
    if now is None or start == "unknown":
        changed = True          # git can't say what changed: run, as a careful default
    elif start is None:
        changed = now[1]        # no record of the session's start: run when there are uncommitted changes
    else:
        changed = now[0] != start
    if not changed:
        return
    last = hi.get("last_assistant_message") or ""
    last = last if isinstance(last, str) else ""
    if "BLOCKED:" in last:
        return  # Claude is stopping to report a blocker (TG-19); CI still gates the change
    previous = last_run(root, hi)
    if now is not None and previous.get("fingerprint") == now[0]:
        if previous.get("rc") == 0:
            return  # this exact state already passed
        if not hi.get("stop_hook_active"):
            # It failed in an earlier turn, Claude and the user were told, and nothing has changed since:
            # remind the user, don't run again. (Right after a block it does run again, once: that gives
            # an intermittent failure a second chance.)
            kitlib.emit({"systemMessage": f"Testing kit: fast tests fail (`{command}`, exit "
                                          f"{previous.get('rc')}), and nothing has changed since that run. "
                                          "The work is not done."})
    asking = last.rstrip().endswith("?")  # a question to the user (TG-02): let it stop, but tell the user
    junit_path = cfg.get("junit_path") or ""
    junit = root / junit_path if junit_path else None
    if junit:
        try:
            junit.unlink()  # only a report written by this run counts
        except OSError:
            pass
    try:
        proc = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True, errors="replace",
                              timeout=int(stop_cfg.get("timeout_s", 300)),
                              env={**os.environ, "CI": os.environ.get("CI", "")})
        rc, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        rc, output = 124, (f"timed out after {stop_cfg.get('timeout_s', 300)}s (raise stop_hook.timeout_s in "
                           ".claude/testing-kit.json, or point commands.fast at a quicker subset)")
    remember_run(root, hi, rc)
    if rc == 0:
        return
    fresh_junit = bool(junit) and junit.is_file()
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
                 f"The fast test tier fails (`{command}`, exit {rc}). If your change caused it, fix the code "
                 f"under test (not the tests). If a failure was already there before your change, don't fix "
                 f"unrelated code to get past this: stop with a report that starts with `BLOCKED:` and names "
                 f"the tests that were already failing. If you are stuck, or a test looks wrong, also stop "
                 f"with a `BLOCKED:` report giving the failing test, your evidence and what you need from the "
                 f"user (TG-19). If you are showing a new test failing first (red before green, TG-04), say so "
                 f"and go on to the fix.\n{summary}"})


if __name__ == "__main__":
    kitlib.run_hook(main, *sys.argv[1:2], protective=False)
