"""Naming the base branch: the installer fills in "base_branch", --check says which branch the hooks use
(or warns that they can't tell), the CI gates run by hand use it, and a draft of a test can't be merged.
"""
import json

import pytest

from conftest import git
from test_branch_tests import commit_all, set_config
from test_ci_and_install import install, py
from test_drop_in import installer
from test_improvement_pass import load_kitlib


def plain_repo(tmp_path, default_branch="main"):
    r = tmp_path / "plain"
    (r / "tests").mkdir(parents=True)
    (r / "tests" / "test_one.py").write_text("def test_one():\n    assert 1 + 1 == 2\n")
    git(r, "init", "-q", "-b", default_branch)
    git(r, "config", "user.email", "kit@example.com")
    git(r, "config", "user.name", "kit")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    return r


def config(repo):
    return json.loads((repo / ".claude" / "testing-kit.json").read_text())


def with_origin(repo, branch="main", record_default=True):
    """Give the repo a remote-tracking branch, as a clone has."""
    git(repo, "update-ref", f"refs/remotes/origin/{branch}", "HEAD")
    if record_default:
        git(repo, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{branch}")


class TestInstallerFillsInTheBaseBranch:
    def test_a_new_install_names_origins_default_branch(self, tmp_path):
        r = plain_repo(tmp_path, "trunk")
        with_origin(r, "trunk")
        out = install(r)
        assert out.returncode == 0, out.stdout + out.stderr
        assert config(r)["base_branch"] == "origin/trunk"
        assert "base_branch origin/trunk" in out.stdout

    def test_origins_branch_is_preferred_to_the_local_one_of_the_same_name(self, tmp_path):
        r = plain_repo(tmp_path)
        with_origin(r, "main", record_default=False)  # a clone that didn't record origin's default
        install(r)
        assert config(r)["base_branch"] == "origin/main"

    def test_a_repo_with_only_a_local_main_names_that(self, tmp_path):
        r = plain_repo(tmp_path)
        install(r)
        assert config(r)["base_branch"] == "main"

    def test_a_repo_with_no_usual_branch_leaves_it_empty_and_says_so(self, tmp_path):
        r = plain_repo(tmp_path, "trunk")
        out = install(r)
        assert config(r)["base_branch"] == ""
        assert "base_branch not set" in out.stdout

    def test_a_later_run_keeps_the_base_branch_you_set(self, tmp_path):
        r = plain_repo(tmp_path)
        install(r)
        set_config(r, base_branch="origin/release")
        install(r)
        assert config(r)["base_branch"] == "origin/release"

    def test_an_upgrade_of_a_config_without_the_key_does_not_add_one(self, tmp_path):
        r = plain_repo(tmp_path)
        install(r)
        cfg = config(r)
        del cfg["base_branch"]
        (r / ".claude" / "testing-kit.json").write_text(json.dumps(cfg, indent=2))
        install(r)
        assert "base_branch" not in config(r)


class TestCheckReportsTheBaseBranch:
    def test_a_named_base_branch_is_reported(self, repo):
        set_config(repo, base_branch="main")
        out = installer("--check", str(repo))
        assert "base branch: main" in out.stdout and "WARNING base branch" not in out.stdout

    def test_origins_default_is_reported_when_none_is_named(self, repo):
        with_origin(repo)
        out = installer("--check", str(repo))
        assert "base branch: origin/main (origin's default" in out.stdout

    def test_no_name_and_no_recorded_default_warns(self, repo):
        out = installer("--check", str(repo))
        assert "WARNING base branch unknown" in out.stdout
        assert "git remote set-head origin --auto" in out.stdout

    def test_a_named_branch_that_is_not_in_the_clone_warns(self, repo):
        set_config(repo, base_branch="origin/main")
        out = installer("--check", str(repo))
        assert "WARNING base branch origin/main" in out.stdout and "not in this clone" in out.stdout

    def test_the_warning_is_not_a_failure(self, repo):
        # the hooks fail closed without a base branch, so the install still works
        with_base = installer("--check", str(repo))
        set_config(repo, base_branch="main")
        assert installer("--check", str(repo)).returncode == with_base.returncode


class TestGatesRunByHandUseTheNamedBase:
    def test_the_named_base_branch_wins_over_the_usual_names(self, repo):
        git(repo, "branch", "release")
        set_config(repo, base_branch="release")
        assert load_kitlib().default_base(repo) == "release"

    def test_a_named_branch_that_does_not_exist_falls_back_to_the_usual_names(self, repo):
        set_config(repo, base_branch="origin/gone")
        assert load_kitlib().default_base(repo) == "main"

    def test_the_diff_guard_with_no_base_given_compares_with_the_named_branch(self, repo):
        # a clone that has no origin/main and records no default: only the config knows the base
        git(repo, "branch", "-m", "main", "trunk")
        set_config(repo, base_branch="trunk")
        commit_all(repo, "name the base")
        git(repo, "checkout", "-qb", "feature")
        git(repo, "rm", "-q", "tests/test_calc.py")
        git(repo, "commit", "-qm", "drop the test")
        r = py(repo, "test_diff_guard.py")
        assert r.returncode == 1 and "against trunk" in r.stdout and "test file deleted" in r.stdout


class TestDraftsOfTestsCannotBeMerged:
    def guard(self, repo, path, text="def test_draft():\n    assert True\n", not_test_globs=None):
        if not_test_globs is not None:
            set_config(repo, not_test_globs=not_test_globs)
            commit_all(repo, "config on the base")
        git(repo, "checkout", "-qb", "feature")
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text(text)
        commit_all(repo, "work")
        return py(repo, "test_diff_guard.py", "--base", "main")

    @pytest.mark.parametrize("path", ["web/cart.test.draft.ts", "web/cart.draft.test.ts",
                                      "tests/test_calc.draft.py"])
    def test_a_committed_draft_of_a_test_is_blocked(self, repo, path):
        r = self.guard(repo, path)
        assert r.returncode == 1 and f"draft of a test committed: {path}" in r.stdout

    def test_it_is_blocked_even_when_the_config_says_drafts_are_not_tests(self, repo):
        r = self.guard(repo, "web/cart.draft.test.ts", not_test_globs=["**/*.draft.*"])
        assert r.returncode == 1 and "draft of a test committed: web/cart.draft.test.ts" in r.stdout

    def test_a_production_file_called_a_draft_is_not_blocked(self, repo):
        r = self.guard(repo, "src/calc/letter.draft.txt", "Dear customer\n")
        assert r.returncode == 0 and "draft of a test" not in r.stdout

    def test_test_data_called_a_draft_is_not_blocked(self, repo):
        r = self.guard(repo, "tests/fixtures/invoice.draft.json", "{}\n")
        assert "draft of a test" not in r.stdout

    def test_a_branch_that_removed_its_draft_again_passes(self, repo):
        self.guard(repo, "web/cart.test.draft.ts")
        git(repo, "rm", "-q", "web/cart.test.draft.ts")
        git(repo, "commit", "-qm", "draft promoted")
        r = py(repo, "test_diff_guard.py", "--base", "main")
        assert "draft of a test" not in r.stdout
