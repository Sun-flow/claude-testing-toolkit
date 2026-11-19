#!/usr/bin/env python3
"""PreToolUse hook (Bash|PowerShell): stop shell-level bypasses of the test protections.

Deny  : shell commands that write, move, delete or restore protected test or
        harness paths (rm, mv, cp onto, sed -i, perl -i, tee, >, truncate,
        git rm/mv/checkout/restore/reset, inline python/node writes), and git
        commands that move the base branch or take HEAD back behind it, because
        the base branch decides which tests are protected.
        A test the base branch doesn't have is work in progress and is not
        protected (see protect_tests.py); harness files always are.
Ask   : snapshot/golden update commands and retry flags on test runs. The user
        approves or declines in the permission prompt.
This is a speed bump, not a sandbox: it inspects the command text. The CI diff
guard (kit: ci/test_diff_guard.py) is the backstop.
Guidelines: TG-14, TG-15, TG-17, TG-18.
"""
from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # never leave __pycache__ in the repo
sys.path.insert(0, str(Path(__file__).resolve().parent))
import kitlib  # noqa: E402

WRITE_CMDS = {"rm", "rmdir", "mv", "cp", "tee", "truncate", "dd", "ln", "install", "unlink", "shred",
              "chmod", "touch", "rsync", "patch",
              # PowerShell (matched case-insensitively) and cmd.exe
              "remove-item", "move-item", "copy-item", "set-content", "add-content", "out-file",
              "clear-content", "new-item", "rename-item", "ri", "del", "erase", "move", "copy", "ren", "rd",
              "sc", "ac", "mi", "cpi"}
INPLACE_FLAGS = re.compile(r"^-(?:[a-zA-Z]*i[a-zA-Z]*|-in-place)(?:=.*)?$")  # sed -i, perl -pi, sed --in-place
GIT_WRITE = {"rm", "mv", "checkout", "restore", "reset", "apply", "clean"}
# These write only their last operand (or the folder after -t); the ones before it are read.
COPY_CMDS = {"cp", "copy-item", "copy", "cpi", "install", "rsync", "ln"}
# git options that take a value, so the word after them is not the subcommand
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path", "--super-prefix"}
INLINE_WRITE = re.compile(r"open\([^)]*['\"][wax]\+?b?['\"]|write_text|write_bytes|writeFileSync|writeFile\(|"
                          r"unlink|os\.remove|shutil\.(?:move|rmtree|copy)|fs\.rm|renameSync|Path\([^)]*\)\.rename")
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish", "pwsh", "powershell", "cmd"}
REDIRECT = re.compile(r"(?:^|[^0-9&<>=-])>>?\s*([^\s;&|]+)")

SNAPSHOT_UPDATE = re.compile(
    r"(?:\b(?:jest|vitest)\b[^;&|]*\s(?:-u|--update(?:Snapshot)?)\b)|--snapshot-update\b|--update-snapshots?\b|"
    r"\binsta\s+(?:accept|review)\b|\bINSTA_UPDATE=(?:always|new|1)|\bUPDATE_(?:GOLDEN|SNAPSHOTS?)=1|"
    r"\bSNAPSHOT_UPDATE=1|--update-goldens?\b|-update\b.*\bgo test|go test\b.*\s-update\b|"
    r"\bpytest\b[^;&|]*--(?:force-regen|regen-all)\b|\bapprovaltests?\b.*approve"
)
RETRY_FLAGS = re.compile(r"(?:pytest|py\.test|vitest|jest|playwright|npm|pnpm|yarn|npx)\b[^;&|]*"
                         r"\s--(?:reruns|retries|retry|only-rerun|flake-finder)\b")


def split_commands(command: str) -> list[list[str]]:
    parts = re.split(r"\|\||&&|;|\||\n", command)
    out = []
    for part in parts:
        try:
            tokens = shlex.split(part, posix=True)
        except ValueError:
            tokens = part.split()
        if tokens:
            out.append(tokens)
    return out


_BASE_FILES: dict = {}


def base_files(root: Path, cfg: dict) -> dict | None:
    """The base branch's files, read once per run (None when the base can't be worked out)."""
    key = str(root)
    if key not in _BASE_FILES:
        _BASE_FILES[key] = kitlib.base_files(root, cfg)
    return _BASE_FILES[key]


def protected(token: str, root: Path, cfg: dict, cwd: Path | None = None) -> str | None:
    tok = token.strip("'\"")
    if "=" in tok and not tok.startswith(("./", "/")):
        tok = tok.split("=", 1)[1].strip("'\"")  # dd of=tests/x.py, --output=tests/x.py
    if not tok or tok.startswith("-"):
        return None
    if cwd is not None and not Path(tok).is_absolute():
        tok = str(cwd / tok)  # after a `cd`, relative paths are relative to the new directory
    rel = kitlib.rel_posix(tok, root)
    if rel.startswith("../"):
        return None
    if kitlib.is_harness_path(rel, cfg) or kitlib.harness_section_patterns(rel, cfg):
        return rel
    if kitlib.is_test_path(rel, cfg) and (root / rel).exists() and not (root / rel).is_dir():
        # a test the base branch doesn't have is still its author's work in progress
        return None if kitlib.new_on_branch(base_files(root, cfg), rel, cfg) else rel
    # a directory that holds tests (rm -rf tests)
    if (root / rel).is_dir() and (kitlib.is_test_path(rel.rstrip("/") + "/x", cfg) or kitlib.is_test_path(rel, cfg)):
        files = base_files(root, cfg)
        if files is None:
            return rel
        prefix = "" if rel in (".", "") else rel.rstrip("/") + "/"
        fold = kitlib.CASE_INSENSITIVE_FS
        if any(kitlib.is_test_path(name, cfg) for key, name in files.items()
               if key.startswith(prefix.lower() if fold else prefix)):
            return rel
    return None


def written_operands(cmd: str, args: list) -> list:
    """The operands a command writes to. Copy commands write only their destination."""
    if cmd not in COPY_CMDS:
        return args
    for i, arg in enumerate(args):
        if arg in {"-t", "--target-directory", "-Destination", "-destination"} and i + 1 < len(args):
            return [args[i + 1]]
        if arg.startswith("--target-directory="):
            return [arg.split("=", 1)[1]]
    operands = [a for a in args if not a.startswith("-")]
    return operands[-1:]


def _git_ok(root: Path, *args: str) -> bool | None:
    import subprocess
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=15).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return None


def names_ref(arg: str, ref: str) -> bool:
    """Does this word name the base branch? (main, refs/heads/main, origin/main, refs/remotes/origin/main)"""
    arg = arg.lstrip("+")
    for prefix in ("refs/heads/", "refs/remotes/"):
        if arg.startswith(prefix):
            arg = arg[len(prefix):]
    return bool(ref) and arg == ref


def base_ref_moves(args: list, root: Path, cfg: dict) -> str | None:
    """`args` are a git command's words after `git`. Says how it would move the base branch, or take
    HEAD back behind the commit where this branch left it. Either changes which tests count as the base
    branch's, so tests the base branch has could then be edited without a prompt."""
    while args and args[0].startswith("-"):
        args = args[2:] if args[0] in GIT_VALUE_OPTS else args[1:]
    if not args:
        return None
    sub, rest = args[0], args[1:]
    words = [a for a in rest if not a.startswith("-")]
    if sub == "update-ref":
        return "`git update-ref` rewrites a reference directly"
    if sub == "symbolic-ref" and (len(words) >= 2 or any(a in {"-d", "--delete"} for a in rest)):
        return "`git symbolic-ref` repoints a reference"
    if sub == "remote" and words[:1] == ["set-head"]:
        return "`git remote set-head` changes which branch counts as origin's default"
    ref = kitlib.base_ref(root, cfg)
    if not ref:
        return None  # no base branch known: every test on disk is protected whatever git does
    if sub == "branch" and any(names_ref(w, ref) for w in words) and (
            any(a.startswith("--") and a[2:] in {"force", "delete", "move", "copy"} for a in rest)
            or any(re.match(r"^-[a-zA-Z]*[fdDmMcC]", a) for a in rest if not a.startswith("--"))):
        return f"`git branch` would move, rename or delete the base branch {ref}"
    if sub in {"checkout", "switch"}:
        for flag, name in zip(rest, rest[1:]):
            if flag in {"-B", "-C", "--force-create"} and names_ref(name, ref):
                return f"`git {sub} {flag}` would reset the base branch {ref}"
    if sub in {"fetch", "pull", "push"}:
        for w in words:
            if ":" in w and names_ref(w.split(":", 1)[1], ref):
                return f"`git {sub}` with {w} would write the base branch {ref} directly"
    if sub == "reset":
        before_paths = rest[:rest.index("--")] if "--" in rest else rest
        target = next((a for a in before_paths if not a.startswith("-")), None)
        commit = kitlib.base_commit(root, cfg)
        # a word that is not a commit is a path: `git reset tests/x.py` only unstages
        if target and commit and _git_ok(root, "rev-parse", "--verify", "--quiet", target + "^{commit}") \
                and _git_ok(root, "merge-base", "--is-ancestor", commit, target) is False:
            return (f"`git reset {target}` would take this branch back behind the commit where it left "
                    f"{ref}, while the tests added since stay on disk")
    return None


def violations(command: str, root: Path, cfg: dict, cwd: Path | None = None, depth: int = 0) -> list[str]:
    found = []
    cwd = cwd or root
    for tokens in split_commands(command):
        if tokens[0].lower() in {"cd", "pushd", "set-location", "sl", "chdir"}:
            dest = tokens[1] if len(tokens) > 1 else ""
            if not dest or dest == "-" or dest.startswith("~") or "$" in dest:
                cwd = root  # can't tell where this goes; bash_audit still checks afterwards
            else:
                cwd = Path(dest) if Path(dest).is_absolute() else cwd / dest
            continue
        # strip leading env assignments and wrappers
        while tokens and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[0]):
            tokens = tokens[1:]
        while tokens and tokens[0] in {"sudo", "command", "env", "xargs", "nohup", "time"}:
            tokens = tokens[1:]
        if not tokens:
            continue
        cmd = Path(tokens[0].replace("\\", "/")).name.lower()
        if cmd.endswith(".exe"):
            cmd = cmd[:-4]
        args = tokens[1:]
        targets = [r for r in (protected(a, root, cfg, cwd) for a in written_operands(cmd, args)) if r]
        if cmd in SHELLS and len(args) >= 2:
            # bash -c "...", pwsh -Command "...": look inside the quoted script
            for flag, script in zip(args, args[1:]):
                if flag.lower() in {"-c", "-command", "/c", "-lc"}:
                    found += violations(script, root, cfg, cwd, depth + 1) if depth < 3 else []
        elif cmd == "eval" and args:
            found += violations(" ".join(args), root, cfg, cwd, depth + 1) if depth < 3 else []
        elif cmd in WRITE_CMDS and targets:
            found.append(f"`{cmd}` on {', '.join(targets)}")
        elif cmd == "find" and targets and any(a in {"-delete", "-exec", "-execdir", "-ok"} for a in args):
            found.append(f"`find` with -delete/-exec on {', '.join(targets)}")
        elif cmd in {"sed", "perl", "ruby"} and any(INPLACE_FLAGS.match(a) for a in args) and targets:
            found.append(f"in-place `{cmd}` on {', '.join(targets)}")
        elif cmd == "git" and args and args[0] in GIT_WRITE and targets:
            found.append(f"`git {args[0]}` on {', '.join(targets)}")
        elif cmd == "git" and base_ref_moves(args, root, cfg):
            found.append(base_ref_moves(args, root, cfg) + " (the base branch decides which tests are protected)")
        elif cmd in {"python", "python3", "py", "node", "deno", "bun", "ruby", "perl"} and any(
                a in {"-c", "-e", "--eval"} for a in args):
            code = " ".join(args)
            if targets and INLINE_WRITE.search(code):
                found.append(f"inline `{cmd}` writing {', '.join(targets)}")
            else:
                # catch paths quoted inside the code string
                inner = [r for r in (protected(t, root, cfg, cwd) for t in re.findall(r"['\"]([^'\"]+)['\"]", code)) if r]
                if inner and INLINE_WRITE.search(code):
                    found.append(f"inline `{cmd}` writing {', '.join(inner)}")
    for m in REDIRECT.finditer(command):
        rel = protected(m.group(1), root, cfg, cwd) or protected(m.group(1), root, cfg)
        if rel:
            found.append(f"shell redirect into {rel}")
    return found


def main() -> None:
    hi = kitlib.read_hook_input()
    command = (hi.get("tool_input") or {}).get("command", "")
    if not command:
        return
    root = kitlib.project_dir(hi)
    if kitlib.allow_marker_present(root):
        return
    cfg = kitlib.load_config(root)

    if re.search(r"\bclaude\b[^;&|]*(?:--settings|--bare|--dangerously|disableAllHooks|--permission-mode\s+bypass)",
                 command) or "disableAllHooks" in command:
        kitlib.block("Blocked: starting Claude with different settings, or disabling hooks, from inside a "
                     "session would bypass the project's test protections.")
    if ".claude/testing-kit/.state" in command.replace("\\", "/") or "testing-kit/.state" in command:
        kitlib.block("Blocked: .claude/testing-kit/.state holds the audit of protected files; leave it alone.")
    if "allow-test-edits" in command:
        kitlib.block("Blocked: only the user may create or change the test-edit allow marker.")

    # relative paths start from the shell's directory, which can differ from the project's
    bad = violations(command, root, cfg, Path(hi["cwd"]) if hi.get("cwd") else None)
    if bad:
        kitlib.guard("this command would change protected tests or test harness (" + "; ".join(bad)
                     + "). Existing tests are the specification (TG-14/TG-15). Approve only if the user "
                     "asked for it. Claude: if a test is wrong, stop and report it with your evidence; to "
                     "add tests, write a new test (file) instead.", cfg)

    reasons = []
    if SNAPSHOT_UPDATE.search(command):
        reasons.append("it regenerates snapshot/golden files, which rewrites the expected output (TG-17). "
                       "Approve only if the behaviour change is intended")
    if RETRY_FLAGS.search(command):
        reasons.append("it reruns failing tests, which can hide a real failure (TG-18)")
    if reasons:
        kitlib.emit({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "Testing kit: " + "; ".join(reasons) + ".",
        }})


if __name__ == "__main__":
    kitlib.run_hook(main, protective=True)
