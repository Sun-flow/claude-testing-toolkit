#!/usr/bin/env python3
"""Testing kit installer. Standard library only; Python 3.9+; Linux, macOS, Windows.

  python install.py --project PATH [--profile minimal|standard|strict] [--tier low|medium|high]
                    [--ci | --no-ci] [--env | --no-env] [--owner GITHUB_LOGIN]
                    [--fast CMD] [--full CMD] [--setup CMD] [--dry-run] [--force]
  python install.py --user [--dry-run] [--force]
  python install.py --check PATH [--run]
  python install.py --uninstall PATH [--dry-run]

Safe to re-run, and re-running is how you upgrade. The installer records what it wrote in
.claude/testing-kit/manifest.json, so the next run:
  - updates the kit files you haven't touched and removes ones that are no longer part of the install;
  - keeps a rule, skill, agent, doc or workflow you changed (the kit's version goes beside it as
    <name>.kit-new, unless --force);
  - always brings the scripts in .claude/testing-kit/ to this version, because they only work as a set
    (one you had changed is saved beside the new one as <name>.yours);
  - remembers the profile and options you chose.
Your .claude/testing-kit.json is kept; settings.json is merged (only the kit's own hook entries are added,
refreshed or removed); CLAUDE.md gets a block between `testing-kit` markers. It never writes through a
symlink, so a skill linked in from elsewhere is never overwritten. docs/GUIDE.md is the manual.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True  # importing the kit's own modules must not leave __pycache__ in the templates

KIT = Path(__file__).resolve().parent
T = KIT / "templates"
VERSION = (KIT / "VERSION").read_text().strip() if (KIT / "VERSION").exists() else "0.0.0"
def _find_python() -> str:
    """The interpreter name hooks will call. Must work from the shell Claude Code uses."""
    candidates = ["py", "python", "python3"] if os.name == "nt" else ["python3", "python"]
    for name in candidates:
        exe = shutil.which(name)
        if not exe:
            continue
        try:
            ok = subprocess.run([exe, "-c", "import sys; sys.exit(sys.version_info < (3, 9))"],
                                capture_output=True, timeout=20).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        if ok:
            return name
    return "python3"


PY = os.environ.get("TESTING_KIT_PYTHON") or _find_python()
MARK_START, MARK_END = "<!-- testing-kit:start", "<!-- testing-kit:end -->"
KIT_HOOK_TAG = ".claude/testing-kit/"
MANIFEST = ".claude/testing-kit/manifest.json"
CONFIG = ".claude/testing-kit.json"
SETTINGS = ".claude/settings.json"

PROFILE_FILES = {
    "minimal": [
        ".claude/testing-kit/kitlib.py", ".claude/testing-kit/protect_tests.py",
        ".claude/testing-kit/guard_bash.py", ".claude/testing-kit/bash_audit.py",
        ".claude/testing-kit/test_report.py", ".claude/testing-kit/test_diff_guard.py",
        ".claude/testing-kit/base_tests.py", ".claude/testing-kit/config_guard.py", ".claude/rules/testing.md",
    ],
}
PROFILE_FILES["standard"] = PROFILE_FILES["minimal"] + [
    ".claude/testing-kit/guard_test_edits.py", ".claude/testing-kit/tests_on_stop.py",
    ".claude/testing-kit/no_src_access.py",
    ".claude/agents/spec-test-writer.md", ".claude/agents/test-reviewer.md",
    ".claude/skills/write-tests/SKILL.md", ".claude/skills/run-tests/SKILL.md",
    ".claude/skills/mutation-check/SKILL.md", ".claude/skills/test-review/SKILL.md",
]
PROFILE_FILES["strict"] = PROFILE_FILES["standard"]
MINIMAL_HOOK_SCRIPTS = {"protect_tests.py", "guard_bash.py", "bash_audit.py", "config_guard.py"}
DOCS = {"docs/testing/GUIDELINES.md": "TESTING-GUIDELINES.md", "docs/testing/REVIEW-PROTOCOL.md": "REVIEW-PROTOCOL.md",
        "docs/testing/KIT-GUIDE.md": "GUIDE.md"}
WORKFLOW = ".github/workflows/testing-kit.yml"
FLAKE_WORKFLOW = ".github/workflows/flake-finder.yml"
OLD_WORKFLOW = ".github/workflows/tests.yml"  # the kit's workflow before 0.4.0; a common name for a repo's own CI
CODEOWNERS_PLACES = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")  # the order GitHub looks in
GITIGNORE_LINES = [".claude/testing-kit/.state/", ".claude/testing-kit/__pycache__/", ".claude/allow-test-edits",
                   ".reports/", ".claude/settings.local.json"]


def _write(path: Path, text: str) -> None:
    """Write with LF line endings on every platform (Path.write_text(newline=) needs Python 3.10)."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def dump_like(data: dict, like: str | None = None) -> str:
    """JSON text in the style of the file it replaces: its indentation, and characters outside ASCII
    written as they are (not as \\u escapes), so the diff shows only what the kit changed."""
    indent = re.search(r"\n([ \t]+)\S", like or "")
    return json.dumps(data, indent=indent.group(1) if indent else 2, ensure_ascii=False) + "\n"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_manifest(root: Path) -> dict:
    """What the last install wrote: {"version", "options", "files": {path: hash}, ...}. {} if none."""
    try:
        data = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def symlinked(dest: Path, root: Path) -> bool:
    p = dest
    while True:
        if p.is_symlink():
            return True
        if p == root or p.parent == p:
            return False
        p = p.parent


class Plan:
    def __init__(self, dry: bool, force: bool, known: dict | None = None, root: Path | None = None):
        self.dry, self.force, self.log, self.root = dry, force, [], root
        self.known: dict = known or {}   # path -> hash of what the last install wrote there
        self.owned: dict = {}            # path -> hash, for the next manifest
        self.touched: set = set()        # every path this run considered

    def note(self, kind: str, path: Path | str, extra: str = "") -> None:
        shown = Path(path)
        if self.root and shown.is_absolute() and self.root in shown.parents:
            shown = shown.relative_to(self.root)  # the header names the repository once
        self.log.append((kind, shown.as_posix() if isinstance(path, Path) else str(path), extra))

    def write(self, dest: Path, text: str, root: Path, script: bool = False) -> None:
        """Write one kit file. A text file you changed is kept (the kit's version goes beside it). A script
        is always brought to this version, because the scripts only work as a set."""
        rel = dest.relative_to(root).as_posix()
        self.touched.add(rel)
        if symlinked(dest, root):
            self.note("SKIP (symlink)", dest, "linked from elsewhere; not overwritten")
            return
        leftover = dest.with_name(dest.name + ".kit-new")
        target = dest
        if dest.exists():
            old = dest.read_text(encoding="utf-8", errors="replace")
            if old == text:
                self.note("same", dest)
                self.owned[rel] = sha(text)
                self._drop(leftover, "merged")
                return
            if self.known.get(rel) == sha(old):
                self.note("update", dest)          # exactly what the last install wrote: safe to replace
            elif self.force:
                self.note("overwrite", dest)
            elif script and not self.known:
                self.note("update", dest, "from an older kit")  # before 0.4.0 there was no install record
            elif script:
                backup = dest.with_name(dest.name + ".yours")
                self.note("REPLACED", dest, f"you changed it; your copy is saved as {backup.name}")
                if not self.dry:
                    _write(backup, old)
            else:
                self.note("CONFLICT", dest, f"yours kept; kit version written to {leftover.name}")
                if rel in self.known:
                    self.owned[rel] = self.known[rel]  # still the kit's file, changed by you
                target = leftover
        else:
            self.note("create", dest)
        if target is dest:
            self.owned[rel] = sha(text)
        if self.dry:
            return
        target.parent.mkdir(parents=True, exist_ok=True)
        _write(target, text)
        if script and os.name != "nt":
            target.chmod(0o755)
        if target is dest:
            self._drop(leftover, "merged")

    def _drop(self, leftover: Path, why: str) -> None:
        if leftover.is_file() and not leftover.is_symlink():
            self.note("remove", leftover, why)
            if not self.dry:
                leftover.unlink()

    def update(self, dest: Path, old: str | None, new: str, root: Path, extra: str) -> None:
        """Write a file the installer merges into (settings.json, CLAUDE.md, .gitignore). `old` is its
        current text, or None if it doesn't exist. Like write(), never goes through a symlink."""
        if old == new:
            self.note("same", dest)
            return
        if symlinked(dest, root):
            self.note("SKIP (symlink)", dest, f"linked from elsewhere; add by hand: {extra}")
            return
        self.note("create" if old is None else "update", dest, extra)
        if not self.dry:
            dest.parent.mkdir(parents=True, exist_ok=True)
            _write(dest, new)

    def remove_stale(self, root: Path) -> None:
        """Kit files from the last install that this one doesn't include (a file the kit dropped, or a
        profile or option you turned off). Only files you haven't changed are removed."""
        for rel, digest in sorted(self.known.items()):
            path = root / rel
            if rel in self.touched or not path.is_file() or symlinked(path, root):
                continue
            if sha(path.read_text(encoding="utf-8", errors="replace")) == digest:
                self.note("remove", path, "no longer part of this install")
                if not self.dry:
                    path.unlink()
                    prune_empty_dirs(path.parent, root)
            else:
                self.note("keep", path, "no longer part of this install, but you changed it")

    def report(self) -> str:
        width = max((len(k) for k, _, _ in self.log), default=6)
        lines = [f"  {k:<{width}}  {p}" + (f"  ({e})" if e else "") for k, p, e in self.log]
        return "\n".join(lines)


def prune_empty_dirs(start: Path, root: Path) -> None:
    p = start
    while p != root and root in p.parents:
        try:
            p.rmdir()  # only succeeds when empty
        except OSError:
            return
        p = p.parent


# ---------------------------------------------------------------- detection

def _python_packages(root: Path) -> list[str]:
    pkgs = [p.name for p in root.iterdir() if p.is_dir() and (p / "__init__.py").exists()
            and not p.name.startswith(("test", ".")) and p.name not in {"docs", "scripts"}]
    return ["src"] if (root / "src").is_dir() else sorted(pkgs)


def looks_like_python(root: Path) -> bool:
    """A Python project without packaging files: runner config, or test files in the usual places."""
    if any((root / f).exists() for f in ("pytest.ini", "tox.ini", "setup.cfg", "conftest.py", "noxfile.py", "Pipfile")):
        return True
    if any(root.glob("test_*.py")) or any(root.glob("*_test.py")):
        return True
    return any(d.is_dir() and (any(d.rglob("test_*.py")) or any(d.rglob("*_test.py")))
               for d in (root / "tests", root / "test"))


def detect(root: Path) -> dict:
    d = {"stack": "unknown", "setup": "", "fast": "", "full": "", "one": "(see your runner's docs)",
         "junit": "", "src_dirs": [], "pm": "", "warnings": [], "cache": False}
    pkg = root / "package.json"
    packaged = any((root / f).exists() for f in ("pyproject.toml", "requirements.txt", "setup.py"))

    def python() -> None:
        d["stack"] = "python"
        uv = (root / "uv.lock").exists()
        d["pm"] = "uv" if uv else "pip"
        run = "uv run " if uv else f"{PY} -m "  # the interpreter name that exists on this machine
        if uv:
            d["setup"] = "uv sync --locked"
        elif (root / "requirements.txt").exists():
            d["setup"] = "pip install -r requirements.txt"
        elif (root / "pyproject.toml").exists() or (root / "setup.py").exists():
            d["setup"] = "pip install -e ."
        d["fast"] = f"{run}pytest -q --junitxml=.reports/junit.xml"
        d["full"] = d["fast"]
        d["junit"] = ".reports/junit.xml"
        d["one"] = f"`{run}pytest path/to/test_file.py::test_name -q`"
        d["src_dirs"] = _python_packages(root)
        # setup-python's pip cache needs one of these files to key on
        d["cache"] = (root / "requirements.txt").exists() or (root / "pyproject.toml").exists()

    if packaged:
        python()
    elif pkg.exists():
        d["stack"] = "node"
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        if (root / "pnpm-lock.yaml").exists():
            d["pm"], d["setup"], x, d["cache"] = "pnpm", "pnpm install --frozen-lockfile", "pnpm exec ", True
        elif (root / "yarn.lock").exists():
            d["pm"], d["setup"], x, d["cache"] = "yarn", "yarn install --frozen-lockfile", "yarn ", True
        else:
            d["pm"], x = "npm", "npx "
            d["cache"] = (root / "package-lock.json").exists()  # setup-node's cache needs a lockfile
            d["setup"] = "npm ci" if d["cache"] else "npm install"
        if "vitest" in deps:
            d["fast"] = f"{x}vitest run --reporter=default --reporter=junit --outputFile.junit=.reports/junit.xml"
            d["one"] = f"`{x}vitest run path/to/file.test.ts -t \"name\"`"
            d["junit"] = ".reports/junit.xml"
        elif "jest" in deps:
            d["fast"] = (f"JEST_JUNIT_OUTPUT_FILE=.reports/junit.xml {x}jest --ci "
                         "--reporters=default --reporters=jest-junit")
            d["one"] = f"`{x}jest path/to/file.test.js -t \"name\"`"
            d["junit"] = ".reports/junit.xml"
            if "jest-junit" not in deps:
                d["warnings"].append("jest-junit is not a devDependency: add it (the fast command, Stop hook "
                                     "and CI gates read its JUnit report)")
        elif data.get("scripts", {}).get("test"):
            d["fast"] = "npm test"
            d["one"] = "`npm test -- <pattern>`"
        d["full"] = d["fast"]
        d["src_dirs"] = [s for s in ("src", "lib", "app") if (root / s).is_dir()]
    elif (root / "go.mod").exists():
        d.update(stack="go", fast="go test ./...", full="go test -race ./...", one="`go test ./pkg -run TestName`",
                 src_dirs=[s for s in ("internal", "pkg", "cmd") if (root / s).is_dir()])
    elif (root / "Cargo.toml").exists():
        d.update(stack="rust", fast="cargo test", full="cargo test --all-features",
                 one="`cargo test test_name`", src_dirs=["src"])
    elif looks_like_python(root):
        python()
    return d


def split_command(command: str, windows: bool = os.name == "nt") -> list:
    """The shell words of a command. On Windows a backslash separates folders; it doesn't escape."""
    words = shlex.split(command, comments=True, posix=not windows)
    if windows:  # non-POSIX splitting keeps the quotes around a word
        words = [w[1:-1] if len(w) > 1 and w[0] == w[-1] and w[0] in "\"'" else w for w in words]
    return words


def runner_indirection(commands: list, root: Path) -> tuple[list, list]:
    """Files the test commands go through (a Makefile, a script), and the npm scripts they call.
    The CI gate takes these from the base branch, so a PR can't redefine what `make test` does."""
    files, scripts = [], []
    pkg_scripts = {}
    try:
        pkg_scripts = json.loads((root / "package.json").read_text(encoding="utf-8")).get("scripts", {})
    except (OSError, ValueError, AttributeError):
        pass
    for command in commands:
        for part in re.split(r"&&|\|\||[;|\n]", command or ""):
            try:
                words = split_command(part)
            except ValueError:
                words = part.split()
            words = [w for w in words if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)]
            if not words:
                continue
            prog = Path(words[0]).name.lower()
            if prog in ("make", "gmake"):
                files += ["Makefile", "makefile", "GNUmakefile", "**/*.mk"]
            elif prog == "just":
                files += ["justfile", "Justfile", ".justfile"]
            elif prog in ("task", "go-task"):
                files += ["Taskfile.yml", "Taskfile.yaml", "Taskfile.dist.yml", "Taskfile.dist.yaml"]
            elif prog in ("npm", "pnpm", "yarn", "bun"):
                args = [w for w in words[1:] if not w.startswith("-")]
                if args and args[0] in ("run", "run-script") and len(args) > 1:
                    name = args[1]
                else:
                    name = args[0] if args else ""
                if name in pkg_scripts:
                    scripts += [name, "pre" + name, "post" + name]
            for w in words:
                rel = Path(w)
                if not w.startswith("-") and not rel.is_absolute() and ".." not in rel.parts and (root / rel).is_file():
                    files.append(rel.as_posix())  # ./scripts/test.sh, tools/run_tests.py, gradlew
    return list(dict.fromkeys(files)), list(dict.fromkeys(scripts))


# ---------------------------------------------------------------- helpers

PLACEHOLDER = re.compile(r"\{\{([A-Z_]+)\}\}")


def fill(text: str, values: dict) -> str:
    """Fill {{NAME}} placeholders in one pass, so a value that happens to contain {{...}} stays as it is."""
    return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)


def settings_fragment() -> dict:
    """The kit's hooks and permissions for .claude/settings.json, with this machine's interpreter name."""
    text = (T / "project" / "settings.fragment.json").read_text(encoding="utf-8")
    return json.loads(fill(text, {"PY": json.dumps(PY)[1:-1]}))  # escaped: a Windows path has backslashes


def md_code(command: str) -> str:
    """A shell command as Markdown code: inline on one line, a fenced block for several lines."""
    command = command.strip()
    if "\n" in command:
        return "\n\n  ```sh\n" + "\n".join("  " + line for line in command.splitlines()) + "\n  ```"
    ticks = "`" * (max((len(run) for run in re.findall(r"`+", command)), default=0) + 1)
    pad = " " if command.startswith("`") or command.endswith("`") else ""
    return f"{ticks}{pad}{command}{pad}{ticks}"


def yaml_block(command: str, indent: str) -> str:
    """The body of a YAML block scalar (`run: |`), so any shell command is valid in a workflow."""
    return ("\n" + indent).join(line.rstrip() for line in command.strip().splitlines())


def kit_hook(h: dict) -> bool:
    return KIT_HOOK_TAG in str(h.get("command", ""))


def merge_settings(existing: dict, fragment: dict, keep_scripts: set | None) -> dict:
    out = json.loads(json.dumps(existing))
    hooks = out.setdefault("hooks", {})
    for event in list(dict.fromkeys([*fragment.get("hooks", {}), *hooks])):
        groups = fragment.get("hooks", {}).get(event, [])
        before = hooks.get(event) if isinstance(hooks.get(event), list) else []
        current = []
        for g in before:  # yours stay; the kit's own entries are replaced by this version's
            mine = [h for h in g.get("hooks", []) if not kit_hook(h)]
            if mine or not g.get("hooks"):
                current.append({**g, "hooks": mine} if len(mine) != len(g.get("hooks", [])) else g)
        if current == before and not groups:
            continue  # an event the kit has nothing to do with
        for g in groups:
            g = json.loads(json.dumps(g))
            if keep_scripts is not None:
                g["hooks"] = [h for h in g["hooks"] if any(s in h["command"] for s in keep_scripts)]
            if g["hooks"]:
                current.append(g)
        if current:
            hooks[event] = current
        else:
            hooks.pop(event, None)  # e.g. Stop after switching to the minimal profile
    for key, value in fragment.items():
        if key not in ("hooks", "permissions"):
            out[key] = value
    perms = out.setdefault("permissions", {})
    for key, values in fragment.get("permissions", {}).items():
        merged = list(perms.get(key, []))
        merged += [v for v in values if v not in merged]
        perms[key] = merged
    return out


def strip_settings(settings: dict, record: dict, fragment: dict) -> dict:
    """Undo merge_settings: the kit's hook entries, and the permissions and keys it added."""
    out = json.loads(json.dumps(settings))
    hooks = out.get("hooks")
    if isinstance(hooks, dict):
        for event in list(hooks):
            groups = []
            for g in hooks[event] if isinstance(hooks[event], list) else []:
                kept = [h for h in g.get("hooks", []) if not kit_hook(h)]
                if kept:
                    groups.append({**g, "hooks": kept})
            if groups:
                hooks[event] = groups
            else:
                del hooks[event]
        if not hooks:
            del out["hooks"]
    perms = out.get("permissions")
    if isinstance(perms, dict) and isinstance(perms.get("deny"), list):
        added = set(record.get("deny_added") or [])
        perms["deny"] = [v for v in perms["deny"] if v not in added]
        if not perms["deny"]:
            del perms["deny"]
        if not perms:
            del out["permissions"]
    for key in record.get("keys_added") or []:
        if key in out and out[key] == fragment.get(key):
            del out[key]
    return out


def update_claude_md(path: Path, block: str) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if MARK_START in text and MARK_END in text:
        start = text.index(MARK_START)
        end = text.index(MARK_END) + len(MARK_END)
        return text[:start] + block.strip() + text[end:]
    sep = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + sep + block.strip() + "\n"


def remove_claude_block(text: str) -> str:
    if MARK_START not in text or MARK_END not in text:
        return text
    start = text.index(MARK_START)
    end = text.index(MARK_END) + len(MARK_END)
    before, after = text[:start].rstrip("\n"), text[end:].lstrip("\n")
    if before and after:
        return before + "\n\n" + after
    return (before + "\n") if before else after


def ensure_lines(path: Path, lines: list) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = [l for l in lines if l not in text.splitlines()]
    if not missing:
        return text
    if text and not text.endswith("\n"):
        text += "\n"
    return text + "# testing kit\n" + "\n".join(missing) + "\n"


def run_step(command: str) -> list:
    """A workflow `run:` step as a block scalar, so any shell command is valid YAML."""
    return ["- run: |"] + ["    " + line.rstrip() for line in command.strip().splitlines()]


def ci_values(det: dict, cmds: dict) -> dict:
    """The workflow's toolchain and dependency steps, matched to the detected stack and package manager."""
    pad = "      "
    setup = (cmds.get("setup") or "").strip()
    stack, pm = det["stack"], det["pm"]
    steps, flake, coverage, label = [], "", "coverage.xml", stack
    if stack == "python" and pm == "uv":
        steps = ["- uses: astral-sh/setup-uv@v7", "  with: {enable-cache: true}"]
        flake = "uv run --with pytest-repeat --with pytest-randomly pytest"
        label = "Python, uv"
    elif stack == "python":
        cache = ", cache: pip" if det.get("cache") else ""
        steps = ["- uses: actions/setup-python@v6", "  with: {python-version: '3.12'" + cache + "}"]
        setup = "python -m pip install pytest" + (f" && {setup}" if setup else "")
        flake = "python -m pip install pytest-repeat pytest-randomly && python -m pytest"
        label = "Python, pip"
    elif stack == "node":
        steps = ["- run: corepack enable"] if pm in ("pnpm", "yarn") else []
        cache = ", cache: " + pm if det.get("cache") else ""
        steps += ["- uses: actions/setup-node@v5", "  with: {node-version: lts/*" + cache + "}"]
        coverage = "coverage/cobertura-coverage.xml"
        label = f"Node, {pm}"
    elif stack == "go":
        steps = ["- uses: actions/setup-go@v6", "  with: {go-version-file: go.mod}"]
        label = "Go"
    elif stack == "rust":
        steps = ["# Rust (stable) and cargo are preinstalled on GitHub's Linux runners."]
        label = "Rust"
    else:
        label = "set up by hand"
        if not setup:
            steps = ["# Add the steps that install your toolchain and dependencies here (nothing was detected)."]
    if setup:
        steps += run_step(setup)
    return {"CI_SETUP": ("\n" + pad).join(steps), "FLAKE_RUN": flake, "COVERAGE_XML": coverage, "STACK": label}


def docs_dir() -> Path | None:
    """The kit's own docs, next to the installer. They are copied into the repo as they are."""
    return KIT / "docs" if (KIT / "docs" / "TESTING-GUIDELINES.md").exists() else None


_KITLIB = None


def kitlib():
    """The hooks' own library (defaults, path matching), loaded from the templates."""
    global _KITLIB
    if _KITLIB is None:
        spec = importlib.util.spec_from_file_location("testing_kit_kitlib",
                                                      T / "project" / ".claude" / "testing-kit" / "kitlib.py")
        _KITLIB = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_KITLIB)
    return _KITLIB


def default_sections(file: str) -> list:
    """The kit's built-in protected sections for a shared manifest (from the hooks' own defaults)."""
    return list(kitlib().DEFAULT_CONFIG["harness_sections"].get(file, []))


def git_out(root: Path, *args: str) -> str | None:
    """Output of a git command in `root`, or None when git isn't there or says no."""
    try:
        out = subprocess.run(["git", "-c", "core.quotepath=off", *args], cwd=root, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout if out.returncode == 0 else None


def placement_warnings(root: Path) -> list:
    """The kit belongs at the root of a git repository: the hooks and the CI gates compare files with git."""
    top = (git_out(root, "rev-parse", "--show-toplevel") or "").strip()
    if not top:
        return [f"{root} is not a git repository. The rules and edit protections work, but the end-of-turn hook "
                "can't tell what a session changed (so it runs the tests every time Claude stops) and the CI "
                "gates need git. Run `git init` and commit first."]
    try:
        same = os.path.samefile(top, root)
    except OSError:
        same = Path(top).resolve() == root
    if not same:
        return [f"{root} is inside the git repository {top}. The kit is built to sit at the repository root: "
                "the CI gates read .claude/testing-kit.json there, and the hooks compare files with git from "
                'there. Install at the root and point the commands into this folder (--fast "cd <folder> && ...").']
    return []


SKIP_DIRS = {"node_modules", "venv", "target", "dist", "build", "vendor", "__pycache__"}  # not walked without git
NOT_THE_REPOS = {"node_modules", "site-packages", "__pycache__"}  # installed packages and bytecode, wherever they are


def recognised_tests(root: Path) -> list:
    """The repo's own files that the kit treats as tests, with this repo's config. The kit's scripts,
    installed packages and bytecode don't count; ignored files are left out when git can say which they are."""
    k = kitlib()
    k._load_config.cache_clear()
    cfg = k.load_config(root)
    listing = git_out(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard")
    if listing is not None:
        files = listing.split("\0")
    else:
        files = []
        for folder, dirs, names in os.walk(root):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            files += [(Path(folder) / n).relative_to(root).as_posix() for n in names]
            if len(files) > 50000:
                break
    return sorted(f for f in files if f and not f.startswith(".claude/")
                  and not NOT_THE_REPOS.intersection(f.split("/")) and k.is_test_path(f, cfg))


def tests_line(root: Path) -> str:
    found = recognised_tests(root)
    if not found:
        return ("No test files are recognised in this repo yet. Tests are recognised by where they are and what "
                "they are called (tests/, test/, __tests__/, test_*.py, *_test.go, *.test.*, *.spec.*, ...). If "
                "this repo keeps tests somewhere else, list their patterns under extra_test_globs in "
                ".claude/testing-kit.json, or the kit won't protect them.")
    return f"test files recognised: {len(found)} ({', '.join(found[:3])}{', ...' if len(found) > 3 else ''})"


def codeowners_path(root: Path) -> str:
    """Where this repo keeps CODEOWNERS. GitHub reads only the first place that has one, so a new file in
    .github/ would silently switch off the rules in a CODEOWNERS kept at the root or in docs/."""
    return next((rel for rel in CODEOWNERS_PLACES if (root / rel).is_file()), CODEOWNERS_PLACES[0])


def quote(path: Path | str) -> str:
    return f'"{path}"' if " " in str(path) else str(path)


# ---------------------------------------------------------------- project install

def resolve_options(a: argparse.Namespace, manifest: dict) -> dict:
    """Flags given now win; otherwise what the last install used; otherwise the defaults."""
    last = manifest.get("options") or {}
    return {
        "profile": a.profile or last.get("profile") or "standard",
        "ci": a.ci if a.ci is not None else bool(last.get("ci")),
        "env": a.env if a.env is not None else bool(last.get("env")),
        "owner": a.owner if a.owner is not None else (last.get("owner") or ""),
    }


def load_config(root: Path) -> dict | None:
    path = root / CONFIG
    if not path.exists():
        return None
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict):
            raise ValueError("not a JSON object")
    except ValueError as exc:
        raise SystemExit(f"{path} is not valid JSON ({exc}). Fix it (or delete it to start again from the "
                         "detected defaults) and re-run; nothing was changed.")
    return cfg


def protect_runner(cfg: dict, commands: dict, root: Path) -> list:
    """Record the files and npm scripts the test commands go through. Returns what was added."""
    files, scripts = runner_indirection([commands.get("fast"), commands.get("full")], root)
    added = []
    have = cfg.get("runner_files") or []
    new_files = [f for f in files if f not in have]
    if new_files or "runner_files" not in cfg:
        cfg["runner_files"] = have + new_files
        added += new_files
    if scripts:
        sections = cfg.setdefault("harness_sections", {})
        current = sections.get("package.json") or default_sections("package.json")
        wanted = [f"scripts.{s}" for s in scripts]
        new_sections = [s for s in wanted if s not in current]
        if new_sections:
            sections["package.json"] = current + new_sections
            added += [f"package.json {s}" for s in new_sections]
    return added


def install_project(root: Path, a: argparse.Namespace) -> Plan:
    manifest = load_manifest(root)
    opts = resolve_options(a, manifest)
    profile = opts["profile"]
    plan = Plan(a.dry_run, a.force, manifest.get("files") or {}, root)
    plan.options, plan.manifest = opts, manifest
    plan.legacy = not manifest and (root / ".claude/testing-kit/kitlib.py").exists()  # installed before 0.4.0
    det = detect(root)
    existing_cfg = load_config(root)
    saved = (existing_cfg or {}).get("commands") or {}
    # Both files the installer merges into are read before anything is written, so a broken one stops
    # the run with the repo untouched.
    settings_path = root / SETTINGS
    settings_text = settings_path.read_text(encoding="utf-8") if settings_path.exists() else None
    try:
        existing = json.loads(settings_text) if settings_text and settings_text.strip() else {}
        if not isinstance(existing, dict):
            raise ValueError("not a JSON object")
    except ValueError as exc:
        raise SystemExit(f"{settings_path} is not valid JSON ({exc}). Fix it and re-run; nothing was changed.")

    # Commands: a flag given now wins, then what is already in the config, then detection.
    cmds, source = {}, {}
    for key in ("setup", "fast", "full"):
        flag = getattr(a, key)
        if flag is not None:
            cmds[key], source[key] = flag.strip(), "flag"
        elif existing_cfg is not None and (saved.get(key) or key == "setup"):
            cmds[key], source[key] = str(saved.get(key) or "").strip(), "config"
        else:
            cmds[key], source[key] = det[key], "detected"
    if a.fast is not None and a.full is None and not cmds["full"]:
        cmds["full"] = a.fast  # one command given for an undetected stack: it is the full tier too
    plan.commands, plan.source = cmds, source

    tier = a.tier or ("medium" if profile == "strict" else "low")
    base = kitlib().default_base(root, fallback="")  # origin/main, origin/master, main, ... or "" when unknown
    if existing_cfg is not None:
        junit = existing_cfg.get("junit_path", ".reports/junit.xml") or ""
    else:  # a new config: the detected commands write this report; a command of your own may not
        junit = ".reports/junit.xml" if ".reports/junit.xml" in cmds["fast"] else ""
    report_dir = (Path(junit).parent.as_posix() if junit else ".reports").rstrip("/") + "/"
    values = {"PY": PY, "FAST": md_code(cmds["fast"]) if cmds["fast"] else "not set yet (`commands.fast` in "
                                "`.claude/testing-kit.json`)",
              "FULL": md_code(cmds["full"]) if cmds["full"] else "not set",
              "ONE": det["one"], "TIER": tier, "OWNER": opts["owner"].lstrip("@") or "OWNER",
              "REPORT_DIR": report_dir, **ci_values(det, cmds), "FAST_YAML": yaml_block(cmds["fast"], " " * 10),
              "BASE": base or "origin/main", "BRANCHES": base.split("/", 1)[-1] if base else "main, master"}

    for rel in PROFILE_FILES[profile]:
        src = T / "project" / rel
        plan.write(root / rel, fill(src.read_text(encoding="utf-8"), values), root, script=rel.endswith(".py"))

    # ---- .claude/testing-kit.json: created once, then yours. Later runs only touch what you asked for.
    cfg_path = root / CONFIG
    plan.touched.add(CONFIG)
    if existing_cfg is None:
        cfg = json.loads((T / "project" / "testing-kit.json").read_text(encoding="utf-8"))
        cfg["commands"].update(setup=cmds["setup"], fast=cmds["fast"], full=cmds["full"])
        cfg.update(junit_path=junit, src_dirs=det["src_dirs"] or ["src"], default_tier=tier)
        if profile == "strict":
            cfg["enforcement"] = "deny"
        if profile == "minimal":
            cfg["stop_hook"]["enabled"] = False
        protect_runner(cfg, cmds, root)
        plan.note("create", cfg_path)
        if not plan.dry:
            cfg_path.parent.mkdir(parents=True, exist_ok=True)
            _write(cfg_path, dump_like(cfg))
    else:
        cfg = json.loads(json.dumps(existing_cfg))
        changed = []
        for key in ("setup", "fast", "full"):
            if (cfg.get("commands") or {}).get(key, "") != cmds[key] and source[key] != "config":
                cfg.setdefault("commands", {})[key] = cmds[key]
                changed.append(f"commands.{key}")
        if changed:
            changed += protect_runner(cfg, cmds, root)
        last_profile = (manifest.get("options") or {}).get("profile")
        if a.profile and last_profile and a.profile != last_profile:
            cfg["enforcement"] = "deny" if profile == "strict" else "ask"
            cfg.setdefault("stop_hook", {})["enabled"] = profile != "minimal"
            cfg["default_tier"] = tier
            changed.append(f"profile {last_profile} -> {profile}: enforcement, stop_hook, default_tier")
        elif a.tier and cfg.get("default_tier") != a.tier:
            cfg["default_tier"] = a.tier
            changed.append("default_tier")
        if changed:
            plan.note("update", cfg_path, ", ".join(changed))
            if not plan.dry:
                _write(cfg_path, dump_like(cfg, _read(cfg_path)))
        else:
            plan.note("keep", cfg_path, "your config")
    block_values = {**values, "TIER": cfg.get("default_tier") or tier}

    # ---- .claude/settings.json: merged
    fragment = settings_fragment()
    keep = set(MINIMAL_HOOK_SCRIPTS) if profile == "minimal" else None
    if opts["env"]:
        fragment["hooks"].setdefault("SessionStart", []).append({"matcher": "startup|resume", "hooks": [
            {"type": "command", "command": 'bash "${CLAUDE_PROJECT_DIR}/.claude/testing-kit/session_start.sh"',
             "timeout": 600}]})
        if keep is not None:
            keep.add("session_start.sh")
        plan.write(root / ".claude/testing-kit/session_start.sh",
                   (T / "env" / "session_start.sh").read_text(encoding="utf-8"), root, script=True)
    merged = merge_settings(existing, fragment, keep)
    unchanged = merged == existing and settings_text is not None
    plan.update(settings_path, settings_text, settings_text if unchanged else dump_like(merged, settings_text),
                root, "kit hooks and permissions")
    before = manifest.get("settings") or {}
    plan.settings = {
        "created": before.get("created", settings_text is None),
        "deny_added": sorted(set(before.get("deny_added") or []) | {
            v for v in fragment.get("permissions", {}).get("deny", [])
            if v not in (existing.get("permissions") or {}).get("deny", [])}),
        "keys_added": sorted(set(before.get("keys_added") or []) | {
            k for k in fragment if k not in ("hooks", "permissions") and k not in existing}),
    }

    # ---- CLAUDE.md: one marked block
    block = fill((T / "project" / "CLAUDE-block.md").read_text(encoding="utf-8"), block_values)
    block = re.sub(r"[ \t]+\n", "\n", block)  # a command shown as a fenced block starts on its own line
    claude_md = root / "CLAUDE.md"
    old_md = claude_md.read_text(encoding="utf-8") if claude_md.exists() else None
    plan.update(claude_md, old_md, update_claude_md(claude_md, block), root, "## Testing block")
    plan.claude_md_created = manifest.get("claude_md_created", old_md is None)

    docs = docs_dir()
    plan.touched.update(DOCS)  # a doc that can't be refreshed is left as it is, not treated as stale
    if docs:
        for dest, name in DOCS.items():
            if (docs / name).exists():
                plan.write(root / dest, (docs / name).read_text(encoding="utf-8"), root)
    else:
        plan.note("MISSING", "docs/testing/GUIDELINES.md", "kit docs not found next to the installer")

    gi = root / ".gitignore"
    plan.update(gi, gi.read_text(encoding="utf-8") if gi.exists() else None, ensure_lines(gi, GITIGNORE_LINES),
                root, "kit ignores")

    # ---- CI
    plan.workflow = False
    old_workflow = root / OLD_WORKFLOW
    if plan.legacy and (_read(old_workflow) or "").startswith("# Testing kit CI") and not symlinked(old_workflow, root):
        plan.note("remove", old_workflow, f"the kit's workflow is now {Path(WORKFLOW).name}")
        if not plan.dry:
            old_workflow.unlink()
    if opts["ci"]:
        if cmds["fast"]:
            plan.write(root / WORKFLOW, fill((T / "ci" / "testing-kit.yml").read_text(encoding="utf-8"), values), root)
            plan.workflow = True
            if det["stack"] == "python":
                plan.write(root / FLAKE_WORKFLOW,
                           fill((T / "ci" / "flake-finder.yml").read_text(encoding="utf-8"), values), root)
        else:
            plan.touched.update({WORKFLOW, FLAKE_WORKFLOW})
            plan.note("SKIP", WORKFLOW, 'no test command yet: re-run with --fast "<command>" to get the workflow')
        if opts["owner"]:
            plan.write(root / codeowners_path(root),
                       fill((T / "ci" / "CODEOWNERS").read_text(encoding="utf-8"), values), root)
        else:
            plan.note("SKIP", ".github/CODEOWNERS", "pass --owner @you-or-team to protect the test harness")
    elif a.owner:
        plan.note("SKIP", ".github/CODEOWNERS", "--owner is used with --ci")

    plan.remove_stale(root)

    # ---- the manifest: what this install wrote, for the next upgrade, --check and --uninstall
    new_manifest = {"version": VERSION, "options": opts, "files": dict(sorted(plan.owned.items())),
                    "settings": plan.settings, "claude_md_created": plan.claude_md_created}
    manifest_text = dump_like(new_manifest)
    manifest_path = root / MANIFEST
    if _read(manifest_path) != manifest_text:
        plan.note("update" if manifest_path.exists() else "create", manifest_path)
        if not plan.dry:
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            _write(manifest_path, manifest_text)
    else:
        plan.note("same", manifest_path)

    plan.detected, plan.junit = det, junit
    return plan


def install_user(home: Path, a: argparse.Namespace) -> Plan:
    plan = Plan(a.dry_run, a.force, root=home)
    base = home / ".claude"
    plan.write(base / "rules/testing-habits.md", (T / "user/rules/testing-habits.md").read_text(encoding="utf-8"), home)
    plan.write(base / "agents/test-reviewer.md", (T / "user/agents/test-reviewer.md").read_text(encoding="utf-8"), home)
    sp = base / "settings.json"
    sp_text = sp.read_text(encoding="utf-8") if sp.exists() else None
    try:
        existing = json.loads(sp_text) if sp_text and sp_text.strip() else {}
    except ValueError as exc:
        raise SystemExit(f"{sp} is not valid JSON ({exc}). Fix it and re-run.")
    allow = ["Bash(pytest *)", "Bash(python -m pytest *)", "Bash(python3 -m pytest *)", "Bash(uv run pytest *)",
             "Bash(npm test *)",
             "Bash(npx vitest run *)", "Bash(npx jest *)", "Bash(go test *)", "Bash(cargo test *)"]
    merged = merge_settings(existing, {"permissions": {"allow": allow}}, None)
    if not merged.get("hooks"):
        merged.pop("hooks", None)
    unchanged = merged == existing and sp_text is not None
    plan.update(sp, sp_text, sp_text if unchanged else dump_like(merged, sp_text), home,
                "test commands allowed")
    return plan


# ---------------------------------------------------------------- check

SHELL_WORDS = {".", "source", "cd", "export", "set", "unset", "if", "for", "while", "until", "case", "time",
               "exec", "eval", "test", "[", "[[", "!", "{", "(", "true", "false", "echo", "printf", "command",
               "builtin", "trap", "ulimit", "umask", "pushd", "popd", "call"}
PYTHON_NAME = re.compile(r"(?:python|pypy)[\d.]*(?:\.exe)?|py(?:\.exe)?", re.I)


def fast_command_problems(fast: str, root: Path) -> list:
    """Can the fast command start? Looks only at its first program (and, for `python -m X`, the module);
    it doesn't run anything. A command that starts with shell syntax is left for --run to judge."""
    try:
        words = split_command(fast)
    except ValueError:
        return []
    while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        words.pop(0)  # VAR=value in front of the program
    if not words or not words[0] or words[0] in SHELL_WORDS or words[0][0] in "({$`":
        return []
    prog = exe = words[0]
    if "/" in prog or os.sep in prog:  # a script or interpreter given by path: looked up from the repo
        target = Path(prog) if Path(prog).is_absolute() else root / prog
        names = [target] + ([target.with_name(target.name + ext) for ext in (".bat", ".cmd", ".exe", ".ps1")]
                            if os.name == "nt" else [])
        found = next((n for n in names if n.is_file()), None)
        if found is None:
            return [f"`{prog}` (from commands.fast) does not exist"]
        if os.name != "nt" and not os.access(found, os.X_OK):
            return [f"`{prog}` (from commands.fast) is not executable: `chmod +x` it, or call it through its "
                    "interpreter"]
        exe = str(found)
    elif not shutil.which(prog):
        return [f"`{prog}` (from commands.fast) is not on PATH"]
    if (PYTHON_NAME.fullmatch(Path(prog).name) and len(words) > 2 and words[1] == "-m"
            and re.fullmatch(r"[A-Za-z_][\w.]*", words[2])):
        r = subprocess.run([exe, "-c", f"import {words[2]}"], cwd=root, capture_output=True, text=True)
        if r.returncode != 0:
            return [f"`{prog} -m {words[2]}` can't run here: {words[2]} is not installed for `{prog}`. "
                    "Install it, start from the environment that has it (an activated virtualenv), or point "
                    "commands.fast at that interpreter"]
    return []


def out_of_step(root: Path, cfg: dict) -> list:
    """Files the installer writes from the config that no longer show the config's fast command."""
    fast = str((cfg.get("commands") or {}).get("fast") or "").strip()
    notes = []
    md = _read(root / "CLAUDE.md") or ""
    if fast and MARK_START in md and md_code(fast) not in md:
        notes.append("CLAUDE.md's Testing block shows another fast command than .claude/testing-kit.json: "
                     "re-run the installer to refresh it")
    workflow = _read(root / WORKFLOW)
    if fast and workflow is not None and yaml_block(fast, " " * 10) not in workflow:
        notes.append(f"{WORKFLOW} runs another fast command than .claude/testing-kit.json: "
                     "re-run the installer (it updates the workflow unless you have edited it)")
    return notes


def run_fast_tier(root: Path, cfg: dict) -> tuple[list, list]:
    """--check --run: run the fast tier once, as the Stop hook would. Returns (problems, notes)."""
    import xml.etree.ElementTree as ET
    problems, notes = [], []
    fast = (cfg.get("commands") or {}).get("fast", "")
    timeout = int((cfg.get("stop_hook") or {}).get("timeout_s", 300))
    junit_path = cfg.get("junit_path", ".reports/junit.xml") or ""
    junit = root / junit_path if junit_path else None
    if junit:
        try:
            junit.unlink()  # only a report written by this run counts
        except OSError:
            pass
    started = time.monotonic()
    try:
        proc = subprocess.run(fast, shell=True, cwd=root, capture_output=True, text=True, errors="replace",
                              timeout=timeout)
        rc, output = proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired:
        rc, output = 124, ""
        problems.append(f"the fast tier did not finish in {timeout}s (stop_hook.timeout_s): point commands.fast "
                        "at a quicker subset, or raise the limit")
    took = time.monotonic() - started
    notes.append(f"fast tier ran in {took:.0f}s (exit {rc}). The Stop hook runs it when Claude has changed "
                 "something and tries to finish.")
    if took > 120:
        notes.append("that is slow for a check at the end of a turn: consider a quicker subset for "
                     "commands.fast and keep the whole suite in commands.full")
    if rc not in (0, 124):
        tail = "\n".join("      " + l for l in output.strip().splitlines()[-12:])
        problems.append(f"the fast tier fails here (exit {rc}). Get it green first: on a red suite Claude is "
                        f"pushed to fix failures it didn't cause.\n{tail}")
    if junit and rc != 124:
        if not junit.is_file():
            problems.append(f"the fast tier wrote no JUnit report to {junit_path}. Add the reporter to "
                            'commands.fast, or set "junit_path": "" so the CI gate compares exit codes instead')
        else:
            try:
                count = sum(1 for _ in ET.parse(junit).getroot().iter("testcase"))
            except ET.ParseError as exc:
                count = -1
                problems.append(f"{junit_path} is not valid JUnit XML ({exc})")
            if count == 0:
                problems.append(f"{junit_path} lists no tests: check that the command collects your tests")
            elif count > 0:
                notes.append(f"JUnit report at {junit_path}: {count} tests")
    elif not junit:
        notes.append("no junit_path: the CI gate compares exit codes, and reports show the runner's own output")
    return problems, notes


def check(root: Path, run: bool = False) -> int:
    problems, notes = [], []
    manifest = load_manifest(root)
    if manifest:
        opts = manifest.get("options") or {}
        notes.append(f"installed: testing kit {manifest.get('version')}, {opts.get('profile', '?')} profile"
                     + (", with CI" if opts.get("ci") else ""))
        if manifest.get("version") != VERSION:
            notes.append(f"this installer is {VERSION}: run `{PY} {quote(Path(__file__).resolve())} --project "
                         f"{quote(root)}` to move the repo to it")
        changed, gone = [], []
        for rel, digest in (manifest.get("files") or {}).items():
            text = _read(root / rel)
            if text is None:
                gone.append(rel)
            elif sha(text) != digest:
                changed.append(rel)
        if changed:
            notes.append("changed since the install (kept as yours on upgrade): " + ", ".join(changed))
        for rel in gone:
            if rel not in PROFILE_FILES["minimal"]:
                notes.append(f"{rel} was installed and is gone (re-run the installer to restore it)")
    else:
        notes.append("no install manifest (.claude/testing-kit/manifest.json): installed by a version before "
                     "0.4.0, or not installed. Re-run the installer to create one")
    for rel in PROFILE_FILES["minimal"]:
        if not (root / rel).exists():
            problems.append(f"missing {rel}")
    pending = sorted({p.relative_to(root).as_posix() for base in (".claude", "docs/testing", ".github")
                      if (root / base).is_dir() for p in (root / base).rglob("*.kit-new")}
                     | {rel + ".kit-new" for rel in CODEOWNERS_PLACES if (root / (rel + ".kit-new")).is_file()})
    if pending:
        notes.append("kit versions beside files of yours (merge what you want, then delete them): "
                     + ", ".join(pending))
    saved = sorted(p.relative_to(root).as_posix() for p in (root / ".claude/testing-kit").glob("*.yours"))
    if saved:
        notes.append("your copies of kit scripts that an upgrade replaced (re-apply what you still need, then "
                     "delete them): " + ", ".join(saved))
    sp = root / SETTINGS
    try:
        settings = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        settings = {}
        problems.append(f"cannot read {sp}: {exc}")
    hooks = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
    commands = [str(h.get("command", "")) for groups in hooks.values() for g in groups for h in g.get("hooks", [])]
    if not any("protect_tests.py" in c for c in commands):
        problems.append("protect_tests.py hook not registered in .claude/settings.json")
    if settings.get("disableAllHooks") is True:
        problems.append('"disableAllHooks": true in .claude/settings.json: no hook runs')
    for name in sorted({m for c in commands if KIT_HOOK_TAG in c for m in re.findall(r"testing-kit/([\w.-]+\.(?:py|sh))", c)}):
        if not (root / ".claude/testing-kit" / name).exists():
            problems.append(f"{name} is registered as a hook but the file is missing: Claude Code blocks every "
                            "edit and shell command while that is so. Re-run the installer, or uninstall")
    if not shutil.which(PY):
        problems.append(f"`{PY}` is not on PATH, so the hooks can't run")
    elif (root / ".claude/testing-kit/protect_tests.py").exists():
        probe = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(root / "README.md"),
                                                               "old_string": "x", "new_string": "y"},
                            "cwd": str(root), "session_id": "kit-check"})
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
        r = subprocess.run([PY, str(root / ".claude/testing-kit/protect_tests.py")], input=probe, text=True,
                           capture_output=True, env=env)
        for leftover in (root / ".claude/testing-kit/.state").glob("kit-check.*"):
            leftover.unlink()
        if r.returncode != 0:
            problems.append(f"protect_tests.py failed on a probe: {r.stderr.strip()[:200]}")
    try:
        cfg = json.loads((root / CONFIG).read_text(encoding="utf-8"))
        fast = (cfg.get("commands") or {}).get("fast", "")
        if not fast:
            problems.append('commands.fast is empty in .claude/testing-kit.json (the Stop hook and CI gates need '
                            'it): set it there, or re-run the installer with --fast "<command>"')
        else:
            notes.append(f"fast tier: {fast}")
            notes += out_of_step(root, cfg)
            found = fast_command_problems(fast, root)
            problems += found
            if run and not found:
                more_problems, more_notes = run_fast_tier(root, cfg)
                problems += more_problems
                notes += more_notes
        notes.append(tests_line(root))
    except (OSError, ValueError):
        problems.append("missing or invalid .claude/testing-kit.json")
    print(f"Testing kit check for {root}")
    for n in notes:
        print(f"  {n}")
    if problems:
        print("Testing kit check found problems:\n" + "\n".join(f"  - {p}" for p in problems))
        return 1
    print("Testing kit check: OK" + ("" if run else " (add --run to run the fast tier once and time it)"))
    return 0


# ---------------------------------------------------------------- uninstall

def uninstall(root: Path, dry: bool) -> int:
    """Take the kit out of a repo: hooks first (so no session is left calling a missing script), then the
    CLAUDE.md block, then every kit file you haven't changed."""
    manifest = load_manifest(root)
    plan = Plan(dry, False, root=root)
    fragment = settings_fragment()

    sp = root / SETTINGS
    text = _read(sp)
    if text is not None:
        try:
            settings = json.loads(text) if text.strip() else {}
            if not isinstance(settings, dict):
                raise ValueError("not a JSON object")
        except ValueError as exc:
            plan.note("SKIP", sp, f"not valid JSON ({exc}): remove the testing-kit hook entries by hand")
        else:
            record = manifest.get("settings") or {}
            stripped = strip_settings(settings, record, fragment)
            if symlinked(sp, root):
                plan.note("SKIP (symlink)", sp, "linked from elsewhere; remove the testing-kit hook entries by hand")
            elif stripped == settings:
                plan.note("same", sp, "no kit hooks in it")
            elif not stripped and record.get("created"):
                plan.note("remove", sp, "the kit created it and nothing else is in it")
                if not dry:
                    sp.unlink()
            else:
                plan.note("update", sp, "kit hooks and permissions removed")
                if not dry:
                    _write(sp, dump_like(stripped, text))

    md = root / "CLAUDE.md"
    text = _read(md)
    if text is not None and MARK_START in text and MARK_END in text:
        rest = remove_claude_block(text)
        if symlinked(md, root):
            plan.note("SKIP (symlink)", md, "linked from elsewhere; remove the testing-kit block by hand")
        elif not rest.strip() and manifest.get("claude_md_created"):
            plan.note("remove", md, "the kit created it and nothing else is in it")
            if not dry:
                md.unlink()
        else:
            plan.note("update", md, "## Testing block removed")
            if not dry:
                _write(md, rest)

    files = manifest.get("files") or {}
    kept = []
    for rel, digest in sorted(files.items()):
        path = root / rel
        if not path.is_file() or symlinked(path, root):
            continue
        if sha(path.read_text(encoding="utf-8", errors="replace")) == digest:
            plan.note("remove", path)
            if not dry:
                path.unlink()
        else:
            plan.note("keep", path, "you changed it: delete it yourself if you don't want it")
            kept.append(rel)
    known = (set(files) | set(PROFILE_FILES["standard"]) | set(DOCS) | set(CODEOWNERS_PLACES)
             | {CONFIG, WORKFLOW, FLAKE_WORKFLOW})
    for rel in sorted(known):
        leftover = root / (rel + ".kit-new")
        if leftover.is_file() and not symlinked(leftover, root):
            plan.note("remove", leftover)
            if not dry:
                leftover.unlink()
    if not manifest:
        present = [rel for rel in sorted(set(PROFILE_FILES["standard"]) | set(DOCS)) if (root / rel).is_file()]
        if present:
            plan.note("keep", root / ".claude/testing-kit", "no install manifest (installed before 0.4.0), so "
                      "the installer can't tell which files you changed. Delete by hand: " + ", ".join(present))
            kept += present
    for path in sorted((root / ".claude/testing-kit").glob("*.yours")):
        plan.note("keep", path, "your copy of a kit script: delete it yourself")
    for rel, why in ((CONFIG, "the kit's config"), (MANIFEST, "")):
        path = root / rel
        if path.is_file() and not symlinked(path, root):
            plan.note("remove", path, why)
            if not dry:
                path.unlink()
    for rel in (".claude/testing-kit/.state", ".claude/testing-kit/__pycache__"):
        path = root / rel
        if path.is_dir() and not symlinked(path, root):
            plan.note("remove", path, "session state" if rel.endswith(".state") else "")
            if not dry:
                shutil.rmtree(path, ignore_errors=True)
    if not dry:
        for rel in sorted(known | {MANIFEST, ".claude/testing-kit/x"}):
            prune_empty_dirs((root / rel).parent, root)

    print(f"Testing kit {VERSION}: uninstall from {root}{' (dry run)' if dry else ''}")
    print(plan.report() or "  nothing to remove: the kit doesn't seem to be installed here")
    print("\nLeft alone: .gitignore (the kit's lines are harmless) and anything marked keep.")
    print("\nNext steps:")
    print("  1. Restart any running Claude Code session in this repo. A session started earlier still calls "
          "the removed hook scripts, and blocks every edit and shell command until it is restarted.")
    print("  2. Commit the removal.")
    if (manifest.get("options") or {}).get("ci"):
        print("  3. On GitHub: take `all-green` out of the branch ruleset's required checks (the workflow that "
              "reported it is gone), and delete the `allow-test-changes` label if you no longer need it.")
    return 0


# ---------------------------------------------------------------- command line

def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--project", type=Path, help="repository to install into, or to upgrade")
    g.add_argument("--user", action="store_true", help="install personal rules into ~/.claude")
    g.add_argument("--check", type=Path, metavar="PATH", help="verify an installation")
    g.add_argument("--uninstall", type=Path, metavar="PATH", help="remove the kit from a repository")
    ap.add_argument("--profile", choices=["minimal", "standard", "strict"],
                    help="default: what the last install used, else standard")
    ap.add_argument("--tier", choices=["low", "medium", "high"])
    ap.add_argument("--ci", action=argparse.BooleanOptionalAction, default=None,
                    help="add GitHub Actions workflows (--no-ci removes them again)")
    ap.add_argument("--env", action=argparse.BooleanOptionalAction, default=None,
                    help="add the cloud-session SessionStart hook")
    ap.add_argument("--owner", help="GitHub login or team for CODEOWNERS (with --ci)")
    ap.add_argument("--fast", metavar="CMD", help="the fast test command, when it isn't detected or you want another")
    ap.add_argument("--full", metavar="CMD", help="the full test command")
    ap.add_argument("--setup", metavar="CMD", help="the command that installs dependencies")
    ap.add_argument("--run", action="store_true", help="with --check: run the fast tier once and time it")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite kit files you changed (your config is kept)")
    a = ap.parse_args(argv)
    kitlib().tolerant_output()  # a file name or runner output a Windows pipe can't carry is shown escaped

    if a.check:
        return check(a.check.resolve(), a.run)
    if a.uninstall:
        root = a.uninstall.resolve()
        if not root.is_dir():
            print(f"{root} is not a directory")
            return 2
        return uninstall(root, a.dry_run)
    if a.user:
        plan = install_user(Path.home(), a)
        print(f"Testing kit {VERSION}: user install{' (dry run)' if a.dry_run else ''}\n{plan.report()}")
        return 0
    root = a.project.resolve()
    if not root.is_dir():
        print(f"{root} is not a directory")
        return 2
    plan = install_project(root, a)
    det, opts, cmds = plan.detected, plan.options, plan.commands
    det["warnings"] = placement_warnings(root) + det.get("warnings", [])
    before = plan.manifest.get("version")
    moving = f" (upgrading from {before})" if before and before != VERSION else ""
    print(f"Testing kit {VERSION}: {opts['profile']} profile into {root}{moving}{' (dry run)' if a.dry_run else ''}")
    where = {"flag": "from --fast", "config": "from .claude/testing-kit.json", "detected": "detected"}[plan.source["fast"]]
    pm = f" ({det['pm']})" if det["pm"] else ""
    print(f"Detected stack: {det['stack']}{pm}; fast tier: "
          + (f"{cmds['fast']} ({where})" if cmds["fast"] else "none yet"))
    line = tests_line(root)
    print(line[0].upper() + line[1:])
    if plan.manifest.get("options"):
        on = [k for k in ("ci", "env") if opts[k]]
        print("Options kept from the last install unless you passed new ones: " + (", ".join(on) or "no ci, no env")
              + (f", owner {opts['owner']}" if opts["owner"] else ""))
    print(plan.report())
    kinds = {k for k, _, _ in plan.log}
    if plan.legacy:
        print("\nThis repo was set up by a kit version from before 0.4.0, which kept no record of what it wrote "
              "or of the options it was given: pass the ones you used then (--ci, --owner, --profile) once more. "
              "The kit's scripts are brought to this version as a set (`git diff` shows what changed).")
    if "REPLACED" in kinds:
        print("\nThe kit's scripts only work as a set, so the ones you had changed were replaced too. Your "
              "versions are beside them as <name>.yours: re-apply what you still need, then delete those files.")
    if "CONFLICT" in kinds and plan.legacy:
        print("\nThe files marked CONFLICT differ from this version, and without an install record the installer "
              "can't tell an older kit file from one you edited, so they were kept. If you never edited them, "
              "re-run with --force to take the kit's versions (your config stays). Otherwise compare each with "
              "its .kit-new file, merge what you want, then delete the .kit-new file.")
    elif "CONFLICT" in kinds:
        print("\nThe files marked CONFLICT are yours (already in the repo, or changed since the last install), so "
              "they were kept. The kit's version of each is beside it as <name>.kit-new: compare, merge what you "
              "want, then delete the .kit-new file. Or re-run with --force to take the kit's.")
    for w in det.get("warnings", []):
        print(f"\nWARNING: {w}")
    if not cmds["fast"]:
        print('\nNo test command was detected. Re-run with --fast "<your test command>" (for example '
              '--fast "make test"), or set commands.fast in .claude/testing-kit.json. Until then the rules and '
              "edit protections work, but the Stop hook and the CI gates have nothing to run.")
    elif not plan.junit:
        print("\nThis test command writes no JUnit report, so the CI gate compares exit codes (it can't name "
              "the tests that broke) and run reports show the runner's own output. If your runner can write "
              "JUnit XML, add that to commands.fast and set junit_path in .claude/testing-kit.json.")
    if kinds <= {"same", "keep", "SKIP"}:
        print(f"\nUp to date: this repo already has testing kit {VERSION} with these options; nothing was changed.")
        return 0
    me = quote(sys.argv[0] if argv is None and sys.argv[0] else Path(__file__).name)
    print("\nNext steps:")
    print("  1. Check the commands in .claude/testing-kit.json, then run "
          f"`{PY} {me} --check {quote(root)} --run`.")
    print("  2. Restart Claude Code (hooks load at start).")
    print("  3. Commit the files. The CI gates count kit files as test harness, so the pull request that "
          "brings them in needs the `allow-test-changes` label.")
    if getattr(plan, "workflow", False):
        print("  4. On GitHub: create the `allow-test-changes` label; in the branch ruleset make `all-green` a "
              "required check, block force pushes" + (", and require Code Owner review." if opts["owner"] else "."))
        if det["stack"] == "unknown" and not cmds["setup"]:
            print("     The workflow has no toolchain or dependency steps yet: add them to "
                  f"{WORKFLOW} where the comment says so (in both jobs).")
    elif not opts["ci"]:
        print("  4. No CI workflow was installed. The hooks only slow an agent down; the checks that hold are the "
              "CI gates. Add them with --ci (GitHub Actions), or run test_diff_guard.py and base_tests.py from "
              "your own CI.")
    if (root / "docs/testing/KIT-GUIDE.md").exists():
        print("\nThe guide is in the repo now: docs/testing/KIT-GUIDE.md (the live check that the hooks fire, "
              "what the prompts mean, upgrading, uninstalling).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
