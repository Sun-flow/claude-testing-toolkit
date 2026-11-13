"""Regression tests for the round 2 review findings (reviews/round2-*.md). Each test names its finding."""
import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import KIT, decision, git, lines_with_private_words, run_hook
from test_ci_and_install import branch, install, py
from test_hooks import bash, edit, write

TEST_FILE = "tests/test_calc.py"
BUG = ("return a + b", "return a - b")


def add_bug(repo: Path) -> None:
    src = repo / "src/calc/__init__.py"
    src.write_text(src.read_text().replace(*BUG))


def ci(repo: Path, env=None):
    guard = py(repo, "test_diff_guard.py", "--base", "main", env=env)
    base = py(repo, "base_tests.py", "--base", "main", env=env)
    return guard, base


# ------------------------------------------------------------ CI gates


def test_adv2_1_new_runner_config_and_plugin_cannot_hide_a_bug(repo):
    branch(repo)
    add_bug(repo)
    (repo / "src/calc/_compat.py").write_text(
        "import pytest\n\n@pytest.hookimpl(hookwrapper=True)\ndef pytest_runtest_makereport(item, call):\n"
        "    out = yield\n    rep = out.get_result()\n    rep.outcome = 'passed'\n")
    (repo / "pytest.toml").write_text('[pytest]\naddopts = ["-q", "-p", "calc._compat"]\npythonpath = ["src"]\n')
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "sneaky plugin")
    guard, base = ci(repo)
    assert guard.returncode == 1 and "pytest.toml" in guard.stdout
    assert base.returncode == 1, base.stdout + base.stderr
    assert "test_add" in base.stdout and "ignored (new on this branch)  pytest.toml" in base.stdout


def test_adv2_1_hook_asks_before_writing_a_new_runner_config(repo):
    assert decision(write(repo, "pytest.toml", "[pytest]\n")) == "ask"
    assert decision(write(repo, "vite.config.ts", "export default {}\n")) == "ask"


def test_adv2_2_ci_catches_sys_modules_test_detection(repo):
    branch(repo)
    src = repo / "src/calc/__init__.py"
    src.write_text("import sys\n" + src.read_text().replace(
        "    return a + b", "    if 'pytest' in sys.modules and (a, b) == (2, 3):\n        return 5\n    return a - b"))
    git(repo, "commit", "-qam", "special-case the test")
    guard, _ = ci(repo)
    assert guard.returncode == 1 and "TG-16" in guard.stdout


def test_adv2_2_split_string_is_still_flagged_by_the_hook(repo):
    content = "import os\nT = os.environ.get('PYTEST_' + 'CURRENT_TEST')\n"
    code, _, _ = run_hook(repo, "guard_test_edits.py", {"tool_name": "Write", "tool_input": {
        "file_path": str(repo / "src/calc/env.py"), "content": content}})
    (repo / "src/calc/env.py").write_text(content)
    code, _, err = run_hook(repo, "guard_test_edits.py", {"tool_name": "Write", "tool_input": {
        "file_path": str(repo / "src/calc/env.py"), "content": content}})
    assert code == 2 and "TG-16" in err


def test_adv2_3_committed_report_and_disabled_junit_do_not_pass(repo):
    branch(repo)
    add_bug(repo)
    (repo / ".reports").mkdir(exist_ok=True)
    (repo / ".reports/junit.xml").write_text(
        '<testsuite tests="2"><testcase classname="tests.test_calc" name="test_add"/>'
        '<testcase classname="tests.test_calc" name="test_div_by_zero"/></testsuite>')
    (repo / ".pytest.toml").write_text('[pytest]\naddopts = ["-p", "no:junitxml"]\npythonpath = ["src"]\n')
    git(repo, "add", "-f", "-A"); git(repo, "commit", "-qm", "fake report")
    guard, base = ci(repo)
    assert guard.returncode == 1 and "test report committed" in guard.stdout
    assert base.returncode == 1, base.stdout + base.stderr


def test_adv2_5_module_level_skip_is_caught(repo):
    branch(repo)
    t = repo / TEST_FILE
    t.write_text(t.read_text().replace("import pytest\n", "import pytest\npytestmark = pytest.mark.skip(reason='wip')\n", 1))
    git(repo, "commit", "-qam", "skip module")
    guard, _ = ci(repo)
    assert guard.returncode == 1 and "skip/xfail/only marker added" in guard.stdout
    assert decision(edit(repo, TEST_FILE, "import pytest\n", "import pytest\npytestmark = pytest.mark.skip\n")) == "ask"


def test_adv2_5_shadowing_the_code_under_test_asks(repo):
    assert decision(edit(repo, TEST_FILE, "import pytest\n", "import pytest\nadd = lambda a, b: a + b\n")) == "ask"


def test_adv2_6_and_10_tests_are_compared_by_class(repo):
    t = repo / TEST_FILE
    t.write_text(t.read_text() + "\n\nclass TestAdd:\n    def test_zero(self):\n        assert add(0, 0) == 0\n")
    git(repo, "commit", "-qam", "class test")
    # adding a same-named test in another class is not shadowing (ADV2-10)
    new = t.read_text() + "\n\nclass TestDiv:\n    def test_zero(self):\n        assert div(0, 1) == 0\n"
    assert decision(write(repo, TEST_FILE, new)) == "allow"
    t.write_text(new)
    git(repo, "commit", "-qam", "div class")
    branch(repo)
    t.write_text(t.read_text().split("\n\nclass TestDiv")[0] + "\n")
    git(repo, "commit", "-qam", "drop TestDiv")
    guard, _ = ci(repo)
    assert guard.returncode == 1 and "TestDiv::test_zero" in guard.stdout


def test_use2_1_label_lets_an_approved_test_fix_through_base_tests(repo):
    branch(repo)
    src = repo / "src/calc/__init__.py"
    src.write_text(src.read_text().replace("return a + b", "return a + b + 0.0"))
    t = repo / TEST_FILE
    t.write_text(t.read_text().replace("assert add(2, 3) == 5", "assert add(2, 3) == 5.0\n    assert add(1, 1) == 3"))
    git(repo, "commit", "-qam", "approved change")
    add_bug(repo); git(repo, "commit", "-qam", "bug")
    _, base = ci(repo)
    assert base.returncode == 1 and "allow-test-changes" in base.stdout
    _, base = ci(repo, env={"ALLOW_TEST_CHANGES": "1"})
    assert base.returncode == 0 and "NOW FAILING" in base.stdout


def test_use2_5_first_tests_in_a_fresh_repo_pass_the_gates(tmp_path):
    r = tmp_path / "fresh"
    (r / "src/app").mkdir(parents=True)
    (r / "pyproject.toml").write_text('[project]\nname = "app"\nversion = "0"\n\n[tool.pytest.ini_options]\npythonpath = ["src"]\n')
    (r / "src/app/__init__.py").write_text("def one():\n    return 1\n")
    git(r, "init", "-q", "-b", "main"); git(r, "config", "user.email", "k@e.com"); git(r, "config", "user.name", "k")
    assert install(r).returncode == 0
    cfg = json.loads((r / ".claude/testing-kit.json").read_text())
    cfg["commands"]["fast"] = f'"{sys.executable}" -m pytest -q -p no:cacheprovider --junitxml=.reports/junit.xml'
    cfg["commands"]["setup"] = ""
    (r / ".claude/testing-kit.json").write_text(json.dumps(cfg))
    git(r, "add", "-A"); git(r, "commit", "-qm", "kit")
    branch(r)
    (r / "tests").mkdir()
    (r / "tests/conftest.py").write_text("")
    (r / "tests/test_one.py").write_text("from app import one\n\ndef test_one_rejects_nothing():\n    assert one() == 1\n")
    git(r, "add", "-A"); git(r, "commit", "-qm", "first tests")
    guard, base = ci(r)
    assert guard.returncode == 0, guard.stdout
    assert base.returncode == 0 and "no tests yet" in base.stdout


# ------------------------------------------------------------ hooks


def test_use2_2_hooks_leave_no_bytecode_in_the_repo(repo):
    decision(edit(repo, TEST_FILE, "== 5", "== 6"))
    bash(repo, "ls")
    assert not list((repo / ".claude/testing-kit").glob("__pycache__"))


def test_adv2_7_cd_does_not_hide_a_protected_path(repo):
    assert decision(bash(repo, 'cd tests && sed -i "s/== 5/== -1/" test_calc.py')) == "ask"
    assert decision(bash(repo, "rm -f .claude/testing-kit/.state/*")) == "block"


def test_adv2_7_missing_audit_state_is_reported(repo):
    code, _, err = run_hook(repo, "bash_audit.py", {"tool_name": "Bash", "session_id": "gone",
                                                    "tool_input": {"command": "true"}}, "post")
    assert code == 2 and "missing" in err


def test_adv2_8_mech2_2_symlinks_do_not_bypass_protection(repo, tmp_path):
    link = tmp_path / "tl"
    os.symlink(repo / "tests", link)
    r = run_hook(repo, "protect_tests.py", {"tool_name": "Edit", "tool_input": {
        "file_path": str(link / "test_calc.py"), "old_string": "== 5", "new_string": "== 6"}})
    assert decision(r) == "ask"
    proj_link = tmp_path / "proj"
    os.symlink(repo, proj_link)
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(proj_link)}
    payload = {"tool_name": "Edit", "cwd": str(proj_link), "tool_input": {
        "file_path": str(repo / TEST_FILE), "old_string": "== 5", "new_string": "== 6"}}
    p = subprocess.run([sys.executable, str(repo / ".claude/testing-kit/protect_tests.py")], input=json.dumps(payload),
                       capture_output=True, text=True, env=env)
    assert '"ask"' in p.stdout


def test_mech2_1_a_crashing_guard_asks_instead_of_allowing(repo):
    cfg = json.loads((repo / ".claude/testing-kit.json").read_text())
    cfg["test_globs"] = 5  # not a list: matching crashes
    (repo / ".claude/testing-kit.json").write_text(json.dumps(cfg))
    r = edit(repo, TEST_FILE, "== 5", "== 6")
    assert decision(r) == "ask" and "check failed" in r[1]["hookSpecificOutput"]["permissionDecisionReason"]


def test_mech2_1_non_object_stdin_is_harmless(repo):
    p = subprocess.run([sys.executable, str(repo / ".claude/testing-kit/protect_tests.py")], input="[1, 2]",
                       capture_output=True, text=True, env={**os.environ, "CLAUDE_PROJECT_DIR": str(repo)})
    assert p.returncode == 0


def test_mech2_3_broken_config_fails_closed(repo):
    (repo / ".claude/testing-kit.json").write_text('{"enforcement": "ask",}')
    code, _, err = edit(repo, TEST_FILE, "== 5", "== 6")
    assert code == 2 and "testing-kit.json" in err


def test_use2_7_deny_message_names_the_way_forward(repo):
    cfg = json.loads((repo / ".claude/testing-kit.json").read_text())
    cfg["enforcement"] = "deny"
    (repo / ".claude/testing-kit.json").write_text(json.dumps(cfg))
    code, _, err = edit(repo, TEST_FILE, "== 5", "== 6")
    assert code == 2 and "allow-test-edits" in err and "Approve only" not in err


def test_use2_9_widening_an_import_is_an_addition(repo):
    old = "from calc import add, div\n"
    new = "from calc import add, div, sub\n"
    t = (repo / TEST_FILE).read_text()
    content = t.replace(old, new) + "\n\ndef test_sub():\n    assert sub(3, 2) == 1\n"
    assert decision(write(repo, TEST_FILE, content)) == "allow"


def test_use2_8_stop_allows_a_question_and_names_environment_failures(repo):
    t = repo / TEST_FILE
    t.write_text(t.read_text().replace("== 5", "== 6"))
    payload = {"hook_event_name": "Stop", "last_assistant_message": "Should add() accept None?"}
    assert decision(run_hook(repo, "tests_on_stop.py", payload)) == "allow"
    cfg = json.loads((repo / ".claude/testing-kit.json").read_text())
    cfg["commands"]["fast"] = f'"{sys.executable}" -m no_such_runner_xyz'
    (repo / ".claude/testing-kit.json").write_text(json.dumps(cfg))
    code, out, _ = run_hook(repo, "tests_on_stop.py", {"hook_event_name": "Stop"})
    assert out["decision"] == "block" and "environment" in out["reason"]


# ------------------------------------------------------------ installer and CI templates


def make_node(tmp_path: Path, deps: dict, lock: str = "") -> Path:
    r = tmp_path / "node"
    r.mkdir()
    (r / "package.json").write_text(json.dumps({"devDependencies": deps}))
    if lock:
        (r / lock).write_text("")
    return r


def test_mech2_4_pip_projects_get_pip_ci(tmp_path):
    r = tmp_path / "p"
    r.mkdir()
    (r / "requirements.txt").write_text("")
    assert install(r, "--ci").returncode == 0
    yml = (r / ".github/workflows/testing-kit.yml").read_text()
    assert "uv sync" not in yml and "pip install -r requirements.txt" in yml and "{{CI_" not in yml
    assert "labeled" in yml and "hashFiles" in yml
    assert "pytest-randomly" in (r / ".github/workflows/flake-finder.yml").read_text()


def test_mech2_6_7_8_node_ci_matches_the_package_manager(tmp_path):
    r = make_node(tmp_path, {"jest": "^29"}, "pnpm-lock.yaml")
    out = install(r, "--ci")
    assert out.returncode == 0 and "jest-junit" in out.stdout
    yml = (r / ".github/workflows/testing-kit.yml").read_text()
    assert "pnpm install --frozen-lockfile" in yml and ".nvmrc" not in yml and "{{CI_" not in yml
    assert not (r / ".github/workflows/flake-finder.yml").exists()


def test_use2_12_owner_writes_codeowners_with_ci(tmp_path):
    r = make_node(tmp_path, {"vitest": "^3"})
    install(r, "--ci", "--owner", "@team")
    assert "@team" in (r / ".github/CODEOWNERS").read_text()


def test_mech2_12_profile_downgrade_removes_the_stop_hook(repo):
    assert install(repo, "--profile", "minimal").returncode == 0
    s = json.loads((repo / ".claude/settings.json").read_text())
    assert "Stop" not in s["hooks"]


def test_use2_6_installed_docs_are_neutral(repo):
    text = (repo / "docs/testing/REVIEW-PROTOCOL.md").read_text()
    found = lines_with_private_words(text)
    assert not found, f"lines that name the kit author's own people or projects: {found}"


def test_use2_11_check_reports_a_fast_command_that_cannot_run(repo):
    cfg = json.loads((repo / ".claude/testing-kit.json").read_text())
    cfg["commands"]["fast"] = f'"{sys.executable}" -m no_such_runner_xyz -q'
    (repo / ".claude/testing-kit.json").write_text(json.dumps(cfg))
    r = subprocess.run([sys.executable, str(KIT / "install.py"), "--check", str(repo)], capture_output=True, text=True,
                       env={**os.environ, "TESTING_KIT_PYTHON": "python3"})
    assert r.returncode == 1 and "not installed" in r.stdout
