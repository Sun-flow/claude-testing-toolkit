import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]

# The kit author's own people and projects. They must stay out of what the kit installs into other repos.
# This file doesn't spell them either: it keeps the start of each name's SHA-256 (lower case).
PRIVATE_WORDS = {"222e292d98107dd3", "a744834ed461ae1d", "ae30a9cffbdcacb4"}


def lines_with_private_words(text: str) -> list:
    """The numbers of the lines in `text` that name one of them (numbers, so a failure doesn't print the name)."""
    return [number for number, line in enumerate(text.splitlines(), 1)
            if any(hashlib.sha256(word.encode()).hexdigest()[:16] in PRIVATE_WORDS
                   for word in re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", line.lower()))]


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small Python repo with one passing test, committed on main, kit installed."""
    r = tmp_path / "repo"
    (r / "src" / "calc").mkdir(parents=True)
    (r / "tests").mkdir()
    (r / "pyproject.toml").write_text(
        '[project]\nname = "calc"\nversion = "0.1"\ndependencies = []\n\n'
        '[tool.pytest.ini_options]\naddopts = "-q"\npythonpath = ["src"]\n', encoding="utf-8")
    (r / "src" / "calc" / "__init__.py").write_text(
        "def add(a, b):\n    return a + b\n\n\ndef div(a, b):\n    if b == 0:\n        raise ZeroDivisionError('b is 0')\n    return a / b\n",
        encoding="utf-8")
    (r / "tests" / "test_calc.py").write_text(
        "import pytest\nfrom calc import add, div\n\n\ndef test_add():\n    assert add(2, 3) == 5\n\n\n"
        "def test_div_by_zero():\n    with pytest.raises(ZeroDivisionError):\n        div(1, 0)\n", encoding="utf-8")
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "kit@example.com")
    git(r, "config", "user.name", "kit")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    res = subprocess.run([sys.executable, str(KIT / "install.py"), "--project", str(r)],
                         capture_output=True, text=True, env={**os.environ, "TESTING_KIT_PYTHON": "python3"})
    assert res.returncode == 0, res.stdout + res.stderr
    cfg_path = r / ".claude" / "testing-kit.json"
    cfg = json.loads(cfg_path.read_text())
    cfg["commands"]["fast"] = f'"{sys.executable}" -m pytest -q -p no:cacheprovider --junitxml=.reports/junit.xml'
    cfg["commands"]["setup"] = ""
    cfg_path.write_text(json.dumps(cfg, indent=2))
    git(r, "add", "-A")
    git(r, "commit", "-qm", "install kit")
    return r


def run_hook(repo: Path, script: str, payload: dict, *args: str):
    payload = {"cwd": str(repo), "session_id": "test", **payload}
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(repo)}
    proc = subprocess.run([sys.executable, str(repo / ".claude/testing-kit" / script), *args],
                          input=json.dumps(payload), capture_output=True, text=True, env=env)
    out = json.loads(proc.stdout) if proc.stdout.strip() else None
    return proc.returncode, out, proc.stderr


def decision(result) -> str:
    """allow | ask | block"""
    code, out, _ = result
    if code == 2:
        return "block"
    if out and out.get("hookSpecificOutput", {}).get("permissionDecision") == "ask":
        return "ask"
    if out and out.get("decision") == "block":
        return "block"
    assert code == 0, result
    return "allow"
