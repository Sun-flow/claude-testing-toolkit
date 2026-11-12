#!/usr/bin/env python3
"""ConfigChange hook: stop a session from changing project or local Claude settings
mid-session (e.g. writing {"disableAllHooks": true} to .claude/settings.local.json,
which would switch off the testing kit's hooks). When blocked, Claude Code does not
apply the new settings to the running session. The user can still change settings
outside the session, or create .claude/allow-test-edits first.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in the repo
sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402


def main() -> None:
    hi = kitlib.read_hook_input()
    source = str(hi.get("source") or hi.get("config_source") or "")
    root = kitlib.project_dir(hi)
    if source in {"project_settings", "local_settings"} and not kitlib.allow_marker_present(root):
        kitlib.block("Testing kit: project/local Claude settings can't be changed during a session, because "
                     "that could switch off the test protections. Ask the user to change settings themselves.")


if __name__ == "__main__":
    kitlib.run_hook(main, protective=False)
