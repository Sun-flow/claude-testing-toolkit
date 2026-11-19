"""The shell guards follow the edit hook's rule: the base branch's tests are protected, tests that are new on
the current branch are work in progress. And because the base branch decides which tests are protected,
git commands that move it, or take the branch back behind it, ask first.
"""
import json

import pytest

from conftest import decision, git, run_hook
from test_branch_tests import MINE, MINE_V1, branch, commit_all, edit, set_config  # noqa: F401
from test_improvement_pass import load_kitlib

TEST_FILE = "tests/test_calc.py"


def bash(repo, command):
    return run_hook(repo, "guard_bash.py", {"tool_name": "Bash", "tool_input": {"command": command}})


def audit(repo, mode, call="c1"):
    return run_hook(repo, "bash_audit.py", {"tool_name": "Bash", "tool_use_id": call,
                                            "tool_input": {"command": "true"}}, mode)


@pytest.fixture
def later_test(repo):
    """`main` gains a second test file after the kit's install, then a work branch starts from it."""
    set_config(repo, base_branch="main")
    (repo / "tests" / "test_later.py").write_text(MINE_V1)
    commit_all(repo, "a later test on main")
    git(repo, "checkout", "-q", "-b", "work")
    return repo


class TestShellCommandsOnTestsNewOnTheBranch:
    @pytest.mark.parametrize("committed", [False, True])
    def test_deleting_a_test_file_the_branch_wrote_is_allowed(self, branch, committed):
        (branch / MINE).write_text(MINE_V1)
        if committed:
            commit_all(branch)
        assert decision(bash(branch, f"rm {MINE}")) == "allow"

    def test_moving_a_test_file_the_branch_wrote_is_allowed(self, branch):
        (branch / MINE).write_text(MINE_V1)
        assert decision(bash(branch, f"git mv {MINE} tests/test_renamed.py")) == "allow"

    def test_deleting_a_test_file_the_base_has_still_asks(self, branch):
        assert decision(bash(branch, f"rm {TEST_FILE}")) == "ask"

    def test_moving_a_new_test_file_onto_one_the_base_has_asks(self, branch):
        (branch / MINE).write_text(MINE_V1)
        assert decision(bash(branch, f"mv {MINE} {TEST_FILE}")) == "ask"

    def test_deleting_a_folder_that_holds_base_tests_asks(self, branch):
        assert decision(bash(branch, "rm -rf tests")) == "ask"

    def test_deleting_a_folder_that_holds_only_the_branchs_tests_is_allowed(self, branch):
        (branch / "tests" / "new_area").mkdir()
        (branch / "tests" / "new_area" / "test_mine.py").write_text(MINE_V1)
        assert decision(bash(branch, "rm -rf tests/new_area")) == "allow"

    def test_an_unknown_base_keeps_a_new_test_file_protected_from_the_shell(self, repo):
        (repo / MINE).write_text(MINE_V1)
        assert decision(bash(repo, f"rm {MINE}")) == "ask"

    def test_harness_files_new_on_the_branch_stay_protected(self, branch):
        (branch / "tests" / "new_area").mkdir()
        (branch / "tests" / "new_area" / "conftest.py").write_text("import pytest\n")
        assert decision(bash(branch, "rm tests/new_area/conftest.py")) == "ask"


class TestAuditAfterAShellCommand:
    def test_a_command_that_changed_a_test_new_on_the_branch_is_not_reported(self, branch):
        (branch / MINE).write_text(MINE_V1)
        audit(branch, "pre")
        (branch / MINE).write_text(MINE_V1.replace("== 8", "== 7"))
        assert decision(audit(branch, "post")) == "allow"

    def test_a_command_that_changed_a_test_the_base_has_is_reported(self, branch):
        audit(branch, "pre")
        path = branch / TEST_FILE
        path.write_text(path.read_text().replace("== 5", "== 6"))
        assert decision(audit(branch, "post")) == "block"

    def test_with_an_unknown_base_a_changed_new_test_is_reported(self, repo):
        (repo / MINE).write_text(MINE_V1)
        audit(repo, "pre")
        (repo / MINE).write_text(MINE_V1.replace("== 8", "== 7"))
        assert decision(audit(repo, "post")) == "block"


class TestMovingTheBaseBranch:
    """Moving the base branch back would turn tests it has into "new on this branch"."""

    @pytest.mark.parametrize("command", [
        "git branch -f main main~1",
        "git branch --force main main~1",
        "git branch -D main",
        "git branch -m main old-main",
        "git update-ref refs/heads/main main~1",
        "git symbolic-ref refs/remotes/origin/HEAD refs/remotes/origin/other",
        "git remote set-head origin other",
        "git fetch . main~1:main",
        "git fetch origin +old:refs/heads/main",
        "git push . main~1:main --force",
        "git -C . branch -f main main~1",
        "cd src && git branch -f main main~1",
    ])
    def test_a_command_that_moves_the_base_branch_asks(self, later_test, command):
        assert decision(bash(later_test, command)) == "ask"

    @pytest.mark.parametrize("command", [
        "git branch -f scratch main~1",
        "git branch --list main",
        "git branch -vv",
        "git branch feature main",
        "git fetch origin",
        "git fetch origin main",
        "git pull origin main",
        "git push origin work",
        "git symbolic-ref --short HEAD",
        "git symbolic-ref refs/remotes/origin/HEAD",
        "git checkout -b another",
        "git switch -c another",
    ])
    def test_everyday_git_commands_do_not_ask(self, later_test, command):
        assert decision(bash(later_test, command)) == "allow"

    def test_resetting_the_base_branch_through_checkout_asks(self, later_test):
        assert decision(bash(later_test, "git checkout -B main main~1")) == "ask"
        assert decision(bash(later_test, "git switch -C main main~1")) == "ask"

    def test_the_edit_the_move_would_have_unlocked_asks_before_it(self, later_test):
        # the reason for the guard: with main moved back one commit, this edit would be allowed
        assert decision(edit(later_test, "tests/test_later.py", "== 8", "== 7")) == "ask"
        git(later_test, "branch", "-f", "main", "main~1")
        assert decision(edit(later_test, "tests/test_later.py", "== 8", "== 7")) == "allow"


class TestResettingBehindTheBase:
    def test_a_reset_to_before_the_branch_left_the_base_asks(self, later_test):
        # a soft or mixed reset keeps tests/test_later.py on disk while HEAD no longer has it
        assert decision(bash(later_test, "git reset --soft HEAD~1")) == "ask"
        assert decision(bash(later_test, "git reset main~1")) == "ask"

    def test_undoing_the_branchs_own_commit_is_allowed(self, later_test):
        (later_test / "notes.txt").write_text("x\n")
        commit_all(later_test)
        assert decision(bash(later_test, "git reset --soft HEAD~1")) == "allow"

    def test_a_reset_to_the_base_branch_itself_is_allowed(self, later_test):
        assert decision(bash(later_test, "git reset --hard main")) == "allow"

    def test_a_reset_with_no_commit_is_allowed(self, later_test):
        assert decision(bash(later_test, "git reset --hard")) == "allow"
        assert decision(bash(later_test, "git reset")) == "allow"

    def test_unstaging_a_file_is_not_a_reset_behind_the_base(self, later_test):
        (later_test / "notes.txt").write_text("x\n")
        git(later_test, "add", "notes.txt")
        assert decision(bash(later_test, "git reset notes.txt")) == "allow"
        assert decision(bash(later_test, "git reset -- notes.txt")) == "allow"

    def test_with_no_base_branch_known_a_reset_does_not_ask(self, repo):
        # every test on disk is protected then, so moving HEAD unlocks nothing
        assert decision(bash(repo, "git reset --soft HEAD~1")) == "allow"


class TestCopying:
    def test_copying_a_base_test_to_a_new_file_does_not_ask(self, branch):
        # the source is only read
        assert decision(bash(branch, f"cp {TEST_FILE} tests/test_calc_copy.py")) == "allow"

    def test_copying_over_a_base_test_asks(self, branch):
        (branch / MINE).write_text(MINE_V1)
        assert decision(bash(branch, f"cp {MINE} {TEST_FILE}")) == "ask"

    def test_copying_into_a_named_target_folder_checks_the_folder(self, branch):
        assert decision(bash(branch, f"cp -t tests src/calc/__init__.py")) == "ask"

    def test_moving_a_base_test_still_asks_about_the_source(self, branch):
        assert decision(bash(branch, f"mv {TEST_FILE} tests/test_elsewhere.py")) == "ask"


class TestPathsThatDifferOnlyInCase:
    """On a disk that ignores case, Tests/Test_Calc.py is tests/test_calc.py: the base branch has it."""

    def test_the_base_copy_is_found_under_another_spelling_when_the_disk_ignores_case(self, branch):
        kitlib = load_kitlib()
        cfg = kitlib.load_config(branch)
        files = kitlib.base_files(branch, cfg, ignore_case=True)
        assert kitlib.base_path(files, "Tests/Test_Calc.py", ignore_case=True) == TEST_FILE

    def test_another_spelling_is_another_file_when_the_disk_keeps_case(self, branch):
        kitlib = load_kitlib()
        cfg = kitlib.load_config(branch)
        files = kitlib.base_files(branch, cfg, ignore_case=False)
        assert kitlib.base_path(files, "Tests/Test_Calc.py", ignore_case=False) is None
        assert kitlib.base_path(files, TEST_FILE, ignore_case=False) == TEST_FILE
