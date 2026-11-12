import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import KIT, git

GOOD_JUNIT = """<testsuites><testsuite name="s" tests="5">
<testcase classname="t" name="a" time="0.1"/>
<testcase classname="t" name="b" time="0.1"><failure type="AssertionError" message="assert 3 == 4"/></testcase>
<testcase classname="t" name="c" time="0.1"><failure type="AssertionError" message="assert 7 == 9"/></testcase>
<testcase classname="t" name="d" time="0.1"><error type="ConnectionError" message="db at 10.0.0.1:5432 refused"/></testcase>
<testcase classname="t" name="e" time="0.0"><skipped message="needs GPU"/></testcase>
</testsuite></testsuites>"""


def py(repo: Path, script: str, *args: str, env=None):
    return subprocess.run([sys.executable, str(repo / ".claude/testing-kit" / script), *args], cwd=repo,
                          capture_output=True, text=True, env={**os.environ, **(env or {})})


def test_report_groups_failures_by_cause_and_lists_what_was_not_tested(repo):
    (repo / "junit.xml").write_text(GOOD_JUNIT)
    r = py(repo, "test_report.py", "junit.xml")
    assert r.returncode == 1
    assert "FAILED (2 distinct cause(s))" in r.stdout          # the two assert N == N failures group together
    assert "needs GPU" in r.stdout and "NOT TESTED" in r.stdout


def test_report_flags_zero_tests_collected(repo):
    (repo / "empty.xml").write_text("<testsuite tests='0'></testsuite>")
    r = py(repo, "test_report.py", "empty.xml")
    assert r.returncode == 1 and "zero tests collected" in r.stdout


def branch(repo: Path) -> None:
    git(repo, "checkout", "-qb", "feature")


def test_diff_guard_passes_an_honest_change(repo):
    branch(repo)
    p = repo / "tests/test_calc.py"
    p.write_text(p.read_text() + "\n\ndef test_add_rejects_none():\n    import pytest\n    with pytest.raises(TypeError):\n        add(None, 1)\n")
    git(repo, "commit", "-qam", "more tests")
    r = py(repo, "test_diff_guard.py", "--base", "main")
    assert r.returncode == 0, r.stdout


def test_diff_guard_blocks_deleted_and_skipped_tests(repo):
    branch(repo)
    p = repo / "tests/test_calc.py"
    text = p.read_text().replace("def test_add():", "@pytest.mark.skip\ndef test_add():")
    text = text.split("def test_div_by_zero")[0]
    p.write_text(text)
    git(repo, "commit", "-qam", "weaken")
    r = py(repo, "test_diff_guard.py", "--base", "main")
    assert r.returncode == 1
    assert "tests removed" in r.stdout and "skip/xfail/only marker added" in r.stdout
    assert py(repo, "test_diff_guard.py", "--base", "main", env={"ALLOW_TEST_CHANGES": "1"}).returncode == 0


def test_diff_guard_blocks_test_config_and_test_env_checks(repo):
    branch(repo)
    pp = repo / "pyproject.toml"
    pp.write_text(pp.read_text().replace('addopts = "-q"', 'addopts = "-q -k not_add"'))
    (repo / "src/calc/env.py").write_text("import os\nTESTING = 'PYTEST_CURRENT_TEST' in os.environ\n")
    git(repo, "add", "-A"); git(repo, "commit", "-qm", "sneaky")
    r = py(repo, "test_diff_guard.py", "--base", "main")
    assert r.returncode == 1
    assert "configuration section changed in pyproject.toml" in r.stdout and "TG-16" in r.stdout


def test_base_tests_catch_a_bug_hidden_by_editing_the_test(repo):
    branch(repo)
    src = repo / "src/calc/__init__.py"
    src.write_text(src.read_text().replace("return a + b", "return a + b + 1"))
    t = repo / "tests/test_calc.py"
    t.write_text(t.read_text().replace("== 5", "== 6"))   # the "fix" that makes CI green
    git(repo, "commit", "-qam", "bug + matching test")
    r = py(repo, "base_tests.py", "--base", "main")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "test_add" in r.stdout


def test_base_tests_pass_an_honest_change(repo):
    branch(repo)
    src = repo / "src/calc/__init__.py"
    src.write_text(src.read_text() + "\n\ndef sub(a, b):\n    return a - b\n")
    git(repo, "commit", "-qam", "add sub")
    r = py(repo, "base_tests.py", "--base", "main")
    assert r.returncode == 0, r.stdout + r.stderr


# ------------------------------------------------------------ installer

def install(target: Path, *args: str):
    return subprocess.run([sys.executable, str(KIT / "install.py"), "--project", str(target), *args],
                          capture_output=True, text=True, env={**os.environ, "TESTING_KIT_PYTHON": "python3"})


def test_reinstall_is_idempotent(repo):
    r = install(repo)
    assert r.returncode == 0
    kinds = {line.split()[0] for line in r.stdout.splitlines() if line.startswith("  ")}
    assert kinds <= {"same", "keep", "update"}, r.stdout     # CLAUDE.md block is rewritten in place
    assert (repo / "CLAUDE.md").read_text().count("testing-kit:start") == 1
    settings = json.loads((repo / ".claude/settings.json").read_text())
    commands = [h["command"] for g in settings["hooks"]["PreToolUse"] for h in g["hooks"]]
    assert sum("protect_tests.py" in c for c in commands) == 1


def test_install_keeps_user_changes_and_existing_settings(tmp_path):
    r = tmp_path / "r"
    (r / ".claude/rules").mkdir(parents=True)
    (r / "package.json").write_text('{"devDependencies": {"vitest": "^3"}}')
    (r / ".claude/rules/testing.md").write_text("my own rules\n")
    (r / ".claude/settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(make *)"]},
                                                          "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}))
    (r / "CLAUDE.md").write_text("# Project\n\nExisting notes.\n")
    out = install(r)
    assert out.returncode == 0, out.stdout
    assert (r / ".claude/rules/testing.md").read_text() == "my own rules\n"
    assert (r / ".claude/rules/testing.md.kit-new").exists()
    s = json.loads((r / ".claude/settings.json").read_text())
    assert "Bash(make *)" in s["permissions"]["allow"]
    assert any(h["command"] == "say done" for g in s["hooks"]["Stop"] for h in g["hooks"])
    assert "Existing notes." in (r / "CLAUDE.md").read_text()
    cfg = json.loads((r / ".claude/testing-kit.json").read_text())
    assert "vitest run" in cfg["commands"]["fast"]


def test_install_never_writes_through_a_symlinked_skill(tmp_path):
    r = tmp_path / "r"
    toolkit_skill = tmp_path / "toolkit/run-tests"
    toolkit_skill.mkdir(parents=True)
    (toolkit_skill / "SKILL.md").write_text("toolkit version\n")
    (r / ".claude/skills").mkdir(parents=True)
    os.symlink(toolkit_skill, r / ".claude/skills/run-tests")
    (r / "requirements.txt").write_text("")
    out = install(r)
    assert out.returncode == 0
    assert (toolkit_skill / "SKILL.md").read_text() == "toolkit version\n"
    assert "SKIP (symlink)" in out.stdout


def test_minimal_profile_registers_only_the_guard_hooks(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    (r / "requirements.txt").write_text("")
    assert install(r, "--profile", "minimal").returncode == 0
    s = json.loads((r / ".claude/settings.json").read_text())
    assert "Stop" not in s["hooks"] and "PostToolUse" in s["hooks"]  # bash_audit post only
    assert not (r / ".claude/agents").exists()


def test_check_reports_ok_after_install(repo):
    r = subprocess.run([sys.executable, str(KIT / "install.py"), "--check", str(repo)], capture_output=True, text=True,
                       env={**os.environ, "TESTING_KIT_PYTHON": "python3"})
    assert r.returncode == 0, r.stdout


def test_diff_guard_blocks_coverage_pragmas_in_production_code(repo):
    branch(repo)
    src = repo / "src/calc/__init__.py"
    src.write_text(src.read_text() + "\n\ndef untested():  # pragma: no cover\n    return 1\n")
    git(repo, "commit", "-qam", "hide from coverage")
    r = py(repo, "test_diff_guard.py", "--base", "main")
    assert r.returncode == 1 and "coverage-exclusion pragma" in r.stdout
