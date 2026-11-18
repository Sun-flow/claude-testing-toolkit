"""Hooks keep working when Claude starts in a folder above the project.

Some hosted sessions clone the repository into a subfolder and start Claude one level up, so
CLAUDE_PROJECT_DIR names the parent folder and the shell's directory can differ from the project's.
"""
import json
import os
import subprocess
import sys

from conftest import decision, run_hook


def run_from_parent(repo, script, payload):
    """Run a hook the way such a session does: CLAUDE_PROJECT_DIR is the folder that holds the repo."""
    payload = {"cwd": str(repo.parent), "session_id": "test", **payload}
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo.parent)}
    proc = subprocess.run([sys.executable, str(repo / ".claude/testing-kit" / script)],
                          input=json.dumps(payload), capture_output=True, text=True, env=env)
    out = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, out, proc.stderr


class TestProjectFoundFromTheKitsOwnLocation:
    def test_changing_the_kit_config_asks_when_claude_starts_above_the_project(self, repo):
        result = run_from_parent(repo, "protect_tests.py", {"tool_name": "Edit", "tool_input": {
            "file_path": str(repo / ".claude" / "testing-kit.json"),
            "old_string": '"enforcement"', "new_string": '"enforcement_off"'}})
        assert decision(result) == "ask"

    def test_rewriting_an_existing_assertion_asks_when_claude_starts_above_the_project(self, repo):
        result = run_from_parent(repo, "protect_tests.py", {"tool_name": "Edit", "tool_input": {
            "file_path": str(repo / "tests" / "test_calc.py"),
            "old_string": "assert add(2, 3) == 5", "new_string": "assert add(2, 3) == 6"}})
        assert decision(result) == "ask"


class TestShellPathsResolvedFromTheShellsDirectory:
    def bash(self, repo, command, cwd):
        return run_hook(repo, "guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": command},
                                                "cwd": str(cwd)})

    def test_a_relative_path_up_from_a_subfolder_into_the_tests_asks(self, repo):
        assert decision(self.bash(repo, "rm ../tests/test_calc.py", repo / "src")) == "ask"

    def test_a_relative_path_from_a_folder_outside_the_project_is_not_the_projects_test(self, repo, tmp_path):
        # from another folder, tests/test_calc.py names that folder's file, not the project's
        elsewhere = tmp_path / "elsewhere"
        (elsewhere / "tests").mkdir(parents=True)
        assert decision(self.bash(repo, "rm tests/test_calc.py", elsewhere)) == "allow"
