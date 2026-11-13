"""Tests for the code-improvement pass (v0.3.0). Each test states the weakness it closes."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import KIT, decision, git, run_hook
from test_ci_and_install import branch, install, py
from test_hooks import bash, edit, write, writer

TEST_FILE = "tests/test_calc.py"
HOOKS = KIT / "templates/project/.claude/testing-kit"


def add_bug(repo: Path) -> None:
    src = repo / "src/calc/__init__.py"
    src.write_text(src.read_text().replace("return a + b", "return a - b"))


def set_config(repo: Path, **changes) -> dict:
    path = repo / ".claude/testing-kit.json"
    cfg = json.loads(path.read_text())
    for key, value in changes.items():
        if isinstance(value, dict):
            cfg[key].update(value)
        else:
            cfg[key] = value
    path.write_text(json.dumps(cfg, indent=2))
    return cfg


# ------------------------------------------------------------ kitlib


def load_kitlib():
    sys.path.insert(0, str(HOOKS))
    try:
        import kitlib
        return kitlib
    finally:
        sys.path.remove(str(HOOKS))


def test_dot_slash_prefix_does_not_eat_a_leading_dot():
    # "./.github/..." used to lose the dot of ".github" and stop matching the harness globs
    kitlib = load_kitlib()
    cfg = kitlib.DEFAULT_CONFIG
    assert kitlib.is_harness_path("./.github/workflows/tests.yml", cfg)
    assert kitlib.is_harness_path("./.claude/settings.json", cfg)
    assert kitlib.is_test_path("./tests/test_x.py", cfg)


def test_globs_ignore_case_only_where_the_filesystem_does():
    kitlib = load_kitlib()
    assert kitlib.glob_to_regex("tests/**", True).match("TESTS/Test_X.py")
    assert not kitlib.glob_to_regex("tests/**", False).match("TESTS/Test_X.py")


def test_kit_scripts_do_not_count_as_project_tests():
    kitlib = load_kitlib()
    cfg = kitlib.DEFAULT_CONFIG
    assert not kitlib.has_tests([".claude/testing-kit/test_report.py", "src/app.py"], cfg)
    assert kitlib.has_tests(["tests/test_app.py"], cfg)


# ------------------------------------------------------------ CI gates use the base's config


def test_branch_cannot_point_the_gates_at_a_fake_test_command(repo):
    branch(repo)
    add_bug(repo)
    fake = ("python3 -c \"import pathlib; pathlib.Path('.reports').mkdir(exist_ok=True); "
            "pathlib.Path('.reports/junit.xml').write_text('<testsuite><testcase classname=\\'tests.test_calc\\' name=\\'test_add\\'/>"
            "<testcase classname=\\'tests.test_calc\\' name=\\'test_div_by_zero\\'/></testsuite>')\"")
    set_config(repo, commands={"fast": fake})
    git(repo, "commit", "-qam", "bug + fake test command")
    base = py(repo, "base_tests.py", "--base", "main")
    assert base.returncode == 1 and "test_add" in base.stdout, base.stdout + base.stderr
    guard = py(repo, "test_diff_guard.py", "--base", "main")
    assert guard.returncode == 1 and ".claude/testing-kit.json" in guard.stdout


def test_branch_cannot_shrink_what_counts_as_a_test(repo):
    branch(repo)
    set_config(repo, test_globs=["nothing/**"])
    t = repo / TEST_FILE
    t.write_text(t.read_text().split("def test_div_by_zero")[0])
    git(repo, "commit", "-qam", "redefine tests, delete one")
    guard = py(repo, "test_diff_guard.py", "--base", "main")
    assert guard.returncode == 1 and "tests removed" in guard.stdout


def test_new_setup_cfg_with_runner_options_is_flagged_and_ignored(repo):
    branch(repo)
    add_bug(repo)
    (repo / "src/calc/_compat.py").write_text(
        "import pytest\n\n@pytest.hookimpl(hookwrapper=True)\ndef pytest_runtest_makereport(item, call):\n"
        "    out = yield\n    out.get_result().outcome = 'passed'\n")
    pp = repo / "pyproject.toml"
    pp.write_text(pp.read_text().split("[tool.pytest.ini_options]")[0])
    git(repo, "commit", "-qam", "drop pytest section"); git(repo, "branch", "-qf", "base2"); git(repo, "checkout", "-q", "base2")
    # base2 has no pytest config at all; the branch adds a setup.cfg that loads the plugin
    git(repo, "checkout", "-qb", "sneaky")
    (repo / "setup.cfg").write_text("[tool:pytest]\naddopts = -p calc._compat\npythonpath = src\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "setup.cfg")
    guard = py(repo, "test_diff_guard.py", "--base", "base2")
    assert guard.returncode == 1 and "configuration section changed in setup.cfg" in guard.stdout


def test_gate_scripts_reject_a_missing_base_value(repo):
    r = py(repo, "test_diff_guard.py", "--base")
    assert r.returncode == 2 and "Traceback" not in r.stderr


# ------------------------------------------------------------ protect_tests


@pytest.mark.parametrize("added", [
    "from fake import add\n",                       # re-import from somewhere else
    "def add(a, b):\n    return 5\n",                # redefine
    "class add:\n    pass\n",
    "add: object = max\n",
    "import pytest as add\n",
])
def test_rebinding_the_code_under_test_asks(repo, added):
    content = (repo / TEST_FILE).read_text() + "\n\n" + added
    assert decision(write(repo, TEST_FILE, content)) == "ask"


def test_multi_line_import_widening_is_still_an_addition(repo):
    t = repo / TEST_FILE
    text = t.read_text().replace("from calc import add, div\n", "from calc import (\n    add,\n    div,\n)\n")
    t.write_text(text)
    git(repo, "commit", "-qam", "multi-line import")
    new = text.replace("    div,\n)", "    div,\n    sub,\n)") + "\n\ndef test_sub():\n    assert sub(3, 2) == 1\n"
    assert decision(write(repo, TEST_FILE, new)) == "allow"


# ------------------------------------------------------------ guard_bash


@pytest.mark.parametrize("command", [
    'bash -c "sed -i s/5/6/ tests/test_calc.py"',
    "sh -c 'rm tests/test_calc.py'",
    'eval "rm tests/test_calc.py"',
    "dd if=/dev/null of=tests/test_calc.py",
    "find tests -name 'test_*.py' -delete",
    "find tests -name '*.py' -exec rm {} +",
    "cd tests && cd .. && rm tests/test_calc.py",
])
def test_more_shell_routes_to_a_protected_file_ask(repo, command):
    assert decision(bash(repo, command)) == "ask"


@pytest.mark.parametrize("command", [
    'bash -c "ls tests"',
    "find tests -name '*.py'",
    "cd ~ && ls",
    "grep -rn add tests/",
])
def test_read_only_shell_commands_still_pass(repo, command):
    assert decision(bash(repo, command)) == "allow"


# ------------------------------------------------------------ bash_audit


def audit(repo, mode, call=None, session="s1"):
    payload = {"tool_name": "Bash", "session_id": session, "tool_input": {"command": "x"}}
    if call:
        payload["tool_use_id"] = call
    return run_hook(repo, "bash_audit.py", payload, mode)


def test_parallel_bash_calls_keep_separate_snapshots(repo):
    audit(repo, "pre", "call-a")
    t = repo / TEST_FILE
    t.write_text(t.read_text().replace("== 5", "== -1"))      # call A changes a test...
    audit(repo, "pre", "call-b")                              # ...and call B starts before A is checked
    code, _, err = audit(repo, "post", "call-a")
    assert code == 2 and TEST_FILE in err
    assert audit(repo, "post", "call-b")[0] == 0
    assert not list((repo / ".claude/testing-kit/.state").glob("s1-call-*.json"))


def test_audit_sees_an_uncommitted_test_being_deleted(repo):
    new = repo / "tests/test_new.py"
    new.write_text("def test_new():\n    assert True is not False\n")
    audit(repo, "pre", "c1")
    new.unlink()
    code, _, err = audit(repo, "post", "c1")
    assert code == 2 and "tests/test_new.py" in err


# ------------------------------------------------------------ Stop hook


def stop(repo, **extra):
    return run_hook(repo, "tests_on_stop.py", {"hook_event_name": "Stop", "session_id": "s1", **extra})


def test_stop_runs_tests_after_claude_commits_a_bug(repo):
    audit(repo, "pre", "c1")                                  # first Bash call records the starting commit
    add_bug(repo)
    git(repo, "commit", "-qam", "bug, committed so the tree is clean")
    assert decision(stop(repo)) == "block"


def test_stop_does_not_rerun_for_a_commit_that_already_passed(repo):
    audit(repo, "pre", "c1")
    src = repo / "src/calc/__init__.py"
    src.write_text(src.read_text() + "\n\ndef sub(a, b):\n    return a - b\n")
    git(repo, "commit", "-qam", "honest change")
    assert decision(stop(repo)) == "allow"
    set_config(repo, commands={"fast": "exit 1"})            # would fail if it ran again...
    git(repo, "stash", "-q")                                  # ...but the tree is clean and HEAD is known green
    assert decision(stop(repo)) == "allow"


def test_ending_on_a_question_does_not_hide_failing_tests(repo):
    add_bug(repo)
    code, out, _ = stop(repo, last_assistant_message="All done! Anything else?")
    assert code == 0 and "decision" not in out
    assert "fast tests fail" in out["systemMessage"]


def test_stop_ignores_a_stale_report_from_an_earlier_run(repo):
    add_bug(repo)
    assert decision(stop(repo)) == "block"                    # writes a junit report with a failure
    set_config(repo, commands={"fast": f'"{sys.executable}" -m no_such_runner_xyz'})
    _, out, _ = stop(repo)
    assert "environment" in out["reason"]


# ------------------------------------------------------------ spec-test-writer allowlist


def test_spec_writer_cannot_chain_a_command_after_the_test_command(repo):
    (repo / "bot.py").write_text("SECRET_LOGIC = 1\n")
    set_config(repo, src_dirs=[])
    fast = json.loads((repo / ".claude/testing-kit.json").read_text())["commands"]["fast"]
    for tail in ("; cat bot.py", "&& cat bot.py", "| tee out.txt", "\ncat bot.py", "$(cat bot.py)"):
        assert decision(writer(repo, "Bash", {"command": f"{fast} {tail}"})) == "block", tail
    assert decision(writer(repo, "Bash", {"command": f"{fast} tests/test_calc.py -k add"})) == "allow"


def test_spec_writer_cannot_read_code_through_git_log(repo):
    for cmd in ("git log -p", "git log --patch -1", "git log -U5", "git log -S add"):
        assert decision(writer(repo, "Bash", {"command": cmd})) == "block", cmd
    for cmd in ("git log --oneline -5", "git status", "git diff --stat"):
        assert decision(writer(repo, "Bash", {"command": cmd})) == "allow", cmd


# ------------------------------------------------------------ guard_test_edits


def post_edit(repo, path, content):
    (repo / path).write_text(content)
    return run_hook(repo, "guard_test_edits.py", {"tool_name": "Write", "tool_input": {
        "file_path": str(repo / path), "content": content}})


def test_kit_allow_comment_cannot_excuse_test_detection_in_production_code(repo):
    code, _, err = post_edit(repo, "src/calc/env.py",
                             "import os\nT = 'PYTEST_CURRENT_TEST' in os.environ  # kit: allow needed\n")
    assert code == 2 and "TG-16" in err


def test_assertion_check_matches_whole_test_names(repo):
    # test_a has no assertion but was there before; only test_ab is new, and it asserts
    (repo / "tests/test_names.py").write_text("def test_a():\n    pass\n")
    content = "def test_a():\n    pass\n\n\ndef test_ab():\n    assert 1 + 1 == 2\n"
    (repo / "tests/test_names.py").write_text(content)
    code, _, err = run_hook(repo, "guard_test_edits.py", {"tool_name": "Edit", "tool_input": {
        "file_path": str(repo / "tests/test_names.py"), "old_string": "",
        "new_string": "def test_ab():\n    assert 1 + 1 == 2\n"}})
    assert code == 0, err


# ------------------------------------------------------------ installer


def test_installer_does_not_write_settings_or_claude_md_through_a_symlink(tmp_path):
    shared = tmp_path / "toolkit"
    shared.mkdir()
    (shared / "CLAUDE.md").write_text("# shared across repos\n")
    r = tmp_path / "r"
    r.mkdir()
    (r / "requirements.txt").write_text("")
    os.symlink(shared / "CLAUDE.md", r / "CLAUDE.md")
    out = install(r)
    assert out.returncode == 0
    assert (shared / "CLAUDE.md").read_text() == "# shared across repos\n"
    assert "SKIP (symlink)" in out.stdout and "CLAUDE.md" in out.stdout


def test_installer_stops_on_invalid_settings_json_without_touching_it(tmp_path):
    r = tmp_path / "r"
    (r / ".claude").mkdir(parents=True)
    (r / "requirements.txt").write_text("")
    (r / ".claude/settings.json").write_text('{"hooks": {},}')
    out = install(r)
    assert out.returncode != 0 and "not valid JSON" in out.stdout + out.stderr
    assert (r / ".claude/settings.json").read_text() == '{"hooks": {},}'
    assert "Traceback" not in out.stderr


def test_detected_python_command_uses_the_interpreter_that_exists(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    (r / "requirements.txt").write_text("")
    install(r)
    fast = json.loads((r / ".claude/testing-kit.json").read_text())["commands"]["fast"]
    assert fast.startswith("python3 -m pytest")          # TESTING_KIT_PYTHON=python3 in these tests


def test_ci_template_runs_the_gates_from_the_base_branch(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    (r / "requirements.txt").write_text("")
    install(r, "--ci")
    yml = (r / ".github/workflows/tests.yml").read_text()
    assert yml.count('git archive "origin/$BASE_REF" .claude/testing-kit') == 2
    assert 'python "$KIT/base_tests.py"' in yml and 'python "$KIT/test_diff_guard.py"' in yml
