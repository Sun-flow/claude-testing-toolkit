"""The edit hook protects the tests the base branch has, not the ones the current branch is still writing.

A test is the specification once it is on the base branch (config "base_branch", else origin's default
branch). A test file, or a test added to a file, that exists only on the working branch is work in
progress: its author may rework it without a prompt. The CI gates already compare with the merge base.
"""
import json

import pytest

from conftest import decision, git, run_hook

TEST_FILE = "tests/test_calc.py"
MINE = "tests/test_mine.py"
MINE_V1 = "from calc import add\n\n\ndef test_add_zero():\n    assert add(0, 7) == 8\n"
ADDED = "\n\ndef test_add_negative():\n    assert add(-2, -3) == -6\n"


def edit(repo, path, old, new):
    return run_hook(repo, "protect_tests.py", {"tool_name": "Edit", "tool_input": {
        "file_path": str(repo / path), "old_string": old, "new_string": new}})


def write(repo, path, content):
    return run_hook(repo, "protect_tests.py", {"tool_name": "Write", "tool_input": {
        "file_path": str(repo / path), "content": content}})


def set_config(repo, **keys):
    path = repo / ".claude" / "testing-kit.json"
    cfg = json.loads(path.read_text())
    cfg.update(keys)
    path.write_text(json.dumps(cfg, indent=2))


@pytest.fixture
def branch(repo):
    """The repo with `main` named as the base branch, and a work branch checked out from it."""
    set_config(repo, base_branch="main")
    git(repo, "commit", "-qam", "name the base branch")
    git(repo, "checkout", "-q", "-b", "work")
    return repo


def commit_all(repo, message="work"):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)


class TestTestsNewOnTheBranch:
    def test_reworking_an_uncommitted_test_file_written_on_the_branch_is_allowed(self, branch):
        (branch / MINE).write_text(MINE_V1)
        assert decision(edit(branch, MINE, "== 8", "== 7")) == "allow"

    def test_reworking_a_test_file_committed_only_on_the_branch_is_allowed(self, branch):
        (branch / MINE).write_text(MINE_V1)
        commit_all(branch)
        assert decision(edit(branch, MINE, "== 8", "== 7")) == "allow"

    def test_removing_a_test_from_a_file_that_is_new_on_the_branch_is_allowed(self, branch):
        (branch / MINE).write_text(MINE_V1 + ADDED)
        commit_all(branch)
        assert decision(write(branch, MINE, MINE_V1)) == "allow"

    def test_origins_default_branch_is_the_base_when_the_config_names_none(self, repo):
        git(repo, "update-ref", "refs/remotes/origin/main", "main")
        git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        git(repo, "checkout", "-q", "-b", "work")
        (repo / MINE).write_text(MINE_V1)
        assert decision(edit(repo, MINE, "== 8", "== 7")) == "allow"

    def test_an_unknown_base_keeps_every_test_file_on_disk_protected(self, repo):
        # no "base_branch" and no origin: the hook can't tell what is new, so it asks as before
        git(repo, "checkout", "-q", "-b", "work")
        (repo / MINE).write_text(MINE_V1)
        assert decision(edit(repo, MINE, "== 8", "== 7")) == "ask"

    def test_a_base_branch_that_does_not_exist_keeps_every_test_file_protected(self, branch):
        set_config(branch, base_branch="no-such-branch")
        (branch / MINE).write_text(MINE_V1)
        assert decision(edit(branch, MINE, "== 8", "== 7")) == "ask"


class TestTestsOnTheBaseBranch:
    def test_changing_an_assertion_the_base_has_still_asks(self, branch):
        assert decision(edit(branch, TEST_FILE, "assert add(2, 3) == 5", "assert add(2, 3) == 6")) == "ask"

    def test_deleting_a_test_the_base_has_still_asks(self, branch):
        assert decision(edit(branch, TEST_FILE, "def test_add():\n    assert add(2, 3) == 5\n", "")) == "ask"

    def test_on_the_base_branch_itself_a_committed_test_stays_protected(self, branch):
        (branch / MINE).write_text(MINE_V1)
        commit_all(branch)
        git(branch, "checkout", "-q", "main")
        git(branch, "merge", "-q", "work")
        assert decision(edit(branch, MINE, "== 8", "== 7")) == "ask"

    def test_a_test_file_merged_in_from_the_base_is_protected_on_the_branch(self, branch):
        git(branch, "checkout", "-q", "main")
        (branch / "tests" / "test_theirs.py").write_text(MINE_V1)
        commit_all(branch, "another branch's test, merged")
        git(branch, "checkout", "-q", "work")
        (branch / "notes.txt").write_text("work in progress\n")
        commit_all(branch)
        git(branch, "merge", "-q", "main")
        assert decision(edit(branch, "tests/test_theirs.py", "== 8", "== 7")) == "ask"

    def test_a_base_test_file_deleted_on_the_branch_and_written_again_stays_protected(self, branch):
        git(branch, "rm", "-q", TEST_FILE)
        git(branch, "commit", "-qm", "delete the test")
        assert decision(write(branch, TEST_FILE, "def test_add():\n    assert True\n")) == "ask"


class TestTestsAddedOnTheBranchToABaseFile:
    def with_added_test(self, repo, committed):
        path = repo / TEST_FILE
        path.write_text(path.read_text() + ADDED)
        if committed:
            commit_all(repo)

    @pytest.mark.parametrize("committed", [False, True])
    def test_reworking_a_test_the_branch_added_is_allowed(self, branch, committed):
        self.with_added_test(branch, committed)
        assert decision(edit(branch, TEST_FILE, "add(-2, -3) == -6", "add(-2, -3) == -5")) == "allow"

    def test_removing_a_test_the_branch_added_is_allowed(self, branch):
        self.with_added_test(branch, committed=True)
        assert decision(edit(branch, TEST_FILE, ADDED, "")) == "allow"

    def test_reworking_it_while_changing_a_base_line_asks(self, branch):
        self.with_added_test(branch, committed=True)
        current = (branch / TEST_FILE).read_text()
        new = current.replace("== -6", "== -5").replace("add(2, 3) == 5", "add(2, 3) == 6")
        assert decision(write(branch, TEST_FILE, new)) == "ask"

    def test_reworking_it_into_a_second_definition_of_a_base_test_asks(self, branch):
        self.with_added_test(branch, committed=True)
        assert decision(edit(branch, TEST_FILE, "def test_add_negative():", "def test_add():")) == "ask"

    def test_reworking_it_with_a_skip_marker_asks(self, branch):
        self.with_added_test(branch, committed=True)
        assert decision(edit(branch, TEST_FILE, "def test_add_negative():",
                             "@pytest.mark.skip\ndef test_add_negative():")) == "ask"
