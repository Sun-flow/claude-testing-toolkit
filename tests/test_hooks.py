import json
import os
import time
from pathlib import Path

import pytest

from conftest import decision, git, run_hook

TEST_FILE = "tests/test_calc.py"


def edit(repo, path, old, new):
    return run_hook(repo, "protect_tests.py", {"tool_name": "Edit", "tool_input": {
        "file_path": str(repo / path), "old_string": old, "new_string": new}})


def write(repo, path, content):
    return run_hook(repo, "protect_tests.py", {"tool_name": "Write", "tool_input": {
        "file_path": str(repo / path), "content": content}})


def bash(repo, command):
    return run_hook(repo, "guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": command}})


# ------------------------------------------------------------ protect_tests

class TestProtectTests:
    def test_production_code_edits_are_allowed(self, repo):
        assert decision(edit(repo, "src/calc/__init__.py", "return a + b", "return b + a")) == "allow"

    def test_new_test_file_is_allowed(self, repo):
        assert decision(write(repo, "tests/test_new.py", "def test_x():\n    assert 1 + 1 == 2\n")) == "allow"

    def test_changing_an_assertion_asks_the_user(self, repo):
        assert decision(edit(repo, TEST_FILE, "assert add(2, 3) == 5", "assert add(2, 3) == 6")) == "ask"

    def test_deleting_a_test_asks(self, repo):
        old = "def test_add():\n    assert add(2, 3) == 5\n"
        assert decision(edit(repo, TEST_FILE, old, "")) == "ask"

    def test_appending_a_new_test_is_allowed(self, repo):
        old = "        div(1, 0)\n"
        new = old + "\n\ndef test_add_negative():\n    assert add(-2, -3) == -5\n"
        assert decision(edit(repo, TEST_FILE, old, new)) == "allow"

    def test_adding_a_skip_marker_asks_even_though_it_only_adds_lines(self, repo):
        assert decision(edit(repo, TEST_FILE, "def test_add():", "@pytest.mark.skip\ndef test_add():")) == "ask"

    def test_redefining_an_existing_test_name_asks(self, repo):
        old = "        div(1, 0)\n"
        new = old + "\n\ndef test_add():\n    assert True\n"
        assert decision(edit(repo, TEST_FILE, old, new)) == "ask"

    def test_whole_file_rewrite_that_keeps_everything_is_allowed(self, repo):
        current = (repo / TEST_FILE).read_text()
        assert decision(write(repo, TEST_FILE, current + "\n\ndef test_more():\n    assert add(0, 0) == 0\n")) == "allow"

    def test_deleted_then_recreated_test_file_stays_protected(self, repo):
        (repo / TEST_FILE).unlink()
        assert decision(write(repo, TEST_FILE, "def test_add():\n    assert True\n")) == "ask"

    def test_new_conftest_asks(self, repo):
        assert decision(write(repo, "tests/conftest.py", "import pytest\n")) == "ask"

    def test_harmless_addition_to_existing_conftest_is_allowed(self, repo):
        (repo / "tests/conftest.py").write_text("import pytest\n")
        git(repo, "add", "-A"); git(repo, "commit", "-qm", "conftest")
        new = "import pytest\n\n\n@pytest.fixture\ndef numbers():\n    return [1, 2]\n"
        assert decision(edit(repo, "tests/conftest.py", "import pytest\n", new)) == "allow"

    def test_autouse_fixture_in_conftest_asks(self, repo):
        (repo / "tests/conftest.py").write_text("import pytest\n")
        new = "import pytest\n\n\n@pytest.fixture(autouse=True)\ndef patch(monkeypatch):\n    pass\n"
        assert decision(edit(repo, "tests/conftest.py", "import pytest\n", new)) == "ask"

    def test_pytest_section_of_pyproject_asks(self, repo):
        assert decision(edit(repo, "pyproject.toml", 'addopts = "-q"', 'addopts = "-q --deselect tests"')) == "ask"

    def test_dependency_section_of_pyproject_is_allowed(self, repo):
        assert decision(edit(repo, "pyproject.toml", "dependencies = []", 'dependencies = ["attrs"]')) == "allow"

    def test_snapshot_files_ask(self, repo):
        snap = repo / "tests/__snapshots__/test_calc.ambr"
        snap.parent.mkdir()
        snap.write_text("# snapshot\n")
        assert decision(edit(repo, "tests/__snapshots__/test_calc.ambr", "# snapshot", "# changed")) == "ask"

    def test_kit_files_and_settings_ask(self, repo):
        assert decision(write(repo, ".claude/settings.local.json", '{"permissions": {}}')) == "ask"
        assert decision(write(repo, ".claude/settings.local.json", '{"disableAllHooks": true}')) == "block"
        assert decision(edit(repo, ".claude/testing-kit.json", '"enforcement": "ask"', '"enforcement": "off"')) == "ask"

    def test_agent_cannot_create_the_allow_marker(self, repo):
        assert decision(write(repo, ".claude/allow-test-edits", "")) == "block"

    def test_fresh_allow_marker_lets_edits_through_and_stale_one_does_not(self, repo):
        marker = repo / ".claude/allow-test-edits"
        marker.write_text("")
        assert decision(edit(repo, TEST_FILE, "== 5", "== 6")) == "allow"
        old = time.time() - 3 * 3600
        os.utime(marker, (old, old))
        assert decision(edit(repo, TEST_FILE, "== 5", "== 6")) == "ask"

    def test_deny_enforcement_blocks_instead_of_asking(self, repo):
        cfg_path = repo / ".claude/testing-kit.json"
        cfg = json.loads(cfg_path.read_text())
        cfg["enforcement"] = "deny"
        cfg_path.write_text(json.dumps(cfg))
        code, _, err = edit(repo, TEST_FILE, "== 5", "== 6")
        assert code == 2 and "TG-14" in err


# ------------------------------------------------------------ guard_bash

class TestGuardBash:
    @pytest.mark.parametrize("command", [
        "pytest tests/", "cat tests/test_calc.py", "grep -n add tests/test_calc.py",
        "ls > /tmp/out.txt", "python -m pytest -q 2>&1 | tee /tmp/log.txt", "git diff -- tests/",
        "echo hi >&2", "rm -rf build/", "sed -i s/a/b/ src/calc/__init__.py",
    ])
    def test_ordinary_commands_are_allowed(self, repo, command):
        assert decision(bash(repo, command)) == "allow"

    @pytest.mark.parametrize("command", [
        "rm tests/test_calc.py", "rm -rf tests", "mv tests/test_calc.py tests/old.txt",
        "sed -i 's/== 5/== 6/' tests/test_calc.py", "echo 'def test_x(): pass' > tests/test_calc.py",
        "python -c \"open('tests/test_calc.py','w').write('')\"", "git checkout HEAD~1 -- tests/test_calc.py",
        "Remove-Item tests/test_calc.py", "cp /tmp/x.py tests/test_calc.py", "echo x >> pyproject.toml",
    ])
    def test_shell_writes_to_tests_or_harness_ask(self, repo, command):
        assert decision(bash(repo, command)) == "ask"

    @pytest.mark.parametrize("command", [
        "npx jest -u", "npx vitest run --update", "pytest --snapshot-update", "cargo insta accept",
        "UPDATE_GOLDEN=1 go test ./...", "pytest --reruns 3",
    ])
    def test_snapshot_updates_and_retries_ask(self, repo, command):
        assert decision(bash(repo, command)) == "ask"

    @pytest.mark.parametrize("command", [
        "touch .claude/allow-test-edits", "claude --settings '{\"disableAllHooks\":true}' -p hi",
        "echo '{\"disableAllHooks\": true}' > .claude/settings.local.json",
    ])
    def test_bypasses_of_the_kit_are_blocked(self, repo, command):
        assert decision(bash(repo, command)) == "block"


# ------------------------------------------------------------ bash_audit

def test_bash_audit_reports_a_test_changed_by_any_shell_route(repo):
    payload = {"tool_name": "Bash", "tool_input": {"command": "python scripts/rewrite.py"}}
    assert run_hook(repo, "bash_audit.py", payload, "pre")[0] == 0
    (repo / TEST_FILE).write_text("def test_add():\n    assert True\n")
    code, _, err = run_hook(repo, "bash_audit.py", payload, "post")
    assert code == 2 and TEST_FILE in err


def test_bash_audit_is_quiet_when_nothing_protected_changed(repo):
    payload = {"tool_name": "Bash", "tool_input": {"command": "echo hi"}}
    run_hook(repo, "bash_audit.py", payload, "pre")
    (repo / "notes.txt").write_text("x")
    assert run_hook(repo, "bash_audit.py", payload, "post")[0] == 0


# ------------------------------------------------------------ guard_test_edits

def post_edit(repo, path, content):
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text(content)
    return run_hook(repo, "guard_test_edits.py", {"tool_name": "Write", "tool_input": {
        "file_path": str(repo / path), "content": content}})


@pytest.mark.parametrize("content, expected", [
    ("import time\n\ndef test_wait():\n    time.sleep(2)\n    assert True\n", "hard wait"),
    ("import pytest\n\n@pytest.mark.flaky(reruns=3)\ndef test_f():\n    assert 1\n", "retry"),
    ("def test_nothing():\n    x = 1 + 1\n", "no assertion"),
    ("def test_swallow():\n    try:\n        assert 1 == 2\n    except Exception:\n        pass\n", "broad except"),
])
def test_review_flags_weak_test_code(repo, content, expected):
    code, _, err = post_edit(repo, "tests/test_new.py", content)
    assert code == 2 and expected in err


def test_review_accepts_a_good_test(repo):
    assert post_edit(repo, "tests/test_ok.py", "from calc import add\n\ndef test_add_zero():\n    assert add(0, 7) == 7\n")[0] == 0


def test_kit_allow_comment_exempts_a_line(repo):
    content = "import time\n\ndef test_wait():\n    time.sleep(0.1)  # kit: allow rate limit of the fake server\n    assert True\n"
    assert post_edit(repo, "tests/test_wait.py", content)[0] == 0


def test_production_code_checking_for_tests_is_flagged(repo):
    code, _, err = post_edit(repo, "src/calc/env.py", "import os\nIS_TEST = 'PYTEST_CURRENT_TEST' in os.environ\n")
    assert code == 2 and "TG-16" in err


# ------------------------------------------------------------ tests_on_stop

def stop(repo, **extra):
    return run_hook(repo, "tests_on_stop.py", {"hook_event_name": "Stop", **extra})


def test_stop_is_allowed_when_tree_is_clean(repo):
    assert decision(stop(repo)) == "allow"


def test_stop_is_allowed_when_fast_tier_passes(repo):
    (repo / "notes.txt").write_text("changed")
    assert decision(stop(repo)) == "allow"


def test_stop_is_blocked_with_a_grouped_summary_when_tests_fail(repo):
    (repo / "src/calc/__init__.py").write_text("def add(a, b):\n    return a - b\n\n\ndef div(a, b):\n    return a / b\n")
    code, out, _ = stop(repo)
    assert out["decision"] == "block"
    assert "FAILED" in out["reason"] and "BLOCKED:" in out["reason"]


def test_stop_is_allowed_after_a_blocked_report(repo):
    (repo / "src/calc/__init__.py").write_text("def add(a, b):\n    return a - b\n")
    assert decision(stop(repo, last_assistant_message="BLOCKED: test_add expects 5, spec unclear")) == "allow"


def test_second_stop_warns_the_user_instead_of_looping(repo):
    (repo / "src/calc/__init__.py").write_text("def add(a, b):\n    return a - b\n")
    code, out, _ = stop(repo, stop_hook_active=True)
    assert code == 0 and "fast tests fail" in out["systemMessage"]


# ------------------------------------------------------------ no_src_access

def writer(repo, tool, tool_input):
    return run_hook(repo, "no_src_access.py", {"tool_name": tool, "tool_input": tool_input, "agent_type": "spec-test-writer"})


def test_spec_writer_cannot_read_source(repo):
    assert decision(writer(repo, "Read", {"file_path": str(repo / "src/calc/__init__.py")})) == "block"
    assert decision(writer(repo, "Grep", {"pattern": "def add"})) == "block"
    assert decision(writer(repo, "Bash", {"command": "cat src/calc/__init__.py"})) == "block"
    assert decision(writer(repo, "Bash", {"command": "grep -r add ."})) == "block"


def test_spec_writer_can_read_tests_and_docs_and_run_tests(repo):
    assert decision(writer(repo, "Read", {"file_path": str(repo / TEST_FILE)})) == "allow"
    assert decision(writer(repo, "Grep", {"pattern": "add", "path": "tests"})) == "allow"
    fast = json.loads((repo / ".claude/testing-kit.json").read_text())["commands"]["fast"]
    assert decision(writer(repo, "Bash", {"command": fast})) == "allow"


def test_spec_writer_allowlist_works_for_flat_repos_and_blocks_code_execution(repo):
    (repo / "bot.py").write_text("print('hi')\n")
    (repo / "README.md").write_text("# calc\nadd(a, b) returns the sum.\n")
    assert decision(writer(repo, "Read", {"file_path": str(repo / "bot.py")})) == "block"
    assert decision(writer(repo, "Read", {"file_path": str(repo / "README.md")})) == "allow"
    assert decision(writer(repo, "Write", {"file_path": str(repo / "src/calc/new.py"), "content": ""})) == "block"
    assert decision(writer(repo, "Write", {"file_path": str(repo / "tests/test_spec.py"), "content": ""})) == "allow"
    fast = json.loads((repo / ".claude/testing-kit.json").read_text())["commands"]["fast"]
    interpreter = fast.split(" -m ")[0]
    assert decision(writer(repo, "Bash", {"command": f"{interpreter} -c \"import calc, inspect; print(inspect.getsource(calc))\""})) == "block"
    assert decision(writer(repo, "Bash", {"command": f"{fast} tests/test_spec.py"})) == "allow"


def test_config_guard_blocks_settings_changes_mid_session(repo):
    code, _, err = run_hook(repo, "config_guard.py", {"hook_event_name": "ConfigChange", "source": "local_settings"})
    assert code == 2
    assert run_hook(repo, "config_guard.py", {"hook_event_name": "ConfigChange", "source": "user_settings"})[0] == 0
