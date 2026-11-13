#!/usr/bin/env python3
"""Testing kit installer. Standard library only; Python 3.9+; Linux, macOS, Windows.

  python install.py --project PATH [--profile minimal|standard|strict] [--tier low|medium|high]
                    [--ci] [--env] [--owner GITHUB_LOGIN] [--dry-run] [--force]
  python install.py --user [--dry-run] [--force]
  python install.py --check PATH

Safe to re-run: identical files are skipped; a file you changed is left alone and the
kit's version is written beside it as <name>.kit-new (unless --force); settings.json
is merged (only the kit's own hook entries are added, refreshed or removed); CLAUDE.md gets a
block between `testing-kit` markers. It never writes through a symlink, so a skill
linked in from claude-toolkit is never overwritten.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

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


def _write(path: Path, text: str) -> None:
    """Write with LF line endings on every platform (Path.write_text(newline=) needs Python 3.10)."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


class Plan:
    def __init__(self, dry: bool, force: bool):
        self.dry, self.force, self.log = dry, force, []

    def note(self, kind: str, path: Path | str, extra: str = "") -> None:
        self.log.append((kind, str(path), extra))

    def _symlinked(self, dest: Path, root: Path) -> bool:
        p = dest
        while True:
            if p.is_symlink():
                return True
            if p == root or p.parent == p:
                return False
            p = p.parent

    def write(self, dest: Path, text: str, root: Path, executable: bool = False) -> None:
        if self._symlinked(dest, root):
            self.note("SKIP (symlink)", dest, "linked from elsewhere; not overwritten")
            return
        if dest.exists():
            old = dest.read_text(encoding="utf-8", errors="replace")
            if old == text:
                self.note("same", dest)
                return
            if not self.force:
                alt = dest.with_name(dest.name + ".kit-new")
                self.note("CONFLICT", dest, f"yours kept; kit version written to {alt.name}")
                dest = alt
            else:
                self.note("overwrite", dest)
        else:
            self.note("create", dest)
        if self.dry:
            return
        dest.parent.mkdir(parents=True, exist_ok=True)
        _write(dest, text)
        if executable and os.name != "nt":
            dest.chmod(0o755)

    def update(self, dest: Path, old: str | None, new: str, root: Path, extra: str) -> None:
        """Write a file the installer merges into (settings.json, CLAUDE.md, .gitignore). `old` is its
        current text, or None if it doesn't exist. Like write(), never goes through a symlink."""
        if old == new:
            self.note("same", dest)
            return
        if self._symlinked(dest, root):
            self.note("SKIP (symlink)", dest, f"linked from elsewhere; add by hand: {extra}")
            return
        self.note("create" if old is None else "update", dest, extra)
        if not self.dry:
            dest.parent.mkdir(parents=True, exist_ok=True)
            _write(dest, new)

    def report(self) -> str:
        width = max((len(k) for k, _, _ in self.log), default=6)
        lines = [f"  {k:<{width}}  {p}" + (f"  ({e})" if e else "") for k, p, e in self.log]
        return "\n".join(lines)


# ---------------------------------------------------------------- detection

def detect(root: Path) -> dict:
    d = {"stack": "unknown", "setup": "", "fast": "", "full": "", "one": "(see your runner's docs)",
         "src_dirs": [], "ci": None, "pm": "", "warnings": []}
    pkg = root / "package.json"
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists() or (root / "setup.py").exists():
        d["stack"], d["ci"] = "python", "tests-python.yml"
        uv = (root / "uv.lock").exists()
        d["pm"] = "uv" if uv else "pip"
        run = "uv run " if uv else f"{PY} -m "  # the interpreter name that exists on this machine
        d["setup"] = "uv sync --locked" if uv else ("pip install -r requirements.txt"
                                                    if (root / "requirements.txt").exists() else "pip install -e .")
        d["fast"] = f"{run}pytest -q --junitxml=.reports/junit.xml"
        d["full"] = d["fast"]
        d["one"] = f"`{run}pytest path/to/test_file.py::test_name -q`"
        pkgs = [p.name for p in root.iterdir() if p.is_dir() and (p / "__init__.py").exists()
                and not p.name.startswith(("test", ".")) and p.name not in {"docs", "scripts"}]
        d["src_dirs"] = ["src"] if (root / "src").is_dir() else sorted(pkgs)
    elif pkg.exists():
        d["stack"], d["ci"] = "node", "tests-node.yml"
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
        except ValueError:
            data = {}
        deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
        if (root / "pnpm-lock.yaml").exists():
            d["pm"], d["setup"], x = "pnpm", "pnpm install --frozen-lockfile", "pnpm exec "
        elif (root / "yarn.lock").exists():
            d["pm"], d["setup"], x = "yarn", "yarn install --frozen-lockfile", "yarn "
        else:
            d["pm"], x = "npm", "npx "
            d["setup"] = "npm ci" if (root / "package-lock.json").exists() else "npm install"
        if "vitest" in deps:
            d["fast"] = f"{x}vitest run --reporter=default --reporter=junit --outputFile.junit=.reports/junit.xml"
            d["one"] = f"`{x}vitest run path/to/file.test.ts -t \"name\"`"
        elif "jest" in deps:
            d["fast"] = (f"JEST_JUNIT_OUTPUT_FILE=.reports/junit.xml {x}jest --ci "
                         "--reporters=default --reporters=jest-junit")
            d["one"] = f"`{x}jest path/to/file.test.js -t \"name\"`"
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
    return d


# ---------------------------------------------------------------- helpers

def fill(text: str, values: dict) -> str:
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def merge_settings(existing: dict, fragment: dict, keep_scripts: set[str] | None) -> dict:
    out = json.loads(json.dumps(existing))
    hooks = out.setdefault("hooks", {})
    for event, groups in fragment.get("hooks", {}).items():
        current = [g for g in hooks.get(event, [])
                   if not any(KIT_HOOK_TAG in h.get("command", "") for h in g.get("hooks", []))]
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


def update_claude_md(path: Path, block: str) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if MARK_START in text and MARK_END in text:
        start = text.index(MARK_START)
        end = text.index(MARK_END) + len(MARK_END)
        return text[:start] + block.strip() + text[end:]
    sep = "" if not text or text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + sep + block.strip() + "\n"


def ensure_lines(path: Path, lines: list[str]) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    missing = [l for l in lines if l not in text.splitlines()]
    if not missing:
        return text
    if text and not text.endswith("\n"):
        text += "\n"
    return text + "# testing kit\n" + "\n".join(missing) + "\n"


def ci_values(det: dict) -> dict:
    """YAML steps for installing dependencies, matched to the detected package manager."""
    pad = "      "
    if det["stack"] == "python":
        if det["pm"] == "uv":
            steps = ["- uses: astral-sh/setup-uv@v7", "  with: {enable-cache: true}", "- run: uv sync --locked"]
            flake = "uv run --with pytest-repeat --with pytest-randomly pytest"
        else:
            steps = ["- uses: actions/setup-python@v6", "  with: {python-version: '3.12', cache: pip}",
                     f"- run: python -m pip install pytest && {det['setup']}"]
            flake = "python -m pip install pytest-repeat pytest-randomly && python -m pytest"
        return {"CI_SETUP": ("\n" + pad).join(steps), "FLAKE_RUN": flake}
    if det["stack"] == "node":
        cache = det["pm"] if det["pm"] in ("npm", "pnpm", "yarn") else "npm"
        steps = ["- run: corepack enable"] if cache in ("pnpm", "yarn") else []
        steps += ["- uses: actions/setup-node@v5",
                  "  with: {node-version: lts/*, cache: " + cache + "}", f"- run: {det['setup']}"]
        return {"CI_SETUP": ("\n" + pad).join(steps), "FLAKE_RUN": ""}
    return {"CI_SETUP": "", "FLAKE_RUN": ""}


REVIEW_ORIGIN = re.compile(r"## Where this comes from\n.*?(?=\n## )", re.S)


def neutral(text: str) -> str:
    """Docs copied into other repos: drop the kit author's own sources and names."""
    text = REVIEW_ORIGIN.sub("## Where this comes from\n\nAdapted from earlier review practice: expected results "
                             "come from the brief, not the code; findings go in a table; fixes are numbered "
                             "proposals that the maintainer approves; reviewers never auto-apply them.\n", text)
    return re.sub(r"\bmae\b", "the maintainer", text)


def docs_dir() -> Path | None:
    for cand in (KIT / "docs", KIT.parent / "docs"):
        if (cand / "TESTING-GUIDELINES.md").exists():
            return cand
    return None


# ---------------------------------------------------------------- installs

def install_project(root: Path, a: argparse.Namespace) -> Plan:
    plan = Plan(a.dry_run, a.force)
    det = detect(root)
    tier = a.tier or ("medium" if a.profile == "strict" else "low")
    values = {"PY": PY, "FAST": det["fast"] or "(set commands.fast in .claude/testing-kit.json)",
              "FULL": det["full"] or "(not set)", "SETUP": det["setup"], "ONE": det["one"], "TIER": tier,
              "SRC_DIRS": json.dumps(det["src_dirs"] or ["src"]), "OWNER": a.owner or "OWNER",
              **ci_values(det)}
    cfg_path = root / ".claude" / "testing-kit.json"
    try:  # the CLAUDE.md block follows the user's edited config, not fresh detection
        existing_cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    except ValueError:
        existing_cfg = {}
    cmds = existing_cfg.get("commands") or {}
    block_values = {**values, "FAST": cmds.get("fast") or values["FAST"], "FULL": cmds.get("full") or values["FULL"],
                    "TIER": existing_cfg.get("default_tier") or tier}

    for rel in PROFILE_FILES[a.profile]:
        src = T / "project" / rel
        plan.write(root / rel, fill(src.read_text(encoding="utf-8"), values), root, executable=rel.endswith(".py"))

    cfg_text = fill((T / "project" / "testing-kit.json").read_text(encoding="utf-8"),
                    {**values, "FAST": det["fast"], "FULL": det["full"]})
    cfg = json.loads(cfg_text)
    if a.profile == "strict":
        cfg["enforcement"] = "deny"
    if a.profile == "minimal":
        cfg["stop_hook"]["enabled"] = False
    if cfg_path.exists() and not a.force:
        plan.note("keep", cfg_path, "existing config kept")
    else:
        plan.write(cfg_path, json.dumps(cfg, indent=2) + "\n", root)

    settings_path = root / ".claude" / "settings.json"
    settings_text = settings_path.read_text(encoding="utf-8") if settings_path.exists() else None
    try:
        existing = json.loads(settings_text) if settings_text and settings_text.strip() else {}
        if not isinstance(existing, dict):
            raise ValueError("not a JSON object")
    except ValueError as exc:
        raise SystemExit(f"{settings_path} is not valid JSON ({exc}). Fix it and re-run; nothing was merged into it.")
    fragment = json.loads(fill((T / "project" / "settings.fragment.json").read_text(encoding="utf-8"), values))
    keep = MINIMAL_HOOK_SCRIPTS if a.profile == "minimal" else None
    merged = merge_settings(existing, fragment, keep)
    if a.env:
        merged.setdefault("hooks", {})
        merged["hooks"]["SessionStart"] = [g for g in merged["hooks"].get("SessionStart", [])
                                           if not any(KIT_HOOK_TAG in h.get("command", "") for h in g["hooks"])]
        merged["hooks"]["SessionStart"].append({"matcher": "startup|resume", "hooks": [
            {"type": "command", "command": 'bash "${CLAUDE_PROJECT_DIR}/.claude/testing-kit/session_start.sh"',
             "timeout": 600}]})
        plan.write(root / ".claude/testing-kit/session_start.sh",
                   (T / "env" / "session_start.sh").read_text(encoding="utf-8"), root, executable=True)
    unchanged = merged == existing and settings_text is not None
    plan.update(settings_path, settings_text, settings_text if unchanged else json.dumps(merged, indent=2) + "\n",
                root, "kit hooks and permissions")

    block = fill((T / "project" / "CLAUDE-block.md").read_text(encoding="utf-8"), block_values)
    claude_md = root / "CLAUDE.md"
    old_md = claude_md.read_text(encoding="utf-8") if claude_md.exists() else None
    plan.update(claude_md, old_md, update_claude_md(claude_md, block), root, "## Testing block")

    docs = docs_dir()
    if docs:
        plan.write(root / "docs/testing/GUIDELINES.md", neutral((docs / "TESTING-GUIDELINES.md").read_text(encoding="utf-8")), root)
        plan.write(root / "docs/testing/REVIEW-PROTOCOL.md", neutral((docs / "REVIEW-PROTOCOL.md").read_text(encoding="utf-8")), root)
    else:
        plan.note("MISSING", "docs/testing/GUIDELINES.md", "kit docs not found next to the installer")

    gi = root / ".gitignore"
    new_gi = ensure_lines(gi, [".claude/testing-kit/.state/", ".claude/testing-kit/__pycache__/",
                               ".claude/allow-test-edits", ".reports/",
                               ".claude/settings.local.json"])
    plan.update(gi, gi.read_text(encoding="utf-8") if gi.exists() else None, new_gi, root, "kit ignores")

    plan.workflow = False
    if a.ci:
        if det["ci"] and det["fast"]:
            text = fill((T / "ci" / det["ci"]).read_text(encoding="utf-8"), values)
            plan.write(root / ".github/workflows/tests.yml", text, root)
            plan.workflow = True
            if det["stack"] == "python":
                plan.write(root / ".github/workflows/flake-finder.yml",
                           fill((T / "ci" / "flake-finder.yml").read_text(encoding="utf-8"), values), root)
        else:
            why = f"no CI template for stack '{det['stack']}'" if not det["ci"] else "no test command detected"
            plan.note("SKIP", ".github/workflows/tests.yml", why)
        if a.owner:
            plan.write(root / ".github/CODEOWNERS", fill((T / "ci" / "CODEOWNERS").read_text(encoding="utf-8"), values), root)
        else:
            plan.note("SKIP", ".github/CODEOWNERS", "pass --owner @you-or-team to protect the test harness")
    elif a.owner:
        plan.note("SKIP", ".github/CODEOWNERS", "--owner is used with --ci")

    plan.detected = det
    return plan


def install_user(home: Path, a: argparse.Namespace) -> Plan:
    plan = Plan(a.dry_run, a.force)
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
    plan.update(sp, sp_text, sp_text if unchanged else json.dumps(merged, indent=2) + "\n", home,
                "test commands allowed")
    return plan


def fast_command_problems(fast: str, root: Path) -> list[str]:
    """Can the fast command start? (Checks the program and, for `python -m X`, the module; doesn't run tests.)"""
    import shlex
    try:
        words = [w for w in shlex.split(fast) if "=" not in w]
    except ValueError:
        return []
    if not words:
        return []
    if not shutil.which(words[0]):
        return [f"`{words[0]}` (from commands.fast) is not on PATH"]
    if Path(words[0]).name.lower().startswith(("python", "py")) and len(words) > 2 and words[1] == "-m":
        r = subprocess.run([words[0], "-c", f"import {words[2]}"], cwd=root, capture_output=True, text=True)
        if r.returncode != 0:
            return [f"`{words[0]} -m {words[2]}` can't run here: {words[2]} is not installed"]
    return []


def check(root: Path) -> int:
    problems = []
    for rel in PROFILE_FILES["minimal"]:
        if not (root / rel).exists():
            problems.append(f"missing {rel}")
    sp = root / ".claude/settings.json"
    try:
        settings = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        settings = {}
        problems.append(f"cannot read {sp}: {exc}")
    commands = [h["command"] for groups in settings.get("hooks", {}).values() for g in groups for h in g.get("hooks", [])]
    if not any("protect_tests.py" in c for c in commands):
        problems.append("protect_tests.py hook not registered in .claude/settings.json")
    if not shutil.which(PY):
        problems.append(f"`{PY}` is not on PATH, so the hooks can't run")
    else:
        probe = json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(root / "README.md"),
                                                               "old_string": "x", "new_string": "y"}, "cwd": str(root)})
        env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root)}
        r = subprocess.run([PY, str(root / ".claude/testing-kit/protect_tests.py")], input=probe, text=True,
                           capture_output=True, env=env)
        if r.returncode != 0:
            problems.append(f"protect_tests.py failed on a probe: {r.stderr.strip()[:200]}")
    try:
        cfg = json.loads((root / ".claude/testing-kit.json").read_text(encoding="utf-8"))
        fast = cfg.get("commands", {}).get("fast", "")
        if not fast:
            problems.append("commands.fast is empty in .claude/testing-kit.json (Stop hook and CI gates need it)")
        else:
            problems += fast_command_problems(fast, root)
    except (OSError, ValueError):
        problems.append("missing or invalid .claude/testing-kit.json")
    if problems:
        print("Testing kit check found problems:\n" + "\n".join(f"  - {p}" for p in problems))
        return 1
    print("Testing kit check: OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--project", type=Path, help="repository to install into")
    g.add_argument("--user", action="store_true", help="install personal rules into ~/.claude")
    g.add_argument("--check", type=Path, metavar="PATH", help="verify an installation")
    ap.add_argument("--profile", choices=["minimal", "standard", "strict"], default="standard")
    ap.add_argument("--tier", choices=["low", "medium", "high"])
    ap.add_argument("--ci", action="store_true", help="add GitHub Actions workflows")
    ap.add_argument("--env", action="store_true", help="add the cloud-session SessionStart hook")
    ap.add_argument("--owner", help="GitHub login for CODEOWNERS (strict profile)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite files you changed")
    a = ap.parse_args(argv)

    if a.check:
        return check(a.check.resolve())
    if a.user:
        plan = install_user(Path.home(), a)
        print(f"Testing kit {VERSION}: user install{' (dry run)' if a.dry_run else ''}\n{plan.report()}")
        return 0
    root = a.project.resolve()
    if not root.is_dir():
        print(f"{root} is not a directory")
        return 2
    plan = install_project(root, a)
    det = plan.detected
    print(f"Testing kit {VERSION}: {a.profile} profile into {root}{' (dry run)' if a.dry_run else ''}")
    print(f"Detected stack: {det['stack']}; fast tier: {det['fast'] or '(none: set commands.fast)'}")
    print(plan.report())
    conflicts = [p for k, p, _ in plan.log if k == "CONFLICT"]
    if conflicts:
        print("\nReview each .kit-new file and merge it by hand, or re-run with --force.")
    for w in det.get("warnings", []):
        print(f"\nWARNING: {w}")
    me = f'"{Path(__file__).resolve()}"' if " " in str(Path(__file__).resolve()) else Path(__file__).name
    target = f'"{root}"' if " " in str(root) else str(root)
    print("\nNext steps:")
    print("  1. Check the commands in .claude/testing-kit.json, then run "
          f"`{PY} {me} --check {target}`.")
    print("  2. Restart Claude Code (hooks load at start).")
    print("  3. Commit the files. CI flags this first commit as a harness change: add the "
          "`allow-test-changes` label to that PR.")
    if getattr(plan, "workflow", False):
        print("  4. On GitHub: create the `allow-test-changes` label; in the branch ruleset make `all-green` a "
              "required check, block force pushes" + (", and require Code Owner review." if a.owner else "."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
