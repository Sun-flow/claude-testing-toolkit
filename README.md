# Testing kit for agent-written code

A drop-in set of rules, hooks, agents, skills and CI checks that help Claude Code (and people) build
honest, effective test suites, and that make it hard to "pass" by weakening the tests.

Standard library Python only. Hooks need **Python ≥ 3.9** on PATH and a git repository. Built against
Claude Code 2.1.x hooks (PreToolUse, PostToolUse, Stop, SessionStart, ConfigChange).

**New here? Read [`docs/GUIDE.md`](docs/GUIDE.md)**: set up, the two-minute check that the hooks fire, daily
use, configuration, upkeep and troubleshooting. The installer copies it into each repo as
`docs/testing/KIT-GUIDE.md`.

## Quick start

```bash
git clone https://github.com/Sun-flow/claude-testing-toolkit && cd claude-testing-toolkit

python3 install.py --project /path/to/repo --ci --dry-run   # show the plan, write nothing
python3 install.py --project /path/to/repo --ci             # install (standard profile, with CI gates)
python3 install.py --check /path/to/repo --run              # are the hooks wired up? is the fast tier green and quick?
```

Then restart Claude Code in the repo, commit, and switch on branch protection (the guide has the steps).
On Windows, type `py` or `python` where the examples say `python3`.

The installer detects Python (pip or uv, with or without packaging files), Node (Vitest, Jest or an npm
test script), Go and Rust, and fills in the test commands. For anything else, give the command:
`--fast "make test"`. It prints the command it chose and the test files it recognises; check both.

```bash
python3 install.py --project /path/to/repo                  # again, later: upgrade to this version of the kit
python3 install.py --project /path/to/repo --profile strict --ci --owner your-team --env
python3 install.py --uninstall /path/to/repo                # take it out again
python3 install.py --user                                   # your own habits, for every repo (~/.claude)
```

Re-running is safe, and it is how you upgrade. The installer records what it wrote in
`.claude/testing-kit/manifest.json`, so the next run updates the files you haven't touched, keeps a rule,
skill or workflow you changed (the kit's version goes beside it as `name.kit-new`), keeps your
`.claude/testing-kit.json`, and remembers the profile and options you chose. It never writes through a
symlink, merges into an existing `.claude/settings.json` rather than replacing it, and keeps one marked
block in `CLAUDE.md`.

## Profiles

| Profile | What you get |
|---|---|
| minimal | Guard hooks only: protect tests and test config, guard Bash writes, audit Bash, guard settings changes |
| standard | Minimal + test-quality feedback after edits, run fast tests when Claude finishes a turn with changes, the spec-only test writer and test reviewer agents, skills `/write-tests`, `/run-tests`, `/mutation-check`, `/test-review` |
| strict | Standard + `enforcement: deny` (no "ask" prompts, blocked outright) and default risk tier medium |

`--ci` adds one GitHub workflow, `.github/workflows/testing-kit.yml`, with the setup steps for the detected
stack and package manager: the fast tier, the test-diff guard, the base-branch tests, and `all-green`. Its
name can't collide with a `tests.yml` or `ci.yml` you already have. Python repos also get a weekly flake
finder. With `--owner`, it writes CODEOWNERS for the test harness. `--env` adds a SessionStart script for
cloud sessions.

## What loads where

| Where Claude runs | Rules | Skills | Hooks and agents |
|---|---|---|---|
| Claude Code CLI / desktop / IDE in the repo | yes | yes | yes |
| Claude Code on the web with the repo checked out | yes | yes | yes |
| `claude -p` in CI | yes | yes, unless `--bare` | project hooks yes, unless `--bare`; subagent frontmatter hooks no (so the spec-test-writer's allowlist doesn't apply) |
| A claude.ai project thread with the repo attached | yes | yes | not confirmed: assume no |
| A chat that only reads files | no | no | no |

The project-thread row is what one such thread loaded on 2026-11-13 (rules and skills, including ones in
nested `.claude` folders); the rest is from the Claude Code documentation. When the hooks don't run, the CI
checks are what holds. See `docs/RULES-BY-LEVEL.md`.

## Layers

1. **Rules** (`.claude/rules/testing.md`, always loaded): how to write tests, and never to game them.
2. **Hooks** (`.claude/testing-kit/*.py`): speed bumps. Editing an existing test, test config or a
   snapshot asks you first (or is denied in strict); pure additions to test files pass. Bash writes to
   protected files are caught before and after.
3. **CI** (binding): `test_diff_guard.py` flags deleted/skipped tests and harness changes;
   `base_tests.py` runs the base branch's tests against the PR's code, so a bug hidden by editing its
   test still fails. It compares test by test when the runner writes JUnit XML, and exit codes when it
   doesn't (`go test`, `cargo test`, a Makefile target). Both gates read `.claude/testing-kit.json` from
   the base branch, and the workflow runs the gate scripts from the base branch's copy, so a PR can't
   redefine or edit its own gate. Files the test command goes through (a Makefile, a script, an npm
   script) are taken from the base too.
   (The workflow file itself still comes from the PR. That is what branch protection is for.)
4. **Branch protection** (you set this up once): require the `all-green` check, require CODEOWNERS
   review for `.claude/`, `.github/` and test config, and block force pushes. Steps are in
   `docs/RULES-BY-LEVEL.md`. Without this, a PR can edit the workflow that checks it.

Overrides, all made by a person:
- Locally, approve the "ask" prompt. In the strict profile there is no prompt; run
  `touch .claude/allow-test-edits` to allow test edits for 2 hours (Claude is blocked from creating it).
- In CI, add the `allow-test-changes` label to the PR. The gates re-run, still list what changed, and pass.

What the checks can't do: the check for production code that detects tests (TG-16) is a pattern match that
string tricks beat, so the `test-reviewer` agent and human review are the real gate there. Hooks are speed
bumps; base-branch tests in CI plus branch protection are what bind.

## How the repo is organised

| Path | What it is |
|---|---|
| `install.py` | Detects the stack, copies the templates for the chosen profile, merges hooks into `.claude/settings.json`, adds the `CLAUDE.md` block, and records it all in a manifest. Re-running upgrades; `--check` verifies an install; `--uninstall` removes it. |
| `templates/project/.claude/testing-kit/` | The hook scripts and CI gate scripts, all built on `kitlib.py` (config, path matching, patterns). |
| `templates/project/.claude/{rules,agents,skills}/` | The always-loaded rules, the two agents and the four skills. |
| `templates/ci/`, `templates/env/`, `templates/user/` | The workflow template (one for every stack), cloud-session scripts, and the personal (`--user`) rules. |
| `docs/`, `research/` | The guidelines and the reports they cite. |
| `tests/` | The kit's own suite: it installs the kit into throwaway repos and feeds the hooks real input. |

Hooks, by when they run: `tests_on_stop.py baseline` (when a session starts: it notes what the working
tree looks like), `protect_tests.py` (before an edit), `guard_bash.py` and `bash_audit.py pre` (before a
shell command), `guard_test_edits.py` and `bash_audit.py post` (after), `tests_on_stop.py` (when Claude
tries to finish: it runs the fast tier if the session changed something), `config_guard.py` (on a settings
change), `no_src_access.py` (inside the spec-test-writer agent only).

## Docs

- `docs/GUIDE.md`: set up, use and upkeep of the kit (installed as `docs/testing/KIT-GUIDE.md`).
- `docs/TESTING-GUIDELINES.md`: rules TG-01..TG-50 with reasons and sources (installed as
  `docs/testing/GUIDELINES.md`).
- `docs/RULES-BY-LEVEL.md`: user, project and environment rules, profiles, CI, branch protection.
- `docs/CLAUDE-PACKAGES.md`: plugins, MCP servers and tools worth adding, by repo type.
- `docs/REVIEW-PROTOCOL.md`: how to run a multi-agent review of tests or of this kit.

## Developing the kit

```bash
python -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest -q tests
```

The kit's own tests run in CI on Linux, macOS and Windows (Python 3.9 to 3.13). They install the kit into
throwaway repos and feed the hooks the input Claude Code sends. Not yet verified: the hooks firing inside a
live Claude Code session (the guide has a two-minute check for that), and the generated workflow running in
GitHub Actions (it passes `actionlint` for pip, uv, npm, pnpm, yarn, Go, Rust and hand-given commands).

## Research

`research/` holds the reports the guidelines cite as [R1]–[R6] and [R1b].
