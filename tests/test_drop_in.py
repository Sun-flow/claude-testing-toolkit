"""Tests for v0.4.0: what it takes to drop the kit into any existing repo and keep it there.
Each test states the snag it closes (found by installing the kit into real repos)."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from conftest import KIT, decision, git, lines_with_private_words, run_hook
from test_ci_and_install import branch, install, py
from test_hooks import edit, write
from test_improvement_pass import add_bug, load_kitlib, set_config

TEST_FILE = "tests/test_calc.py"
WORKFLOW = ".github/workflows/testing-kit.yml"
PYTEST = f'"{sys.executable}" -m pytest -q -p no:cacheprovider'
# No bytecode: a test here edits a source file right after a run, and Python reuses a .pyc when the
# file's size and whole-second timestamp haven't changed.
ENV = {**os.environ, "TESTING_KIT_PYTHON": "python3", "PYTHONDONTWRITEBYTECODE": "1"}


def installer(*args: str, kit: Path = KIT):
    return subprocess.run([sys.executable, str(kit / "install.py"), *args], capture_output=True, text=True, env=ENV)


def utf8(path: Path) -> str:
    """The kit's rules, skills, agents and docs are UTF-8; a Windows machine reads files in its code page by default."""
    return path.read_text(encoding="utf-8")


def config(repo: Path) -> dict:
    return json.loads((repo / ".claude/testing-kit.json").read_text())


def manifest(repo: Path) -> dict:
    return json.loads((repo / ".claude/testing-kit/manifest.json").read_text())


def hook_commands(repo: Path, event: str) -> list:
    settings = json.loads((repo / ".claude/settings.json").read_text())
    return [h["command"] for g in settings.get("hooks", {}).get(event, []) for h in g["hooks"]]


def commit(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)


# ------------------------------------------------------------ Stop hook: only when the session changed something


def start(repo, session="s1"):
    return run_hook(repo, "tests_on_stop.py", {"hook_event_name": "SessionStart", "source": "startup",
                                               "session_id": session}, "baseline")


def stop(repo, session="s1", **extra):
    return run_hook(repo, "tests_on_stop.py", {"hook_event_name": "Stop", "session_id": session, **extra})


def counting_runner(repo: Path, tmp_path: Path, exit_code: int) -> Path:
    """Make the fast tier a command that records each run in a file outside the repo."""
    log = tmp_path / "runs.log"
    (repo / "tools").mkdir(exist_ok=True)
    (repo / "tools/count_runs.py").write_text(
        "import sys\nwith open(sys.argv[1], 'a') as fh:\n    fh.write('x')\nsys.exit(int(sys.argv[2]))\n")
    set_config(repo, junit_path="", commands={"fast": f'"{sys.executable}" tools/count_runs.py "{log}" {exit_code}'})
    commit(repo, "counting runner")
    return log


def runs(log: Path) -> int:
    return len(log.read_text()) if log.exists() else 0


def test_changes_that_were_there_before_the_session_do_not_trigger_a_run(repo):
    add_bug(repo)                                   # the user's own unfinished work: the suite is red
    start(repo)
    assert decision(stop(repo)) == "allow"          # Claude only answered a question


def test_a_change_made_in_the_session_runs_the_tests_even_on_top_of_earlier_changes(repo):
    (repo / "notes.txt").write_text("the user's scratch file")
    start(repo)
    add_bug(repo)
    code, out, _ = stop(repo)
    assert out["decision"] == "block" and "FAILED" in out["reason"]


def test_a_state_that_already_passed_is_not_run_again(repo, tmp_path):
    log = counting_runner(repo, tmp_path, 0)
    start(repo)
    (repo / "src/calc/extra.py").write_text("X = 1\n")
    assert decision(stop(repo)) == "allow" and runs(log) == 1
    assert decision(stop(repo)) == "allow" and runs(log) == 1      # next turn, nothing new
    (repo / "src/calc/extra.py").write_text("X = 2\n")
    assert decision(stop(repo)) == "allow" and runs(log) == 2      # a new change runs again


def test_a_failed_run_is_repeated_once_then_only_reported_until_something_changes(repo, tmp_path):
    log = counting_runner(repo, tmp_path, 1)
    start(repo)
    (repo / "src/calc/extra.py").write_text("X = 1\n")
    assert decision(stop(repo)) == "block" and runs(log) == 1
    _, out, _ = stop(repo, stop_hook_active=True)                  # right after the block: one more try
    assert "fast tests fail" in out["systemMessage"] and runs(log) == 2
    _, out, _ = stop(repo)                                         # a later turn, nothing changed
    assert "decision" not in out and "nothing has changed" in out["systemMessage"] and runs(log) == 2
    (repo / "src/calc/extra.py").write_text("X = 2\n")
    assert decision(stop(repo)) == "block" and runs(log) == 3


def test_the_start_of_the_session_is_recorded_only_once(repo):
    start(repo)
    add_bug(repo)
    start(repo)                                     # e.g. SessionStart firing again after a compaction
    assert decision(stop(repo)) == "block"


def test_each_session_has_its_own_starting_point(repo):
    start(repo, "old")
    add_bug(repo)                                   # left behind by the old session
    start(repo, "new")
    assert decision(stop(repo, "new")) == "allow"
    assert decision(stop(repo, "old")) == "block"


def test_the_first_edit_records_the_start_when_session_start_did_not_run(repo):
    add_bug(repo)                                   # there before Claude did anything
    assert decision(edit(repo, "src/calc/extra.py", "", "X = 1\n")) == "allow"      # PreToolUse of the first edit
    assert decision(run_hook(repo, "tests_on_stop.py", {"hook_event_name": "Stop"})) == "allow"
    (repo / "src/calc/extra.py").write_text("X = 1\n")                               # ...now the edit happens
    assert decision(run_hook(repo, "tests_on_stop.py", {"hook_event_name": "Stop"})) == "block"


def test_a_failure_message_says_what_to_do_about_failures_that_were_already_there(repo):
    start(repo)
    add_bug(repo)
    _, out, _ = stop(repo)
    assert "already there before your change" in out["reason"] and "BLOCKED:" in out["reason"]


def test_without_a_junit_report_the_runner_output_is_shown(repo):
    set_config(repo, junit_path="", commands={"fast": PYTEST})
    commit(repo, "no junit")
    start(repo)
    add_bug(repo)
    _, out, _ = stop(repo)
    assert out["decision"] == "block" and "test_add" in out["reason"]
    assert not (repo / ".reports/junit.xml").exists()


def test_state_left_by_old_sessions_is_cleaned_up(repo):
    start(repo, "old")
    stale = repo / ".claude/testing-kit/.state/old.base"
    month_ago = time.time() - 30 * 24 * 3600
    os.utime(stale, (month_ago, month_ago))
    start(repo, "new")
    assert not stale.exists() and (repo / ".claude/testing-kit/.state/new.base").exists()
    assert git(repo, "status", "--porcelain") == ""             # state never shows up as a change


def test_fingerprint_follows_content_and_ignores_ignored_files(repo):
    kitlib = load_kitlib()
    clean = kitlib.tree_fingerprint(repo)
    assert clean and clean[1] is False
    (repo / ".reports").mkdir()
    (repo / ".reports/junit.xml").write_text("<testsuite/>")      # git-ignored: a test run doesn't count
    assert kitlib.tree_fingerprint(repo) == clean
    (repo / "notes.txt").write_text("a")
    one = kitlib.tree_fingerprint(repo)
    assert one[1] is True and one[0] != clean[0]
    (repo / "notes.txt").write_text("b")                          # same file list, different content
    assert kitlib.tree_fingerprint(repo)[0] != one[0]
    (repo / "notes.txt").unlink()
    assert kitlib.tree_fingerprint(repo) == clean                 # changed back: nothing to test
    assert kitlib.tree_fingerprint(repo.parent) is None           # not a git repository


def test_session_start_hook_is_registered_next_to_the_cloud_setup_hook(tmp_path):
    r = tmp_path / "r"
    r.mkdir()
    (r / "requirements.txt").write_text("")
    assert install(r, "--env").returncode == 0
    commands = hook_commands(r, "SessionStart")
    assert any("tests_on_stop.py\" baseline" in c for c in commands) and any("session_start.sh" in c for c in commands)
    assert install(r, "--profile", "minimal").returncode == 0    # no Stop hook, so no baseline; --env is remembered
    commands = hook_commands(r, "SessionStart")
    assert not any("tests_on_stop.py" in c for c in commands) and any("session_start.sh" in c for c in commands)
    assert install(r, "--no-env").returncode == 0
    assert hook_commands(r, "SessionStart") == [] and not (r / ".claude/testing-kit/session_start.sh").exists()


# ------------------------------------------------------------ package.json sections were never compared


PKG = {"name": "x", "version": "1.0.0", "scripts": {"test": "jest", "lint": "eslint ."},
       "jest": {"testMatch": ["**/*.test.js"]}}


def test_changing_the_jest_section_of_package_json_asks_and_is_blocked_in_ci(repo):
    (repo / "package.json").write_text(json.dumps(PKG, indent=2))
    commit(repo, "package.json")
    changed = json.dumps({**PKG, "jest": {"testMatch": ["nothing"]}}, indent=2)
    assert decision(write(repo, "package.json", changed)) == "ask"
    assert decision(write(repo, "package.json", json.dumps({**PKG, "version": "1.0.1"}, indent=2))) == "allow"
    branch(repo)
    (repo / "package.json").write_text(changed)
    commit(repo, "narrow jest")
    guard = py(repo, "test_diff_guard.py", "--base", "main")
    assert guard.returncode == 1 and "configuration section changed in package.json" in guard.stdout


def test_an_npm_test_script_the_command_goes_through_is_protected(tmp_path):
    r = tmp_path / "node"
    r.mkdir()
    (r / "package.json").write_text(json.dumps({"scripts": {"test": "node --test", "lint": "eslint ."}}, indent=2))
    git(r, "init", "-q", "-b", "main")
    assert install(r).returncode == 0
    cfg = config(r)
    assert cfg["commands"]["fast"] == "npm test" and cfg["junit_path"] == ""
    assert "scripts.test" in cfg["harness_sections"]["package.json"]
    assert '"jest"\\s*:' in cfg["harness_sections"]["package.json"]          # the built-in sections stay
    fake = json.dumps({"scripts": {"test": "true", "lint": "eslint ."}}, indent=2)
    assert decision(write(r, "package.json", fake)) == "ask"
    other = json.dumps({"scripts": {"test": "node --test", "lint": "eslint src"}}, indent=2)
    assert decision(write(r, "package.json", other)) == "allow"


# ------------------------------------------------------------ CI gate without a JUnit report (Go, Rust, make)


def exit_code_mode(repo: Path) -> None:
    set_config(repo, junit_path="", commands={"fast": PYTEST})
    commit(repo, "no junit report")


def hide_bug_by_editing_the_test(repo: Path) -> None:
    src = repo / "src/calc/__init__.py"
    src.write_text(src.read_text().replace("return a + b", "return a + b + 1"))
    t = repo / TEST_FILE
    t.write_text(t.read_text().replace("== 5", "== 6"))
    commit(repo, "bug + matching test")


def test_exit_code_mode_catches_a_bug_hidden_by_editing_the_test(repo):
    exit_code_mode(repo)
    branch(repo)
    hide_bug_by_editing_the_test(repo)
    r = py(repo, "base_tests.py", "--base", "main")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "compares exit codes" in r.stdout and "test_add" in r.stdout      # the runner's own output names it
    report = json.loads(py(repo, "base_tests.py", "--base", "main", "--json").stdout)
    assert report["mode"] == "exit_code" and report["base_exit"] == 0 and report["head_exit"] != 0
    assert py(repo, "base_tests.py", "--base", "main", env={"ALLOW_TEST_CHANGES": "1"}).returncode == 0


def test_exit_code_mode_passes_an_honest_change(repo):
    exit_code_mode(repo)
    branch(repo)
    src = repo / "src/calc/__init__.py"
    src.write_text(src.read_text() + "\n\ndef sub(a, b):\n    return a - b\n")
    (repo / "tests/test_sub.py").write_text("from calc import sub\n\n\ndef test_sub():\n    assert sub(3, 2) == 1\n")
    commit(repo, "add sub")
    r = py(repo, "base_tests.py", "--base", "main")
    assert r.returncode == 0, r.stdout + r.stderr


def test_exit_code_mode_asks_for_a_human_when_the_base_is_already_red(repo):
    (repo / "tests/test_red.py").write_text("def test_known_red():\n    assert 1 == 2\n")
    exit_code_mode(repo)                                           # main now has a failing test
    branch(repo)
    hide_bug_by_editing_the_test(repo)
    r = py(repo, "base_tests.py", "--base", "main")
    assert r.returncode == 1 and "already fail on the base" in r.stdout
    assert py(repo, "base_tests.py", "--base", "main", env={"ALLOW_TEST_CHANGES": "1"}).returncode == 0


def test_exit_code_mode_passes_a_branch_that_makes_a_red_base_green(repo):
    add_bug(repo)
    exit_code_mode(repo)                                           # main is red because of the bug
    branch(repo)
    src = repo / "src/calc/__init__.py"
    src.write_text(src.read_text().replace("return a - b", "return a + b"))
    commit(repo, "fix")
    r = py(repo, "base_tests.py", "--base", "main")
    assert r.returncode == 0 and "pass now" in r.stdout, r.stdout + r.stderr


def test_a_missing_report_is_explained_and_points_to_exit_code_mode(repo):
    set_config(repo, commands={"fast": PYTEST})                    # junit_path is still set, nothing writes it
    commit(repo, "command without a report")
    branch(repo)
    (repo / "src/calc/extra.py").write_text("X = 1\n")
    commit(repo, "change")
    r = py(repo, "base_tests.py", "--base", "main")
    assert r.returncode == 2 and '"junit_path": ""' in r.stdout
    assert "[100%]" in r.stdout                                    # the end of the base run is shown (pytest -qq)


def test_a_branch_cannot_redefine_the_script_the_test_command_goes_through(repo):
    (repo / "run_tests.py").write_text(
        "import subprocess, sys\nsys.exit(subprocess.call([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider']))\n")
    set_config(repo, junit_path="", commands={"fast": f'"{sys.executable}" run_tests.py'})
    commit(repo, "tests run through a script")

    def sneaky(name: str) -> None:
        git(repo, "checkout", "-qb", name, "main")
        add_bug(repo)
        (repo / "run_tests.py").write_text("import sys\nsys.exit(0)\n")
        commit(repo, "bug + a runner that always passes")

    sneaky("without")                                              # control: without runner_files it gets through
    assert py(repo, "base_tests.py", "--base", "main").returncode == 0
    git(repo, "checkout", "-q", "main")
    set_config(repo, runner_files=["run_tests.py"])
    commit(repo, "name the runner file")
    sneaky("with")
    r = py(repo, "base_tests.py", "--base", "main")
    assert r.returncode == 1, r.stdout + r.stderr
    guard = py(repo, "test_diff_guard.py", "--base", "main")
    assert guard.returncode == 0 and "test runner file changed: run_tests.py" in guard.stdout


def test_a_setup_failure_on_the_branch_copy_is_explained_and_a_human_can_pass_it(repo):
    (repo / "tools").mkdir()
    (repo / "tools/setup_check.py").write_text("import os, sys\nsys.exit(1 if os.path.exists('BROKEN') else 0)\n")
    set_config(repo, commands={"setup": f'"{sys.executable}" tools/setup_check.py'})
    commit(repo, "setup command")
    branch(repo)
    (repo / "BROKEN").write_text("")
    commit(repo, "break setup")
    r = py(repo, "base_tests.py", "--base", "main")
    assert r.returncode == 1 and "Setup failed" in r.stdout and "Traceback" not in r.stderr
    assert py(repo, "base_tests.py", "--base", "main", env={"ALLOW_TEST_CHANGES": "1"}).returncode == 0


def test_version_pin_files_stay_in_the_branch_copy_but_runner_config_does_not(repo):
    branch(repo)
    for name in (".python-version", ".nvmrc", ".npmrc"):
        (repo / name).write_text("x\n")
    commit(repo, "dotfiles")
    r = py(repo, "base_tests.py", "--base", "main")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ignored (new on this branch)  .npmrc" in r.stdout      # node-options in .npmrc can preload code
    assert ".python-version" not in r.stdout and ".nvmrc" not in r.stdout


def test_files_that_only_look_like_tests_can_be_excluded(repo):
    kitlib = load_kitlib()
    cfg = {**kitlib.DEFAULT_CONFIG, "not_test_globs": ["src/**/test_runner.py"]}
    assert kitlib.is_test_path("src/tools/test_runner.py", kitlib.DEFAULT_CONFIG)
    assert not kitlib.is_test_path("src/tools/test_runner.py", cfg)
    assert kitlib.is_test_path("tests/test_calc.py", cfg)
    (repo / "src/calc/test_runner.py").write_text("def run():\n    return 1\n")
    commit(repo, "a production file with a test-like name")
    assert decision(edit(repo, "src/calc/test_runner.py", "return 1", "return 2")) == "ask"
    set_config(repo, not_test_globs=["src/**/test_runner.py"])
    assert decision(edit(repo, "src/calc/test_runner.py", "return 1", "return 2")) == "allow"


@pytest.mark.parametrize("path", [
    "spec/models/user_spec.rb", "test/models/user_test.rb", "app/src/test/kotlin/UserTest.kt", "src/UserTest.cs",
    "Sources/AppTests/UserTests.swift", "tests/Unit/UserTest.php", "test/user_test.exs", "test/user_test.dart",
    "Tests/AppTests/Smoke.swift", "App.Tests/Smoke.cs",
])
def test_test_files_of_other_ecosystems_are_recognised(path):
    kitlib = load_kitlib()
    assert kitlib.is_test_path(path, kitlib.DEFAULT_CONFIG)


@pytest.mark.parametrize("path", ["spec/openapi.yaml", "src/user.rb", "docs/testing/GUIDELINES.md", "lib/protest.rb",
                                  "src/TestHelpers.kt", "src/Spec.rb", "src/Tests.Shared.cs"])
def test_files_that_are_not_tests_stay_unprotected(path):
    kitlib = load_kitlib()
    assert not kitlib.is_test_path(path, kitlib.DEFAULT_CONFIG)


def test_your_own_test_and_harness_patterns_add_to_the_built_in_ones(repo):
    (repo / "checks").mkdir()
    (repo / "checks/pricing.check.txt").write_text("total 5\n")
    (repo / "runner.settings").write_text("retries=0\n")
    commit(repo, "tests in a layout of our own")
    assert decision(edit(repo, "checks/pricing.check.txt", "total 5", "total 6")) == "allow"
    assert decision(edit(repo, "runner.settings", "retries=0", "retries=3")) == "allow"
    set_config(repo, extra_test_globs=["checks/**"], extra_harness_globs=["runner.settings"])
    assert decision(edit(repo, "checks/pricing.check.txt", "total 5", "total 6")) == "ask"
    assert decision(edit(repo, "runner.settings", "retries=0", "retries=3")) == "ask"
    assert decision(edit(repo, TEST_FILE, "== 5", "== 6")) == "ask"            # the built-in patterns still apply


def test_the_gates_find_the_default_branch_when_it_is_not_main(repo):
    git(repo, "branch", "-m", "main", "trunk")
    git(repo, "update-ref", "refs/remotes/origin/trunk", "trunk")              # as after a clone of such a repo
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
    git(repo, "checkout", "-qb", "feature")
    t = repo / TEST_FILE
    t.write_text(t.read_text().replace("def test_add():", "import pytest\n\n\n@pytest.mark.skip\ndef test_add():"))
    commit(repo, "skip a test")
    guard = py(repo, "test_diff_guard.py")                                     # no --base given
    assert guard.returncode == 1 and "against origin/trunk" in guard.stdout and "skip/xfail/only marker added" in guard.stdout
    gate = py(repo, "base_tests.py")
    assert gate.returncode == 0 and "Traceback" not in gate.stderr, gate.stdout + gate.stderr


# ------------------------------------------------------------ installer: more repos are recognised


def bare(tmp_path: Path, files: dict) -> Path:
    r = tmp_path / "r"
    r.mkdir()
    for name, text in files.items():
        (r / name).parent.mkdir(parents=True, exist_ok=True)
        (r / name).write_text(text)
    return r


def test_a_python_repo_without_packaging_files_is_recognised(tmp_path):
    r = bare(tmp_path, {"tests/test_app.py": "def test_ok():\n    assert 1 + 1 == 2\n", "app.py": "X = 1\n"})
    out = install(r, "--ci")
    assert out.returncode == 0 and "Detected stack: python" in out.stdout
    cfg = config(r)
    assert cfg["commands"]["fast"] == "python3 -m pytest -q --junitxml=.reports/junit.xml"
    assert cfg["commands"]["setup"] == "" and cfg["junit_path"] == ".reports/junit.xml"
    yml = (r / WORKFLOW).read_text()
    assert "python -m pip install pytest" in yml and "cache: pip" not in yml    # no requirements file to key a cache on
    assert "&& \n" not in yml and "{{" not in yml.replace("${{", "")


def test_node_repo_with_python_helper_tests_is_still_node(tmp_path):
    r = bare(tmp_path, {"package.json": json.dumps({"devDependencies": {"vitest": "^3"}}),
                        "tests/test_e2e.py": "def test_ok():\n    assert True\n"})
    assert "Detected stack: node" in install(r).stdout


@pytest.mark.parametrize("manifest_file, stack, command, setup_step", [
    ("go.mod", "go", "go test ./...", "actions/setup-go@v6"),
    ("Cargo.toml", "rust", "cargo test", "preinstalled"),
])
def test_go_and_rust_get_a_workflow_and_compare_exit_codes(tmp_path, manifest_file, stack, command, setup_step):
    r = bare(tmp_path, {manifest_file: "module example.com/x\n"})
    out = install(r, "--ci")
    assert out.returncode == 0 and f"Detected stack: {stack}" in out.stdout
    assert "compares exit codes" in out.stdout
    cfg = config(r)
    assert cfg["commands"]["fast"] == command and cfg["junit_path"] == ""
    yml = (r / WORKFLOW).read_text()
    assert command in yml and setup_step in yml and "{{" not in yml.replace("${{", "")
    assert not (r / ".github/workflows/flake-finder.yml").exists()


def test_an_unrecognised_repo_is_told_how_to_set_the_command_and_the_flag_does_it(tmp_path):
    r = bare(tmp_path, {"Makefile": "test:\n\t./run-tests\n", "run-tests": "#!/bin/sh\n"})
    out = install(r, "--ci")
    assert out.returncode == 0 and '--fast "<your test command>"' in out.stdout
    assert not (r / WORKFLOW).exists()
    assert installer("--check", str(r)).returncode == 1
    out = install(r, "--fast", "make test", "--setup", "make deps")
    assert out.returncode == 0 and "make test (from --fast)" in out.stdout
    cfg = config(r)
    assert cfg["commands"] == {**cfg["commands"], "fast": "make test", "full": "make test", "setup": "make deps"}
    assert "Makefile" in cfg["runner_files"] and cfg["junit_path"] == ""
    yml = (r / WORKFLOW).read_text()             # --ci was remembered from the first run
    assert "make test" in yml and "make deps" in yml
    assert "Fast tier" in (r / "CLAUDE.md").read_text() and "make test" in (r / "CLAUDE.md").read_text()


def test_a_command_given_later_keeps_the_rest_of_your_config(repo):
    set_config(repo, high_paths=["src/calc/**"], enforcement="deny")
    out = install(repo, "--fast", f"{PYTEST} --junitxml=.reports/junit.xml tests")
    assert out.returncode == 0
    cfg = config(repo)
    assert cfg["commands"]["fast"].endswith("tests") and cfg["commands"]["setup"] == ""
    assert cfg["high_paths"] == ["src/calc/**"] and cfg["enforcement"] == "deny"


def test_the_workflow_runs_the_command_from_your_config_and_gives_both_gates_the_label(repo):
    assert install(repo, "--ci").returncode == 0
    yml = (repo / WORKFLOW).read_text()
    assert "no:cacheprovider" in yml                                   # the fixture's edited command, not the detected one
    assert yml.count("ALLOW_TEST_CHANGES: ${{ contains(") == 2          # base-tests used to ignore the label
    assert "include-hidden-files: true" in yml                         # .reports/ is a hidden directory


def test_codeowners_owner_is_written_once(tmp_path):
    r = bare(tmp_path, {"requirements.txt": ""})
    install(r, "--ci", "--owner", "@team")
    text = (r / ".github/CODEOWNERS").read_text()
    assert "@team" in text and "@@" not in text


def test_a_broken_config_stops_the_install_before_anything_changes(repo):
    (repo / ".claude/testing-kit.json").write_text('{"commands": {"fast": "x"},}')
    before = git(repo, "status", "--porcelain")
    out = install(repo)
    assert out.returncode != 0 and "not valid JSON" in out.stdout + out.stderr and "Traceback" not in out.stderr
    assert git(repo, "status", "--porcelain") == before


# ------------------------------------------------------------ what an existing repo already has


def test_the_kit_workflow_does_not_collide_with_a_workflow_you_already_have(tmp_path):
    own = "name: tests\non: push\njobs: {}\n"
    r = bare(tmp_path, {"requirements.txt": "", ".github/workflows/tests.yml": own})
    out = install(r, "--ci")
    assert out.returncode == 0 and "CONFLICT" not in out.stdout, out.stdout
    assert (r / ".github/workflows/tests.yml").read_text() == own                 # yours, untouched
    kit = (r / WORKFLOW).read_text()
    assert kit.startswith("# Testing kit CI") and "\nname: testing-kit\n" in kit and "  all-green:" in kit


def test_the_workflow_an_older_kit_wrote_is_replaced_by_the_new_file(repo):
    (repo / ".claude/testing-kit/manifest.json").unlink()              # an install from before 0.4.0
    old = repo / ".github/workflows/tests.yml"
    old.parent.mkdir(parents=True)
    old.write_text("# Testing kit CI for Python projects. Pin every action to a full commit SHA.\nname: tests\n")
    out = install(repo, "--ci")
    assert out.returncode == 0 and not old.exists() and (repo / WORKFLOW).exists(), out.stdout
    assert "tests.yml" in out.stdout and "testing-kit.yml" in out.stdout


def set_default_branch(repo: Path, name: str) -> None:
    """Make `repo` look like a clone of a repository whose default branch is `name`."""
    git(repo, "branch", "-m", "main", name)
    git(repo, "update-ref", f"refs/remotes/origin/{name}", name)
    git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{name}")


def test_a_default_branch_that_is_not_main_is_used_in_the_workflow_and_the_skills(repo):
    set_default_branch(repo, "trunk")
    assert install(repo, "--ci").returncode == 0
    assert "\n    branches: [trunk]\n" in (repo / WORKFLOW).read_text()
    mutation = utf8(repo / ".claude/skills/mutation-check/SKILL.md")
    assert "git diff --name-only origin/trunk...HEAD" in mutation and "origin/main" not in mutation
    review = utf8(repo / ".claude/skills/test-review/SKILL.md")
    assert "use origin/trunk" in review and "origin/main" not in review


def test_when_the_default_branch_is_unknown_the_workflow_covers_both_usual_names(tmp_path):
    r = bare(tmp_path, {"requirements.txt": ""})                       # no git here, so nothing to ask
    assert install(r, "--ci").returncode == 0
    assert "\n    branches: [main, master]\n" in (r / WORKFLOW).read_text()
    assert "origin/main...HEAD" in utf8(r / ".claude/skills/mutation-check/SKILL.md")


def test_codeowners_goes_where_the_repo_already_keeps_it(tmp_path):
    r = bare(tmp_path, {"requirements.txt": "", "CODEOWNERS": "* @everyone\n"})
    out = install(r, "--ci", "--owner", "team")
    assert out.returncode == 0
    assert not (r / ".github/CODEOWNERS").exists()                     # GitHub would read it instead of the root file
    assert (r / "CODEOWNERS").read_text() == "* @everyone\n"
    assert "@team" in (r / "CODEOWNERS.kit-new").read_text()
    assert re.search(r"^\s+CONFLICT\s+CODEOWNERS\b", out.stdout, re.M), out.stdout


def test_the_installer_warns_when_the_target_is_not_the_root_of_a_git_repository(repo, tmp_path):
    sub = repo / "services/api"
    sub.mkdir(parents=True)
    (sub / "requirements.txt").write_text("")
    out = install(sub)
    assert out.returncode == 0 and "WARNING" in out.stdout and "is inside the git repository" in out.stdout
    plain = bare(tmp_path, {"requirements.txt": ""})
    assert "is not a git repository" in install(plain).stdout
    assert "WARNING" not in install(repo).stdout


def test_install_and_check_say_which_test_files_are_recognised(repo, tmp_path):
    assert "Test files recognised: 1 (tests/test_calc.py)" in install(repo).stdout
    assert "test files recognised: 1 (tests/test_calc.py)" in installer("--check", str(repo)).stdout
    r = bare(tmp_path, {"Makefile": "test:\n\ttrue\n", "checks/pricing.check": "total 5\n"})
    out = install(r, "--fast", "make test")
    assert "No test files are recognised" in out.stdout and "extra_test_globs" in out.stdout
    set_config(r, extra_test_globs=["checks/**"])
    assert "test files recognised: 1 (checks/pricing.check)" in installer("--check", str(r)).stdout


def test_bytecode_and_installed_packages_are_not_counted_as_the_repos_tests(repo):
    for rel in ("tests/__pycache__/test_calc.cpython-313-pytest-9.2.0.pyc", "node_modules/left-pad/test/pad.test.js",
                "env/lib/python3.13/site-packages/attr/tests/test_attr.py"):     # none of them ignored in this repo
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("")
    assert "test files recognised: 1 (tests/test_calc.py)" in installer("--check", str(repo)).stdout


# ------------------------------------------------------------ any test command, however it is written


def load_installer():
    spec = importlib.util.spec_from_file_location("kit_installer", KIT / "install.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fast_tier_step(repo: Path) -> list:
    """The lines of the workflow's fast-tier `run: |` block."""
    lines = (repo / WORKFLOW).read_text().splitlines()
    start = lines.index("      - name: Fast tier")
    assert lines[start + 1] == "        run: |"
    body = []
    for line in lines[start + 2:]:
        if not line.startswith(" " * 10):
            break
        body.append(line[10:])
    return body


TRICKY = """go test -run 'Test"A": b' ./... # `x` {{.Dir}} C:\\dir"""


def test_a_command_with_quotes_and_other_shell_punctuation_is_kept_exactly(tmp_path):
    r = bare(tmp_path, {"go.mod": "module example.com/x\n"})
    out = install(r, "--ci", "--fast", TRICKY, "--setup", """echo "it's: fine" """)
    assert out.returncode == 0, out.stdout + out.stderr              # used to stop with a JSON error
    cfg = config(r)
    assert cfg["commands"]["fast"] == TRICKY and cfg["commands"]["setup"] == """echo "it's: fine\""""
    assert fast_tier_step(r) == [TRICKY]
    assert f"``{TRICKY}``" in (r / "CLAUDE.md").read_text()          # two backticks, because the command has one
    again = install(r)                                               # and it reads back as the same command
    assert again.returncode == 0 and "Up to date" in again.stdout, again.stdout


def test_a_command_of_several_lines_is_written_as_several_lines(tmp_path):
    r = bare(tmp_path, {"Makefile": "lint:\n\ttrue\ntest:\n\ttrue\n"})
    assert install(r, "--ci", "--fast", "make lint\nmake test\n", "--full", "make test-all").returncode == 0
    assert config(r)["commands"]["fast"] == "make lint\nmake test"
    assert fast_tier_step(r) == ["make lint", "make test"]
    md = (r / "CLAUDE.md").read_text()
    assert "done):\n\n  ```sh\n  make lint\n  make test\n  ```\n- Full tier: `make test-all`\n" in md
    check = installer("--check", str(r))
    assert "shows another fast command" not in check.stdout and "runs another fast command" not in check.stdout


def test_the_command_check_does_not_mistake_pytest_markers_or_shell_syntax_for_a_missing_program(repo, monkeypatch):
    inst = load_installer()
    monkeypatch.setattr(inst.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("pytest", "python3") else None)
    started = []
    monkeypatch.setattr(inst.subprocess, "run", lambda cmd, **kw: started.append(cmd) or SimpleNamespace(returncode=1))
    for command in ('pytest -m "not slow" -q', "CI=1 pytest -q", "cd backend && pytest", ". .venv/bin/activate && pytest",
                    "(cd api; make test)", "pytest -q  # the fast subset", ""):
        assert inst.fast_command_problems(command, repo) == [], command
    assert started == []                                               # none of those needed a look inside Python
    assert "`vitest` (from commands.fast) is not on PATH" in inst.fast_command_problems("vitest run", repo)[0]
    assert "pytest is not installed for `python3`" in inst.fast_command_problems("python3 -m pytest -q", repo)[0]
    assert "`./scripts/test.sh` (from commands.fast) does not exist" in inst.fast_command_problems("./scripts/test.sh -x", repo)[0]
    (repo / "run_tests.py").write_text("")
    if os.name != "nt":
        assert "is not executable" in inst.fast_command_problems("./run_tests.py", repo)[0]
        (repo / "run_tests.py").chmod(0o755)
    assert inst.fast_command_problems("./run_tests.py", repo) == []    # found from the repo, wherever --check is run from
    # On Windows a backslash is part of the path, with or without quotes around it
    assert inst.split_command(r".venv\Scripts\python.exe -m pytest", windows=True) == [r".venv\Scripts\python.exe", "-m", "pytest"]
    assert inst.split_command(r'''"C:\Program Files\py.exe" -m pytest -k "a or b"''', windows=True) == [
        r"C:\Program Files\py.exe", "-m", "pytest", "-k", "a or b"]
    assert inst.split_command(r"""sh -c 'make test' a\ b""", windows=False) == ["sh", "-c", "make test", "a b"]


def test_check_accepts_a_command_that_starts_with_a_shell_builtin(repo):
    set_config(repo, commands={"fast": f"cd . && {PYTEST} --junitxml=.reports/junit.xml"})
    out = installer("--check", str(repo))
    assert out.returncode == 0 and "Testing kit check: OK" in out.stdout, out.stdout


def test_check_says_when_claude_md_or_the_workflow_no_longer_show_your_command(repo):
    assert install(repo, "--ci").returncode == 0
    out = installer("--check", str(repo))
    assert "another fast command" not in out.stdout
    set_config(repo, commands={"fast": f"{PYTEST} --junitxml=.reports/junit.xml tests"})    # edited by hand
    out = installer("--check", str(repo))
    assert out.returncode == 0
    assert "CLAUDE.md's Testing block shows another fast command" in out.stdout
    assert ".github/workflows/testing-kit.yml runs another fast command" in out.stdout
    assert install(repo).returncode == 0                                # re-running the installer brings both in line
    assert "another fast command" not in installer("--check", str(repo)).stdout
    assert fast_tier_step(repo) == [f"{PYTEST} --junitxml=.reports/junit.xml tests"]


def test_an_install_without_ci_says_that_the_binding_checks_are_missing(tmp_path):
    r = bare(tmp_path, {"requirements.txt": ""})
    assert "No CI workflow was installed" in install(r).stdout
    out = install(r, "--ci")
    assert "No CI workflow was installed" not in out.stdout and "`all-green` a required check" in out.stdout


def test_broken_settings_stop_the_install_before_anything_changes(tmp_path):
    r = bare(tmp_path, {"requirements.txt": "", ".claude/settings.json": "{ not json"})
    out = install(r, "--ci")
    assert out.returncode != 0 and "not valid JSON" in out.stdout + out.stderr and "Traceback" not in out.stderr
    left = sorted(p.relative_to(r).as_posix() for p in r.rglob("*") if p.is_file())
    assert left == [".claude/settings.json", "requirements.txt"]


# ------------------------------------------------------------ upkeep: upgrade, options, check, uninstall


@pytest.fixture
def newer_kit(tmp_path: Path) -> Path:
    """A copy of the kit that stands in for the next release: one rule and one skill have changed."""
    kit = tmp_path / "newer-kit"
    shutil.copytree(KIT, kit, ignore=shutil.ignore_patterns(".venv", ".git", "__pycache__", ".pytest_cache", "tests"))
    (kit / "VERSION").write_text("99.0.0\n")
    for rel in ("templates/project/.claude/rules/testing.md", "templates/project/.claude/skills/run-tests/SKILL.md"):
        with open(kit / rel, "a") as fh:
            fh.write("\nA line added by the next release.\n")
    return kit


def test_upgrade_replaces_files_you_have_not_touched_and_keeps_the_ones_you_have(repo, newer_kit):
    skill = repo / ".claude/skills/run-tests/SKILL.md"
    skill.write_text(utf8(skill) + "\nOur own house rule.\n", encoding="utf-8")
    cfg_before = (repo / ".claude/testing-kit.json").read_text()
    out = installer("--project", str(repo), kit=newer_kit)
    assert out.returncode == 0 and "upgrading from" in out.stdout, out.stdout
    assert "next release" in utf8(repo / ".claude/rules/testing.md")                  # untouched: updated in place
    assert not (repo / ".claude/rules/testing.md.kit-new").exists()
    assert "Our own house rule." in utf8(skill) and "next release" not in utf8(skill)
    assert "next release" in utf8(repo / ".claude/skills/run-tests/SKILL.md.kit-new")
    assert (repo / ".claude/testing-kit.json").read_text() == cfg_before               # your config is never rewritten
    assert manifest(repo)["version"] == "99.0.0"
    # merging by hand and re-running clears the leftover
    skill.write_text(utf8(repo / ".claude/skills/run-tests/SKILL.md.kit-new"), encoding="utf-8")
    out = installer("--project", str(repo), kit=newer_kit)
    assert not (repo / ".claude/skills/run-tests/SKILL.md.kit-new").exists() and "CONFLICT" not in out.stdout


def test_kit_scripts_are_upgraded_as_a_set_and_one_you_changed_is_saved_beside_the_new_one(repo, newer_kit):
    for name in ("kitlib.py", "tests_on_stop.py"):                     # the next release changes two scripts together
        with open(newer_kit / "templates/project/.claude/testing-kit" / name, "a") as fh:
            fh.write("# next release\n")
    kitlib_path = repo / ".claude/testing-kit/kitlib.py"
    kitlib_path.write_text(kitlib_path.read_text() + "# our local patch\n")
    out = installer("--project", str(repo), kit=newer_kit)
    assert out.returncode == 0 and "REPLACED" in out.stdout and "kitlib.py.yours" in out.stdout, out.stdout
    assert "# next release" in kitlib_path.read_text() and "our local patch" not in kitlib_path.read_text()
    assert "# next release" in (repo / ".claude/testing-kit/tests_on_stop.py").read_text()
    assert "# our local patch" in (repo / ".claude/testing-kit/kitlib.py.yours").read_text()
    assert not (repo / ".claude/testing-kit/kitlib.py.kit-new").exists()
    check = installer("--check", str(repo), kit=newer_kit)
    assert check.returncode == 0 and "kitlib.py.yours" in check.stdout
    again = installer("--project", str(repo), kit=newer_kit)             # nothing is replaced twice
    assert "REPLACED" not in again.stdout and "# our local patch" in (repo / ".claude/testing-kit/kitlib.py.yours").read_text()


def test_an_install_from_before_0_4_0_gets_its_scripts_replaced_and_its_texts_kept(repo):
    (repo / ".claude/testing-kit/manifest.json").unlink()              # earlier versions kept no install record
    kitlib_path = repo / ".claude/testing-kit/kitlib.py"
    kitlib_path.write_text("# kitlib from an older kit\n")
    rules = repo / ".claude/rules/testing.md"
    rules.write_text("older rules, or yours\n")
    out = install(repo)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "def tree_fingerprint" in kitlib_path.read_text()            # one old script would break the new ones
    assert not list((repo / ".claude/testing-kit").glob("kitlib.py.*"))
    assert rules.read_text() == "older rules, or yours\n" and (repo / ".claude/rules/testing.md.kit-new").exists()
    assert "before 0.4.0" in out.stdout and "--force" in out.stdout
    assert (repo / ".claude/testing-kit/manifest.json").exists()
    assert decision(start(repo)) == "allow" and decision(stop(repo)) == "allow"       # the hooks run as a set


def test_a_run_that_changes_nothing_says_so_instead_of_listing_next_steps(repo):
    first = install(repo)                                              # brings CLAUDE.md in line with the fixture's command
    assert "Next steps:" in first.stdout
    again = install(repo)
    assert again.returncode == 0 and "Up to date" in again.stdout and "Next steps:" not in again.stdout


def test_force_takes_the_kit_version_of_a_changed_file_but_keeps_your_config(repo):
    rules = repo / ".claude/rules/testing.md"
    rules.write_text("mine\n")
    set_config(repo, high_paths=["src/calc/**"])
    assert install(repo, "--force").returncode == 0
    assert "Never game the suite" in utf8(rules)
    assert config(repo)["high_paths"] == ["src/calc/**"] and "no:cacheprovider" in config(repo)["commands"]["fast"]


def test_profile_and_options_are_remembered_and_can_be_changed(tmp_path):
    r = bare(tmp_path, {"requirements.txt": ""})
    assert install(r, "--profile", "strict", "--ci", "--owner", "@team").returncode == 0
    assert config(r)["enforcement"] == "deny" and config(r)["default_tier"] == "medium"
    out = install(r)                                                   # a plain re-run changes nothing
    assert "strict profile" in out.stdout and "Options kept from the last install" in out.stdout
    assert manifest(r)["options"] == {"profile": "strict", "ci": True, "env": False, "owner": "@team"}
    assert (r / WORKFLOW).exists() and (r / ".github/CODEOWNERS").exists()
    # change one workflow by hand, then turn CI off: the untouched files go, the changed one stays
    flake = r / ".github/workflows/flake-finder.yml"
    flake.write_text(flake.read_text() + "# ours\n")
    out = install(r, "--no-ci", "--profile", "standard")
    assert not (r / WORKFLOW).exists() and not (r / ".github/CODEOWNERS").exists()
    assert flake.exists() and "you changed it" in out.stdout
    assert config(r)["enforcement"] == "ask" and config(r)["default_tier"] == "low"


def test_profile_downgrade_removes_the_extras_you_have_not_changed(repo):
    agent = repo / ".claude/agents/test-reviewer.md"
    agent.write_text(utf8(agent) + "\nOur own lens.\n", encoding="utf-8")
    assert install(repo, "--profile", "minimal").returncode == 0
    assert not (repo / ".claude/skills").exists() and not (repo / ".claude/testing-kit/tests_on_stop.py").exists()
    assert agent.exists() and not (repo / ".claude/agents/spec-test-writer.md").exists()
    assert config(repo)["stop_hook"]["enabled"] is False
    assert installer("--check", str(repo)).returncode == 0


def test_your_own_hook_in_a_group_shared_with_the_kit_survives_a_reinstall(repo):
    path = repo / ".claude/settings.json"
    settings = json.loads(path.read_text())
    settings["hooks"]["PreToolUse"][0]["hooks"].append({"type": "command", "command": "echo mine"})
    settings["hooks"]["PreCompact"] = [{"hooks": [{"type": "command", "command": "echo compact"}]}]
    path.write_text(json.dumps(settings, indent=2))
    assert install(repo).returncode == 0
    assert "echo mine" in hook_commands(repo, "PreToolUse") and hook_commands(repo, "PreCompact") == ["echo compact"]
    assert sum("protect_tests.py" in c for c in hook_commands(repo, "PreToolUse")) == 1


def test_check_shows_the_version_what_you_changed_and_a_missing_hook_script(repo, newer_kit):
    out = installer("--check", str(repo))
    assert out.returncode == 0 and f"installed: testing kit {(KIT / 'VERSION').read_text().strip()}, standard profile" in out.stdout
    assert "this installer is 99.0.0" in installer("--check", str(repo), kit=newer_kit).stdout
    skill = repo / ".claude/skills/run-tests/SKILL.md"
    skill.write_text(utf8(skill) + "\nOurs.\n", encoding="utf-8")
    out = installer("--check", str(repo))
    assert out.returncode == 0 and "changed since the install" in out.stdout and "run-tests/SKILL.md" in out.stdout
    (repo / ".claude/testing-kit/tests_on_stop.py").unlink()
    out = installer("--check", str(repo))
    assert out.returncode == 1 and "tests_on_stop.py is registered as a hook but the file is missing" in out.stdout
    assert git(repo, "status", "--porcelain").count("\n") == 2          # the check itself leaves nothing behind


def test_check_run_times_the_fast_tier_and_notices_a_missing_report(repo):
    out = installer("--check", str(repo), "--run")
    assert out.returncode == 0, out.stdout
    assert "fast tier ran in" in out.stdout and "JUnit report at .reports/junit.xml: 2 tests" in out.stdout
    set_config(repo, commands={"fast": PYTEST})
    out = installer("--check", str(repo), "--run")
    assert out.returncode == 1 and "wrote no JUnit report" in out.stdout
    add_bug(repo)
    set_config(repo, junit_path="")
    out = installer("--check", str(repo), "--run")
    assert out.returncode == 1 and "the fast tier fails here" in out.stdout and "test_add" in out.stdout


def test_uninstall_gives_back_the_repo_as_it_was(tmp_path):
    r = bare(tmp_path, {"requirements.txt": "", "CLAUDE.md": "# Project\n\nExisting notes.\n", ".gitignore": "*.log\n"})
    own = {"permissions": {"allow": ["Bash(make *)"], "deny": ["Read(./.env)"]},
           "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "say done"}]}]}}
    (r / ".claude").mkdir()
    (r / ".claude/settings.json").write_text(json.dumps(own, indent=2) + "\n")
    assert install(r, "--ci", "--env").returncode == 0
    skill = r / ".claude/skills/run-tests/SKILL.md"
    skill.write_text(utf8(skill) + "\nOurs.\n", encoding="utf-8")
    (r / ".claude/testing-kit/.state").mkdir()
    (r / ".claude/testing-kit/.state/s1.base").write_text("x")

    dry = installer("--uninstall", str(r), "--dry-run")
    assert dry.returncode == 0 and "(dry run)" in dry.stdout and (r / ".claude/testing-kit/kitlib.py").exists()

    out = installer("--uninstall", str(r))
    assert out.returncode == 0 and "Restart any running Claude Code session" in out.stdout, out.stdout
    assert json.loads((r / ".claude/settings.json").read_text()) == own            # your deny rule was yours: kept
    assert (r / "CLAUDE.md").read_text() == "# Project\n\nExisting notes.\n"
    assert skill.exists() and "you changed it" in out.stdout
    left = sorted(p.relative_to(r).as_posix() for p in r.rglob("*") if p.is_file())
    assert left == [".claude/settings.json", ".claude/skills/run-tests/SKILL.md", ".gitignore", "CLAUDE.md", "requirements.txt"]
    assert installer("--uninstall", str(r)).returncode == 0                        # running it again is harmless


def test_your_settings_keep_their_characters_and_indentation(tmp_path):
    r = bare(tmp_path, {"requirements.txt": ""})
    own = {"hooks": {"PreCompact": [{"hooks": [{"type": "command", "command": "echo '⚠️ run /handoff — now'"}]}]}}
    own_text = json.dumps(own, indent=4, ensure_ascii=False) + "\n"
    (r / ".claude").mkdir()
    (r / ".claude/settings.json").write_text(own_text, encoding="utf-8")
    assert install(r).returncode == 0
    merged = (r / ".claude/settings.json").read_text(encoding="utf-8")
    assert "⚠️ run /handoff — now" in merged and "\\u26a0" not in merged          # not turned into \u escapes
    assert '\n    "hooks": {\n        "PreCompact": [' in merged                  # still indented by four
    assert installer("--uninstall", str(r)).returncode == 0
    assert (r / ".claude/settings.json").read_text(encoding="utf-8") == own_text


def test_uninstall_removes_the_files_the_kit_created(tmp_path):
    r = bare(tmp_path, {"requirements.txt": ""})
    assert install(r).returncode == 0
    assert installer("--uninstall", str(r)).returncode == 0
    left = sorted(p.relative_to(r).as_posix() for p in r.rglob("*") if p.is_file())
    assert left == [".gitignore", "requirements.txt"]


def test_the_guide_is_installed_with_the_other_docs(repo):
    text = utf8(repo / "docs/testing/KIT-GUIDE.md")
    assert "## Upkeep" in text and "--uninstall" in text


def test_nothing_the_kit_installs_names_the_authors_own_people_or_projects(tmp_path):
    r = bare(tmp_path, {"requirements.txt": ""})
    assert install(r, "--ci", "--env", "--owner", "@team").returncode == 0
    found = {}
    for path in sorted(p for p in r.rglob("*") if p.is_file()):
        lines = lines_with_private_words(path.read_text(encoding="utf-8", errors="replace"))
        if lines:
            found[path.relative_to(r).as_posix()] = lines
    assert not found, f"files and the lines that name them: {found}"


# ------------------------------------------------------------ text that is not ASCII, pipes that are not UTF-8


CODE_PAGE = "cp1252"                              # what Python gives a pipe on a western Windows; forced here on every OS
TESTS_RU = "\u0442\u0435\u0441\u0442\u044b"            # "tests" in Cyrillic: no place in that code page
CHECKS_RU = "\u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438"  # "checks"


def escaped(text: str) -> str:
    """How Python shows characters a pipe can't carry: \\uXXXX."""
    return text.encode("ascii", "backslashreplace").decode("ascii")


def piped(repo: Path, script: str, *args: str, payload=None):
    """Run a kit script the way it runs on a Windows machine: its pipes use the code page, while the hook
    input Claude Code sends is UTF-8 all the same. Returns (exit code, stdout, stderr)."""
    path = KIT / script if script == "install.py" else repo / ".claude/testing-kit" / script
    sent = b"" if payload is None else json.dumps({"cwd": str(repo), "session_id": "test", **payload},
                                                  ensure_ascii=False).encode("utf-8")
    proc = subprocess.run([sys.executable, str(path), *args], cwd=repo, input=sent, capture_output=True,
                          env={**ENV, "CLAUDE_PROJECT_DIR": str(repo), "PYTHONIOENCODING": CODE_PAGE})
    out, err = (data.decode(CODE_PAGE, "replace").replace("\r\n", "\n") for data in (proc.stdout, proc.stderr))
    return proc.returncode, out, err


def commit_any_name(repo: Path, message: str) -> None:
    """Commit without reading what git prints: it names files in UTF-8, whatever this machine's encoding is."""
    for args in (["add", "-A"], ["commit", "-qm", message]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def test_a_hook_reads_what_claude_code_sends_as_utf8_whatever_the_pipe_encoding_is(repo):
    shout = repo / "tests/test_shout.py"
    shout.write_text('def test_shout():\n    assert "Jos\u00e9".upper() == "JOS\u00c9"\n', encoding="utf-8")
    commit(repo, "a test with accents in it")

    def edit_as_sent(old: str, new: str) -> str:
        code, out, err = piped(repo, "protect_tests.py", payload={"tool_name": "Edit", "tool_input": {
            "file_path": str(shout), "old_string": old, "new_string": new}})
        return decision((code, json.loads(out) if out.strip() else None, err))

    # Read in the code page, the accent came out as two other characters: the hook didn't find the old text
    # in the file, took the edit for one that fails by itself, and let it through.
    assert edit_as_sent('== "JOS\u00c9"', '== "JOSE"') == "ask"
    # A closing curly quote has no place in the code page at all: the whole input was unreadable, nothing was checked.
    assert edit_as_sent("def test_shout():",
                        "import pytest\n\n\n@pytest.mark.skip(reason=\u201cflaky\u201d)\ndef test_shout():") == "ask"


def test_the_run_report_shows_a_test_name_the_pipe_cannot_carry(repo):
    (repo / "junit.xml").write_text(f'<testsuite><testcase classname="t" name="test_{TESTS_RU}">'
                                    '<failure message="boom"/></testcase></testsuite>', encoding="utf-8")
    code, out, err = piped(repo, "test_report.py", "junit.xml")
    assert code == 1 and "Traceback" not in err, out + err             # used to stop with UnicodeEncodeError
    assert f"t::test_{escaped(TESTS_RU)}" in out


def test_the_installer_lists_a_test_file_whose_name_the_pipe_cannot_carry(repo):
    (repo / f"tests/test_{TESTS_RU}.py").write_text("def test_price():\n    assert 2 * 3 == 6\n")
    code, out, err = piped(repo, "install.py", "--project", str(repo))
    assert code == 0 and "Traceback" not in err, out + err
    assert f"Test files recognised: 2 (tests/test_calc.py, tests/test_{escaped(TESTS_RU)}.py)" in out


def test_the_exit_code_gate_shows_runner_output_that_is_in_another_encoding(repo):
    (repo / "tools").mkdir()
    (repo / "tools/odd_runner.py").write_text(        # a byte that is neither UTF-8 nor in the code page
        "import os, sys\nsys.stdout.buffer.write(b'price \\x81 is wrong\\n')\nsys.exit(1 if os.path.exists('BROKEN') else 0)\n")
    set_config(repo, junit_path="", commands={"fast": f'"{sys.executable}" tools/odd_runner.py'})
    commit(repo, "a runner that prints in its own encoding")
    branch(repo)
    (repo / "BROKEN").write_text("")
    commit(repo, "break it")
    code, out, err = piped(repo, "base_tests.py", "--base", "main")
    assert code == 1 and "Traceback" not in err, out + err
    assert "price \\ufffd is wrong" in out and "This branch's code fails the base's tests" in out


def test_the_gates_work_with_file_names_and_patterns_that_are_not_ascii(repo):
    """Git answers in UTF-8 on every system. Read in a Windows code page, a file name or a pattern from the
    committed config came out as other characters. (Only a Windows machine can fail this for that reason;
    everywhere it checks that such names work and are shown.)"""
    cfg = config(repo)
    cfg["extra_test_globs"] = [f"{CHECKS_RU}/**"]                      # a folder only the config calls tests
    (repo / ".claude/testing-kit.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    (repo / CHECKS_RU).mkdir()
    (repo / CHECKS_RU / "pricing.txt").write_text("total 5\n")
    named = repo / f"tests/test_{TESTS_RU}.py"
    named.write_text("from calc import add\n\n\ndef test_price():\n    assert add(2, 2) == 4\n")
    commit_any_name(repo, "tests and patterns with names that are not ASCII")
    branch(repo)
    (repo / CHECKS_RU / "pricing.txt").unlink()
    src = repo / "src/calc/__init__.py"
    src.write_text(src.read_text().replace("return a + b", "return a + b + 1"))
    named.write_text(named.read_text().replace("== 4", "== 5"))
    commit_any_name(repo, "a bug, the test edited to match, and a check deleted")
    code, out, err = piped(repo, "test_diff_guard.py", "--base", "main")
    assert code == 1 and f"test file deleted: {escaped(CHECKS_RU)}/pricing.txt" in out, out + err
    code, out, err = piped(repo, "base_tests.py", "--base", "main")
    assert code == 1 and f"NOW FAILING  tests.test_{escaped(TESTS_RU)}::test_price" in out, out + err
