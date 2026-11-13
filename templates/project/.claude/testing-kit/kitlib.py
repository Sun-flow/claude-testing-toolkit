"""Shared helpers for the testing-kit hooks. Standard library only.

Hooks receive a JSON object on stdin (Claude Code hook input) and signal back
through exit codes (0 = allow, 2 = block with stderr shown to Claude) or a
JSON object on stdout. See https://code.claude.com/docs/en/hooks
"""
from __future__ import annotations

import json
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

DEFAULT_CONFIG = {
    "test_globs": [
        "tests/**", "test/**", "**/tests/**", "**/test/**", "**/__tests__/**",
        "**/*.test.*", "**/*.spec.*", "**/test_*.py", "**/*_test.py",
        "**/*_test.go", "**/*Test.java", "**/*Tests.cs",
        # Other ecosystems, by file name. A folder named spec/ often holds specifications, so only *_spec.rb.
        "**/Tests/**", "**/*.Tests/**", "**/*Test.cs", "**/*Test.kt", "**/*Tests.swift", "**/*Test.php",
        "**/*_spec.rb", "**/*_test.rb", "**/*_test.exs", "**/*_test.dart",
        "**/__snapshots__/**", "**/*.snap", "**/snapshots/**", "**/testdata/**",
    ],
    "harness_globs": [
        "**/conftest.py", "pytest.ini", "pytest.toml", ".pytest.ini", ".pytest.toml", "tox.ini",
        "noxfile.py", ".coveragerc", "jest.config.*", "jest.setup.*", "vitest.config.*",
        "vitest.workspace.*", "vitest.setup.*", "vite.config.*", "playwright.config.*",
        "babel.config.*", ".babelrc*", "**/setupTests.*",
        "karma.conf.*", ".mocharc*", "codecov.yml", ".codecov.yml",
        ".github/workflows/**", ".github/CODEOWNERS", "CODEOWNERS",
        ".claude/settings.json", ".claude/settings.local.json", ".claude/testing-kit/**",
        "**/sitecustomize.py", "**/usercustomize.py", "**/*.pth",
        ".claude/testing-kit.json", ".claude/agents/**", ".claude/rules/testing.md",
    ],
    # Sections of shared manifests that are harness config. Edits that touch
    # these sections are blocked; the rest of the file stays editable.
    "harness_sections": {
        "pyproject.toml": [r"^\[tool\.pytest", r"^\[tool\.coverage", r"^\[tool\.mutmut"],
        "setup.cfg": [r"^\[tool:pytest", r"^\[coverage:"],
        "package.json": [r'"jest"\s*:', r'"vitest"\s*:', r'"c8"\s*:', r'"nyc"\s*:'],
    },
    "src_dirs": ["src", "lib", "app", "pkg", "internal"],
    "commands": {"fast": "", "full": "", "mutation": ""},
    "junit_path": ".reports/junit.xml",
    "stop_hook": {"enabled": True, "timeout_s": 300},
    # "ask": the user approves or declines in Claude Code's permission prompt (default).
    # "deny": always refuse; the user edits the file or uses the allow marker.
    "enforcement": "ask",
    "default_tier": "medium",
}

ALLOW_MARKER = ".claude/allow-test-edits"
ALLOW_MARKER_TTL_S = 2 * 60 * 60  # a forgotten marker stops counting after 2 hours


def project_dir(hook_input: dict | None = None) -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    if hook_input and hook_input.get("cwd"):
        return Path(hook_input["cwd"])
    return Path.cwd()


@lru_cache(maxsize=None)
def _load_config(root: str) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    path = Path(root) / ".claude" / "testing-kit.json"
    if path.is_file():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(user, dict):
                raise ValueError("not a JSON object")
        except (OSError, ValueError) as exc:
            # fail closed: a broken config must not quietly turn strict mode into ask mode
            cfg["enforcement"] = "deny"
            cfg["_config_error"] = f".claude/testing-kit.json can't be read ({exc}); fix it"
            return cfg
        _merge_config(cfg, user)
    return cfg


def _merge_config(cfg: dict, user: dict) -> None:
    for key, value in user.items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(value)
        else:
            cfg[key] = value


def load_config(root: Path) -> dict:
    return _load_config(str(root))


def load_config_at(root: Path, rev: str) -> dict:
    """The config as committed at `rev` (CI gates use the base branch's copy, so a pull request can't
    point the gates at a different test command). Falls back to the working tree if `rev` has none."""
    import subprocess
    try:
        out = subprocess.run(["git", "show", f"{rev}:.claude/testing-kit.json"], cwd=root, capture_output=True,
                             text=True, encoding="utf-8", errors="replace", timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return load_config(root)
    if out.returncode != 0:
        return load_config(root)
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        user = json.loads(out.stdout)
    except ValueError:
        return load_config(root)
    _merge_config(cfg, user if isinstance(user, dict) else {})
    cfg["_from_rev"] = rev
    return cfg


def default_base(root: Path, fallback: str = "origin/main") -> str:
    """What a pull request from this branch would be compared with: origin's default branch, or the
    first of the usual names that exists. For running the CI gates by hand without --base."""
    import subprocess

    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8",
                                 errors="replace", timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return out.stdout.strip() if out.returncode == 0 else None

    head = git("symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if head:
        return head
    for name in ("origin/main", "origin/master", "main", "master"):
        if git("rev-parse", "--verify", "--quiet", name + "^{commit}"):
            return name
    return fallback


# macOS and Windows filesystems are normally case-insensitive: TESTS/Test_x.py is the same file there.
CASE_INSENSITIVE_FS = sys.platform in ("darwin", "win32", "cygwin")


@lru_cache(maxsize=None)
def glob_to_regex(glob: str, ignore_case: bool = False) -> re.Pattern:
    """Translate a gitignore-style glob (with **) to an anchored regex on posix paths."""
    i, out = 0, []
    while i < len(glob):
        c = glob[i]
        if c == "*":
            if glob[i:i + 3] == "**/":
                out.append(r"(?:.*/)?")
                i += 3
                continue
            if glob[i:i + 2] == "**":
                out.append(r".*")
                i += 2
                continue
            out.append(r"[^/]*")
        elif c == "?":
            out.append(r"[^/]")
        else:
            out.append(re.escape(c))
        i += 1
    return re.compile("^" + "".join(out) + "$", re.I if ignore_case else 0)


def rel_posix(path: str | os.PathLike, root: Path) -> str:
    p = Path(str(path).replace("\\", "/")) if os.name != "nt" else Path(path)
    if not p.is_absolute():
        p = root / p
    try:
        # realpath, so a symlink pointing into the project can't hide a protected file
        rel = os.path.relpath(os.path.realpath(str(p)), os.path.realpath(str(root)))
    except ValueError:  # different drive on Windows
        return Path(path).as_posix()
    return Path(rel).as_posix()


def matches_any(rel: str, globs) -> bool:
    while rel.startswith("./"):
        rel = rel[2:]
    return any(glob_to_regex(g, CASE_INSENSITIVE_FS).match(rel) for g in globs)


def is_test_path(rel: str, cfg: dict) -> bool:
    # extra_test_globs: your own layout, on top of the built-in patterns.
    # not_test_globs: production files that only look like tests (src/tools/test_runner.py).
    return (matches_any(rel, cfg["test_globs"] + (cfg.get("extra_test_globs") or []))
            and not matches_any(rel, cfg.get("not_test_globs") or []))


def is_harness_path(rel: str, cfg: dict) -> bool:
    return matches_any(rel, cfg["harness_globs"] + (cfg.get("extra_harness_globs") or []))


def has_tests(paths, cfg: dict) -> bool:
    """Does this file list contain project tests? (The kit's own test_*.py scripts don't count.)"""
    return any(is_test_path(f, cfg) for f in paths if not f.startswith(".claude/"))


def harness_section_patterns(rel: str, cfg: dict) -> list[str]:
    sections = cfg.get("harness_sections", {})
    return sections.get(rel) or sections.get(Path(rel).name) or []


def allow_marker_present(root: Path) -> bool:
    import time
    marker = root / ALLOW_MARKER
    try:
        return time.time() - marker.stat().st_mtime < ALLOW_MARKER_TTL_S
    except OSError:
        return False


def head_content(root: Path, rel: str) -> str | None:
    """Content of `rel` at HEAD if git tracks it there (deleted-then-recreated files stay protected)."""
    import subprocess
    try:
        out = subprocess.run(["git", "show", f"HEAD:{rel}"], cwd=root, capture_output=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------- per-session state
# Small files under .claude/testing-kit/.state/ (git-ignored): what the working tree looked like when
# the session started, the audit snapshots for shell commands, and the result of the last test run.

STATE_DIR = ".claude/testing-kit/.state"
STATE_TTL_S = 14 * 24 * 60 * 60  # files left by sessions older than this are deleted
BIG_FILE = 5_000_000             # larger changed files are fingerprinted by size and time, not content


def session_key(hook_input: dict | None) -> str:
    sid = str((hook_input or {}).get("session_id") or "")
    return "".join(c for c in sid if c.isalnum() or c in "-_")[:64] or "default"


def state_path(root: Path, hook_input: dict | None, suffix: str) -> Path:
    return root / STATE_DIR / f"{session_key(hook_input)}.{suffix}"


def ensure_state_dir(root: Path) -> Path:
    d = root / STATE_DIR
    d.mkdir(parents=True, exist_ok=True)
    ignore = d / ".gitignore"
    if not ignore.exists():
        ignore.write_text("*\n", encoding="utf-8")  # so state never shows up as a change in the repo
    return d


def prune_state(root: Path) -> None:
    import time
    cutoff = time.time() - STATE_TTL_S
    try:
        for f in (root / STATE_DIR).iterdir():
            if f.name != ".gitignore" and f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
    except OSError:
        pass


def tree_fingerprint(root: Path) -> tuple[str, bool] | None:
    """(fingerprint, has_uncommitted_changes) for the working tree as git sees it: the commit that is
    checked out plus the content of every changed or untracked file. Ignored files don't count.
    None when git can't say (not a repository, git missing, timeout)."""
    import hashlib
    import subprocess

    def git(*args: str, timeout: int = 60):
        return subprocess.run(["git", *args], cwd=root, capture_output=True, timeout=timeout)

    try:
        top = git("rev-parse", "--show-toplevel", timeout=15)
        if top.returncode != 0:
            return None
        head = git("rev-parse", "-q", "--verify", "HEAD", timeout=15)  # fails in a repo with no commit yet
        status = git("status", "--porcelain=v1", "-z", "--no-renames", "--untracked-files=all")
    except (OSError, subprocess.TimeoutExpired):
        return None
    if status.returncode != 0:
        return None
    toplevel = Path(os.fsdecode(top.stdout.strip()))  # status paths are relative to this, not to `root`
    entries = sorted(e for e in status.stdout.split(b"\0") if e)
    h = hashlib.sha256(head.stdout.strip() + b"\n")
    for entry in entries:
        h.update(entry + b"\0")
        path = toplevel / os.fsdecode(entry[3:])
        try:
            if path.is_symlink():
                h.update(b"L" + os.fsencode(os.readlink(path)))
            elif path.is_dir():
                h.update(b"D")  # a nested repository or submodule
            else:
                st = path.stat()
                if st.st_size > BIG_FILE:
                    h.update(f"S{st.st_size}:{st.st_mtime_ns}".encode())
                else:
                    h.update(hashlib.sha256(path.read_bytes()).digest())
        except OSError:
            h.update(b"-")  # deleted
    return h.hexdigest(), bool(entries)


def record_baseline(root: Path, hook_input: dict | None) -> None:
    """Remember what the working tree looked like when this session started (once per session), so the
    Stop hook can tell whether anything changed since. Called at SessionStart and, in case that hook
    didn't run, before the first edit or shell command."""
    path = state_path(root, hook_input, "base")
    if path.exists():
        return
    fp = tree_fingerprint(root)
    try:
        ensure_state_dir(root)
        path.write_text(fp[0] if fp else "unknown", encoding="utf-8")
    except OSError:
        return
    prune_state(root)


def read_state(root: Path, hook_input: dict | None, suffix: str) -> str | None:
    try:
        return state_path(root, hook_input, suffix).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def read_hook_input() -> dict:
    """The JSON Claude Code sends on stdin. It is UTF-8, so it is read as bytes: a pipe on Windows is
    otherwise decoded in the system code page, where an accent turns into other characters (an edit's old
    text is then not found in the file) and some characters can't be read at all."""
    try:
        raw = getattr(sys.stdin, "buffer", None)
        data = raw.read().decode("utf-8-sig", "replace") if raw is not None else sys.stdin.read()
        obj = json.loads(data) if data.strip() else {}
    except (ValueError, OSError, AttributeError):
        return {}
    return obj if isinstance(obj, dict) else {}


def tolerant_output() -> None:
    """For the scripts that print a report. A pipe on Windows uses the system code page: a character it
    lacks (in a file name, a test name, a test runner's output) is shown as \\uXXXX instead of stopping
    the script with UnicodeEncodeError."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):  # replaced by something that isn't a text file
            pass


def block(message: str) -> None:
    """Exit 2: Claude Code blocks the action and shows stderr to Claude."""
    sys.stderr.write(message.rstrip() + "\n")
    sys.exit(2)


DENY_NEXT_STEP = ("Blocked (strict mode): Claude may not make this change. If it is wrong, stop and tell the "
                  "user the file, what it expects, what the code does and your evidence. The user can make "
                  "the change themselves, or run `touch .claude/allow-test-edits` to allow test edits for 2 hours.")


def guard(message: str, cfg: dict) -> None:
    """Refuse a protected change: ask the user (default) or deny outright."""
    note = f" Also: {cfg['_config_error']}." if cfg.get("_config_error") else ""
    if cfg.get("enforcement", "ask") == "deny":
        # the ask-mode text addresses an approver; in deny mode there is none
        message = message.split(" Approve only if")[0]
        block("Testing kit: " + message.rstrip(". ") + ". " + DENY_NEXT_STEP + note)
    message += note
    emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": "Testing kit: " + message,
    }})


def run_hook(main, *args, protective: bool = True) -> None:
    """Run a hook's main(). A crash in a protective PreToolUse hook asks the user instead of silently
    allowing the action (Claude Code treats a crashed hook as non-blocking); other hooks just report it."""
    try:
        main(*args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        where = Path(sys.argv[0]).name
        if protective:
            emit({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": f"Testing kit: the {where} check failed ({type(exc).__name__}: {exc}), "
                                            "so it can't confirm this action is safe for the tests. Approve only "
                                            "if you know it doesn't weaken tests or test config.",
            }})
        sys.stderr.write(f"Testing kit: {where} failed: {type(exc).__name__}: {exc}\n")
        sys.exit(0)


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.exit(0)


TEST_FUNC_RE = re.compile(
    r"^\s*(?:async\s+)?def\s+(test_\w+)|"            # python
    r"^\s*(?:it|test|describe)(?:\.\w+)?\(\s*['\"`]([^'\"`]+)|"  # js/ts
    r"^\s*func\s+(Test\w+)\s*\(",                       # go
    re.M,
)

SKIP_RE = re.compile(
    r"pytest\.mark\.(?:skip|skipif|xfail)\b|pytest\.skip\(|pytest\.xfail\(|pytest\.importorskip\(|"
    r"@unittest\.skip|\bpytestmark\s*=.*\b(?:skip|xfail)|"
    r"\b(?:it|test|describe)\.(?:skip|only|todo|fails)\b|\bx(?:it|describe|test)\(|\bf(?:it|describe)\(|"
    r"\bt\.Skip(?:Now|f)?\(|@Disabled\b|@Ignore\b|#\[ignore\]",
)
SLEEP_RE = re.compile(
    r"\btime\.sleep\(|\basyncio\.sleep\(\s*[0-9.]+\s*\)|\bThread\.sleep\(|\bwaitForTimeout\(|"
    r"\bcy\.wait\(\s*\d|\bsetTimeout\([^)]*resolve|\btime\.Sleep\(|\bsleep\s+\d",
)
RETRY_RE = re.compile(
    r"@pytest\.mark\.flaky|@flaky\b|--reruns|\bjest\.retryTimes\(|\bretries\s*[:=]\s*[1-9]|"
    r"\.retries\(\s*[1-9]|@Retry\b|@RepeatedTest\b",
)
BROAD_EXCEPT_RE = re.compile(r"except\s*(?:Exception|BaseException)?\s*:\s*(?:\n\s*)?(?:pass|\.\.\.|return)\b")
# Production code that behaves differently under a test (TG-16). A cheap heuristic: string tricks
# beat it, so review (test-reviewer agent, a human) is the real gate.
TEST_ENV_RE = re.compile(
    r"PYTEST_|['\"]pytest['\"]\s+in\s+sys\.modules|sys\.modules\.get\(\s*['\"]pytest|"
    r"\b_pytest\b|NODE_ENV\s*[!=]==?\s*['\"]test['\"]|JEST_WORKER_ID|process\.env\.VITEST\b|"
    r"import\.meta\.env\.(?:VITEST|MODE\s*===?\s*['\"]test)|['\"]test['\"]\s+in\s+sys\.argv|testing\.Testing\(\)|"
    r"\bunittest\b.*\bin\s+sys\.modules")
NO_COVER_RE = re.compile(r"pragma:\s*no\s*cover|istanbul\s+ignore|c8\s+ignore|v8\s+ignore")
PROSE_SUFFIXES = (".md", ".markdown", ".mdx", ".rst", ".txt", ".adoc")


def is_prose(path: str) -> bool:
    """Documentation. It may describe test detection or coverage pragmas without being code (TG-16, TG-33)."""
    return path.lower().endswith(PROSE_SUFFIXES)


def test_names(text: str) -> list[str]:
    names = []
    for m in TEST_FUNC_RE.finditer(text or ""):
        names.append(next(g for g in m.groups() if g))
    return names


_CLASS_RE = re.compile(r"^(\s*)class\s+(\w+)")
_DEF_RE = re.compile(r"^(\s*)(?:async\s+)?def\s+(test_\w+)")


def qualified_test_names(text: str) -> list[str]:
    """Test names qualified by their Python class (TestAdd::test_zero), as a list so duplicates count.
    Non-Python tests fall back to bare names."""
    out, classes = [], []  # classes: stack of (indent, name)
    py = False
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        while classes and indent <= classes[-1][0]:
            classes.pop()
        c = _CLASS_RE.match(line)
        if c:
            classes.append((len(c.group(1)), c.group(2)))
            continue
        d = _DEF_RE.match(line)
        if d:
            py = True
            out.append("::".join([n for _, n in classes] + [d.group(2)]))
    return out if py else test_names(text)
