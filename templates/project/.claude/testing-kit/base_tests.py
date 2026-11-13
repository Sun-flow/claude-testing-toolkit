#!/usr/bin/env python3
"""CI gate: the base branch's tests must still pass against this branch's code.

    python .claude/testing-kit/base_tests.py [--base BRANCH] [--json]

1. Runs the fast test command in a worktree of the merge base -> the test IDs
   that passed there.
2. Builds a second worktree from HEAD, then puts back the merge base's copy of
   every test, harness and runner file (`runner_files`: a Makefile or script
   the test command goes through) and removes test/harness/runner files, new
   config-like files (pytest.toml, .babelrc, ...) and test reports that only
   exist on HEAD, so the branch can't steer the runner. Runs the same command
   -> the test IDs that pass now.
3. Fails if any test ID that passed on the base doesn't pass now, or if the
   runner failed on HEAD while its report shows no failure.
   ALLOW_TEST_CHANGES=1 (a human's PR label) still lists the lost tests but
   passes, for a test fix the user approved.

Because both runs use the base's tests and harness, editing, skipping,
deleting or renaming tests on the branch can't make this gate pass.

It compares test by test when the runner writes JUnit XML to `junit_path`
(.claude/testing-kit.json). With "junit_path": "" (go test, cargo test, a
Makefile target: no report) it compares the two runs' exit codes instead. That
is coarser: it can't name the tests, and when the base is already failing it
can't tell whether the branch broke more, so it asks for a human then.
`commands.setup` (optional) installs dependencies in each worktree.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in the repo
sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402


def run(cmd, cwd: Path, check=True, shell=False, **kwargs) -> subprocess.CompletedProcess:
    # git names files in UTF-8 on every system; a test command prints in the system's own encoding
    proc = subprocess.run(cmd, cwd=cwd, shell=shell, capture_output=True, text=True,
                          encoding=None if shell else "utf-8", errors="replace", **kwargs)
    if check and proc.returncode != 0:
        raise SystemExit(f"command failed: {cmd}\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    return proc


def passing_ids(junit: Path) -> tuple[set[str], int]:
    if not junit.is_file():
        return set(), 0
    ok, total = set(), 0
    for case in ET.parse(junit).getroot().iter("testcase"):
        total += 1
        if all(case.find(t) is None for t in ("failure", "error", "skipped")):
            ok.add(f"{case.get('classname', '')}::{case.get('name', '')}")
    return ok, total


DEPENDENCY_FILES = {"pyproject.toml", "setup.py", "setup.cfg", "package.json", "package-lock.json", "yarn.lock",
                    "pnpm-lock.yaml", "uv.lock", "poetry.lock", "Pipfile", "Pipfile.lock", "go.mod", "go.sum",
                    "Cargo.toml", "Cargo.lock", "tsconfig.json", ".gitignore", ".gitattributes"}
CONFIG_LIKE = re.compile(r"^\.|\.(?:toml|ini|cfg|conf)$|(?:^|[._-])config\.|rc(?:\.\w+)?$")


# Files that only pin a tool version or configure an editor: a branch may add them, no runner reads them.
HARMLESS_DOTFILES = {".nvmrc", ".node-version", ".python-version", ".ruby-version", ".java-version",
                     ".go-version", ".tool-versions", ".editorconfig", ".dockerignore", ".mailmap", ".gitmodules"}


def protected(path: str, cfg: dict) -> bool:
    """Taken from the base in both runs: tests, harness, and the files the test command goes through."""
    return (kitlib.is_test_path(path, cfg) or kitlib.is_harness_path(path, cfg)
            or kitlib.matches_any(path, cfg.get("runner_files") or []))


def steers_runner(path: str, cfg: dict) -> bool:
    """A file only on HEAD that the runner might read: a new config file, or a committed report."""
    name = Path(path).name
    junit_dir = Path(cfg.get("junit_path", ".reports/junit.xml")).parent.as_posix()
    if junit_dir not in ("", ".") and path.startswith(junit_dir + "/"):
        return True
    if kitlib.harness_section_patterns(path, cfg):
        return True  # e.g. a setup.cfg or pyproject.toml the base doesn't have: it may carry runner config
    return (name not in DEPENDENCY_FILES and name not in HARMLESS_DOTFILES and "/" not in path
            and bool(CONFIG_LIKE.search(name)))


def failures(junit: Path) -> int:
    if not junit.is_file():
        return 0
    root = ET.parse(junit).getroot()
    return sum(1 for c in root.iter("testcase") if c.find("failure") is not None or c.find("error") is not None)


def tail(text: str, lines: int = 40) -> str:
    return "\n".join("    " + l for l in (text or "").strip().splitlines()[-lines:])


def run_suite(tree: Path, cfg: dict) -> dict:
    """Run setup and the fast command in `tree`. Returns the passing test IDs, the number of tests in
    the report, the exit code and the end of the output; or {"setup_failed": output}."""
    setup = (cfg.get("commands") or {}).get("setup")
    if setup:
        proc = run(setup, tree, check=False, shell=True)
        if proc.returncode != 0:
            return {"setup_failed": tail(proc.stdout + "\n" + proc.stderr), "setup": setup}
    junit_path = cfg.get("junit_path") or ""
    junit = tree / junit_path if junit_path else None
    if junit:
        junit.parent.mkdir(parents=True, exist_ok=True)
        junit.unlink(missing_ok=True)  # only a report written by this run counts
    proc = run(cfg["commands"]["fast"], tree, check=False, shell=True)
    ids, total = passing_ids(junit) if junit else (set(), 0)
    return {"ids": ids, "total": total, "rc": proc.returncode, "failures": failures(junit) if junit else 0,
            "output": tail(proc.stdout + "\n" + proc.stderr)}


APPROVED = "\nApproved by a human (ALLOW_TEST_CHANGES=1): passing despite the above."
ASK_A_HUMAN = ("If that is intended and the user agreed, a human adds the `allow-test-changes` label to the PR.")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="The base branch's tests must still pass against this branch's code.")
    ap.add_argument("--base", help="branch or commit to compare with (default: the repo's default branch)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    kitlib.tolerant_output()
    root = Path(run(["git", "rev-parse", "--show-toplevel"], Path.cwd()).stdout.strip())
    base = a.base or kitlib.default_base(root)
    merge_base = run(["git", "merge-base", base, "HEAD"], root).stdout.strip()
    # The base's config: the branch can't point this gate at a different command or report path.
    cfg = kitlib.load_config_at(root, merge_base)
    if not (cfg.get("commands") or {}).get("fast"):
        print("No commands.fast in .claude/testing-kit.json; nothing to run.")
        return 2
    by_exit_code = not cfg.get("junit_path")
    allowed = os.environ.get("ALLOW_TEST_CHANGES") == "1"
    work = Path(tempfile.mkdtemp(prefix="base-tests-"))
    base_tree, head_tree = work / "base", work / "head"
    try:
        run(["git", "worktree", "add", "--detach", str(base_tree), merge_base], root)
        run(["git", "worktree", "add", "--detach", str(head_tree), "HEAD"], root)
        base_files = [f for f in run(["git", "-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", merge_base], root).stdout.splitlines()
                      if protected(f, cfg)]
        all_base = set(run(["git", "-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", merge_base], root).stdout.splitlines())
        all_head = run(["git", "-c", "core.quotepath=off", "ls-tree", "-r", "--name-only", "HEAD"], root).stdout.splitlines()
        head_only = [f for f in all_head if f not in all_base and (protected(f, cfg) or steers_runner(f, cfg))]
        for f in head_only:
            (head_tree / f).unlink(missing_ok=True)
        if base_files:  # via stdin, so thousands of test files don't overflow the command line
            run(["git", "--literal-pathspecs", "checkout", merge_base, "--pathspec-from-file=-", "--pathspec-file-nul"], head_tree,
                input="\0".join(base_files))
        before = run_suite(base_tree, cfg)
        after = run_suite(head_tree, cfg) if "setup_failed" not in before else {}
    finally:
        for tree in (base_tree, head_tree):
            subprocess.run(["git", "worktree", "remove", "--force", str(tree)], cwd=root, capture_output=True)
        shutil.rmtree(work, ignore_errors=True)

    if "setup_failed" in before:
        print(f"Setup failed on the base (`{before['setup']}`), so there is nothing to compare with. Check "
              f"commands.setup in .claude/testing-kit.json.\n{before['setup_failed']}")
        return 2
    if "setup_failed" in after:
        print(f"Setup failed (`{after['setup']}`) in the copy of this branch that carries the base's tests.")
        for f in head_only:
            print(f"  removed (new on this branch)  {f}")
        print(after["setup_failed"])
        if head_only:
            print("If it only fails because the files above were removed (new files that can steer the test "
                  "runner are left out of this run), a human can check them and add the "
                  "`allow-test-changes` label to the PR.")
        if allowed:
            print(APPROVED)
            return 0
        return 1

    lost = sorted(before["ids"] - after["ids"])
    runner_mismatch = (not by_exit_code and before["rc"] == 0 and after["rc"] != 0 and after["failures"] == 0)
    base_has_tests = kitlib.has_tests(all_base, cfg)
    report = {"merge_base": merge_base, "mode": "exit_code" if by_exit_code else "junit",
              "base_passed": len(before["ids"]), "base_total": before["total"], "base_exit": before["rc"],
              "head_passed": len(after["ids"]), "head_total": after["total"], "head_exit": after["rc"],
              "now_failing": lost, "removed_from_head": head_only, "runner_exit_mismatch": runner_mismatch}
    if a.json:
        print(json.dumps(report, indent=2))

    def say(*lines: str) -> None:
        if not a.json:
            print("\n".join(lines))

    ignored = [f"  ignored (new on this branch)  {f}" for f in head_only]

    if by_exit_code:
        say("No junit_path is configured, so this gate compares exit codes, not individual tests.",
            f"The base's tests exit {before['rc']} on the base and {after['rc']} with this branch's code.", *ignored)
        if after["rc"] == 0:
            say("OK." if before["rc"] == 0 else "They failed on the base and pass now. OK.")
            return 0
        if before["rc"] != 0 and not base_has_tests:
            say("The base has no test files yet and its test command fails there too, so there is nothing to "
                "compare. OK.")
            return 0
        say("Output with this branch's code:", after["output"])
        if before["rc"] == 0:
            say("\nThis branch's code fails the base's tests. Fix the code. " + ASK_A_HUMAN)
        else:
            say("\nThe base's tests already fail on the base, so without a per-test report this gate can't "
                "tell whether this branch broke more. Get the base green, or make the test command write "
                "JUnit XML and set junit_path. " + ASK_A_HUMAN)
        if allowed:
            say(APPROVED)
            return 0
        return 1

    say(f"Base tests on this branch's code: {len(before['ids'])} passed on base, {len(after['ids'])} pass now.",
        *ignored)
    for t in lost[:50]:
        say(f"  NOW FAILING  {t}")
    if runner_mismatch:
        say(f"  The test command exited {after['rc']} on this branch but its report shows no failure.",
            after["output"])
    if before["total"] == 0:
        if not base_has_tests:
            say("The base has no tests yet, so there is nothing to compare. OK.")
            return 0
        say(f"No tests were collected on the base (no JUnit report at {cfg.get('junit_path')}). Check "
            "commands.fast and junit_path in .claude/testing-kit.json; if this runner can't write JUnit "
            "XML, set \"junit_path\": \"\" to compare exit codes instead. The run on the base ended with:",
            before["output"])
        return 2
    if not (lost or runner_mismatch):
        return 0
    if allowed:
        say("\nApproved by a human (ALLOW_TEST_CHANGES=1): passing despite the tests listed above.")
        return 0
    say("\nThis branch's code fails tests that pass on the base. Fix the code. If a listed test was itself "
        "wrong and the user agreed to change it, a human adds the `allow-test-changes` label to the PR.")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
