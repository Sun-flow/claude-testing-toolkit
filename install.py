#!/usr/bin/env python3
"""Testing kit installer. Standard library only; Python 3.9+; Linux, macOS, Windows.

  python install.py --project PATH [--profile minimal|standard|strict] [--tier low|medium|high]
                    [--ci] [--env] [--owner GITHUB_LOGIN] [--dry-run] [--force]
  python install.py --user [--dry-run] [--force]
  python install.py --check PATH

Safe to re-run: identical files are skipped; a file you changed is left alone and the
kit's version is written beside it as <name>.kit-new (unless --force); settings.json
is merged (only the kit's own hook entries are added or refreshed); CLAUDE.md gets a
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
        dest.write_text(text, encoding="utf-8", newline="\n")
        if executable and os.name != "nt":
            dest.chmod(0o755)

    def report(self) -> str:
        width = max((len(k) for k, _, _ in self.log), default=6)
        lines = [f"  {k:<{width}}  {p}" + (f"  ({e})" if e else "") for k, p, e in self.log]
        return "\n".join(lines)


# ---------------------------------------------------------------- detection

def detect(root: Path) -> dict:
    d = {"stack": "unknown", "setup": "", "fast": "", "full": "", "one": "(see your runner's docs)",
         "src_dirs": [], "ci": None}
    pkg = root / "package.json"
    if (root / "pyproject.toml").exists() or (root / "requirements.txt").exists() or (root / "setup.py").exists():
        d["stack"], d["ci"] = "python", "tests-python.yml"
        uv = (root / "uv.lock").exists()
        run = "uv run " if uv else "python -m "
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
        d["setup"] = "npm ci" if (root / "package-lock.json").exists() else "npm install"
        if "vitest" in deps:
            d["fast"] = "npx vitest run --reporter=default --reporter=junit --outputFile.junit=.reports/junit.xml"
            d["one"] = "`npx vitest run path/to/file.test.ts -t \"name\"`"
        elif "jest" in deps:
            d["fast"] = ("JEST_JUNIT_OUTPUT_FILE=.reports/junit.xml npx jest --ci "
                         "--reporters=default --reporters=jest-junit")
            d["one"] = "`npx jest path/to/file.test.js -t \"name\"`"
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
              "SRC_DIRS": json.dumps(det["src_dirs"] or ["src"]), "OWNER": a.owner or "OWNER"}

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
    cfg_path = root / ".claude" / "testing-kit.json"
    if cfg_path.exists() and not a.force:
        plan.note("keep", cfg_path, "existing config kept")
    else:
        plan.write(cfg_path, json.dumps(cfg, indent=2) + "\n", root)

    settings_path = root / ".claude" / "settings.json"
    existing = json.loads(settings_path.read_text(encoding="utf-8")) if settings_path.exists() else {}
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
    if merged != existing:
        plan.note("merge" if existing else "create", settings_path, "kit hooks and permissions")
        if not a.dry_run:
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8", newline="\n")
    else:
        plan.note("same", settings_path)

    block = fill((T / "project" / "CLAUDE-block.md").read_text(encoding="utf-8"), values)
    claude_md = root / "CLAUDE.md"
    plan.note("update" if claude_md.exists() else "create", claude_md, "## Testing block")
    if not a.dry_run:
        claude_md.write_text(update_claude_md(claude_md, block), encoding="utf-8", newline="\n")

    docs = docs_dir()
    if docs:
        plan.write(root / "docs/testing/GUIDELINES.md", (docs / "TESTING-GUIDELINES.md").read_text(encoding="utf-8"), root)
        plan.write(root / "docs/testing/REVIEW-PROTOCOL.md", (docs / "REVIEW-PROTOCOL.md").read_text(encoding="utf-8"), root)
    else:
        plan.note("MISSING", "docs/testing/GUIDELINES.md", "kit docs not found next to the installer")

    gi = root / ".gitignore"
    new_gi = ensure_lines(gi, [".claude/testing-kit/.state/", ".claude/allow-test-edits", ".reports/",
                               ".claude/settings.local.json"])
    if (gi.read_text(encoding="utf-8") if gi.exists() else "") != new_gi:
        plan.note("update" if gi.exists() else "create", gi, "kit ignores")
        if not a.dry_run:
            gi.write_text(new_gi, encoding="utf-8", newline="\n")

    if a.ci:
        if det["ci"]:
            text = fill((T / "ci" / det["ci"]).read_text(encoding="utf-8"), values)
            plan.write(root / ".github/workflows/tests.yml", text, root)
            plan.write(root / ".github/workflows/flake-finder.yml",
                       (T / "ci" / "flake-finder.yml").read_text(encoding="utf-8"), root)
        else:
            plan.note("SKIP", ".github/workflows/tests.yml", f"no CI template for stack '{det['stack']}'")
        if a.profile == "strict":
            plan.write(root / ".github/CODEOWNERS", fill((T / "ci" / "CODEOWNERS").read_text(encoding="utf-8"), values), root)

    plan.detected = det
    return plan


def install_user(home: Path, a: argparse.Namespace) -> Plan:
    plan = Plan(a.dry_run, a.force)
    base = home / ".claude"
    plan.write(base / "rules/testing-habits.md", (T / "user/rules/testing-habits.md").read_text(encoding="utf-8"), home)
    plan.write(base / "agents/test-reviewer.md", (T / "user/agents/test-reviewer.md").read_text(encoding="utf-8"), home)
    sp = base / "settings.json"
    existing = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    allow = ["Bash(pytest *)", "Bash(python -m pytest *)", "Bash(uv run pytest *)", "Bash(npm test *)",
             "Bash(npx vitest run *)", "Bash(npx jest *)", "Bash(go test *)", "Bash(cargo test *)"]
    merged = merge_settings(existing, {"permissions": {"allow": allow}}, None)
    if not merged.get("hooks"):
        merged.pop("hooks", None)
    if merged != existing:
        plan.note("merge" if existing else "create", sp, "test commands allowed")
        if not a.dry_run:
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    else:
        plan.note("same", sp)
    return plan


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
        if not cfg.get("commands", {}).get("fast"):
            problems.append("commands.fast is empty in .claude/testing-kit.json (Stop hook and CI gates need it)")
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
    print("\nNext: check the commands in .claude/testing-kit.json, run "
          f"`{PY} {Path(__file__).name} --check {root}`, restart Claude Code (hooks load at start), "
          "and commit the files.")
    if a.ci:
        print("For CI to bind: make the `all-green` job a required check in the branch ruleset"
              + (" and require Code Owner review." if a.profile == "strict" else "."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
