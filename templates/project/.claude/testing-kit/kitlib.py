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
        "**/__snapshots__/**", "**/*.snap", "**/snapshots/**", "**/testdata/**",
    ],
    "harness_globs": [
        "**/conftest.py", "pytest.ini", "tox.ini", "noxfile.py", ".coveragerc",
        "jest.config.*", "vitest.config.*", "vitest.workspace.*", "playwright.config.*",
        "karma.conf.*", ".mocharc*", "codecov.yml", ".codecov.yml",
        ".github/workflows/**", ".github/CODEOWNERS", "CODEOWNERS",
        ".claude/settings.json", ".claude/settings.local.json", ".claude/testing-kit/**",
        "**/sitecustomize.py", "**/usercustomize.py", "**/*.pth", "**/__init__.py.pth",
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
    "max_attempts_note": 3,
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
        except (OSError, ValueError):
            user = {}
        for key, value in user.items():
            if isinstance(value, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(value)
            else:
                cfg[key] = value
    return cfg


def load_config(root: Path) -> dict:
    return _load_config(str(root))


@lru_cache(maxsize=None)
def glob_to_regex(glob: str) -> re.Pattern:
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
    return re.compile("^" + "".join(out) + "$")


def rel_posix(path: str | os.PathLike, root: Path) -> str:
    p = Path(str(path).replace("\\", "/")) if os.name != "nt" else Path(path)
    if not p.is_absolute():
        p = root / p
    try:
        rel = os.path.relpath(os.path.normpath(str(p)), os.path.normpath(str(root)))
    except ValueError:  # different drive on Windows
        return Path(path).as_posix()
    return Path(rel).as_posix()


def matches_any(rel: str, globs) -> bool:
    rel = rel.lstrip("./") if rel.startswith("./") else rel
    return any(glob_to_regex(g).match(rel) for g in globs)


def is_test_path(rel: str, cfg: dict) -> bool:
    return matches_any(rel, cfg["test_globs"])


def is_harness_path(rel: str, cfg: dict) -> bool:
    return matches_any(rel, cfg["harness_globs"])


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


def read_hook_input() -> dict:
    try:
        data = sys.stdin.read()
        return json.loads(data) if data.strip() else {}
    except ValueError:
        return {}


def block(message: str) -> None:
    """Exit 2: Claude Code blocks the action and shows stderr to Claude."""
    sys.stderr.write(message.rstrip() + "\n")
    sys.exit(2)


def guard(message: str, cfg: dict) -> None:
    """Refuse a protected change: ask the user (default) or deny outright."""
    if cfg.get("enforcement", "ask") == "deny":
        block(message)
    emit({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": "Testing kit: " + message,
    }})


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
    r"@pytest\.mark\.(?:skip|skipif|xfail)|pytest\.skip\(|pytest\.xfail\(|@unittest\.skip|"
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
NO_COVER_RE = re.compile(r"pragma:\s*no\s*cover|istanbul\s+ignore|c8\s+ignore|v8\s+ignore")


def test_names(text: str) -> list[str]:
    names = []
    for m in TEST_FUNC_RE.finditer(text or ""):
        names.append(next(g for g in m.groups() if g))
    return names
