# Testing kit for agent-written code

A drop-in set of rules, hooks, agents, skills and CI checks that help Claude Code (and people) build
honest, effective test suites, and that make it hard to "pass" by weakening the tests.

Standard library Python only. Hooks need **Python ≥ 3.9** on PATH. Built against Claude Code 2.1.x
hooks (PreToolUse, PostToolUse, Stop, ConfigChange).

## Install

```bash
# into an existing or fresh repo
python install.py --project /path/to/repo                 # standard profile
python install.py --project /path/to/repo --profile minimal
python install.py --project /path/to/repo --profile strict --ci --env --owner @your-team
python install.py --project /path/to/repo --dry-run       # show the plan, write nothing

# your own habits, for every repo (~/.claude)
python install.py --user

# is everything wired up?
python install.py --check /path/to/repo
```

The installer detects the stack (Python with uv or pip, Node with vitest or jest, Go, Rust) and fills in
the test commands in `.claude/testing-kit.json`. Check them after installing.

It is safe to re-run. It never overwrites a file you changed (it writes `name.kit-new` next to it),
never writes through a symlink, merges into an existing `.claude/settings.json` rather than replacing it,
and keeps one marked block in `CLAUDE.md`.

## Profiles

| Profile | What you get |
|---|---|
| minimal | Guard hooks only: protect tests and test config, guard Bash writes, audit Bash, guard settings changes |
| standard | Minimal + test-quality feedback after edits, run fast tests on Stop, the spec-only test writer and test reviewer agents, skills `/write-tests`, `/run-tests`, `/mutation-check`, `/test-review` |
| strict | Standard + `enforcement: deny` (no "ask" prompts, blocked outright) and default risk tier medium |

`--ci` adds GitHub workflows (tests, test-diff guard, base-branch tests, flake finder) and CODEOWNERS.
`--env` adds a cloud setup script, a SessionStart script and a devcontainer.

## What loads where

| Where Claude runs | Rules | Hooks, agents, skills |
|---|---|---|
| Claude Code CLI / desktop / IDE in the repo | yes | yes |
| Claude Code on the web with the repo checked out | yes | yes |
| `claude -p` in CI | yes | yes, unless `--bare` (which skips hooks) |
| A claude.ai chat or project thread that only reads files | no | no |

When the hooks don't run, the CI checks are what holds. See `docs/RULES-BY-LEVEL.md`.

## Layers

1. **Rules** (`.claude/rules/testing.md`, always loaded): how to write tests, and never to game them.
2. **Hooks** (`.claude/testing-kit/*.py`): speed bumps. Editing an existing test, test config or a
   snapshot asks you first (or is denied in strict); pure additions to test files pass. Bash writes to
   protected files are caught before and after.
3. **CI** (binding): `test_diff_guard.py` flags deleted/skipped tests and harness changes;
   `base_tests.py` runs the base branch's tests against the PR's code, so a bug hidden by editing its
   test still fails.
4. **Branch protection** (you set this up once): require the `all-green` check, require CODEOWNERS
   review for `.claude/`, `.github/` and test config, and block force pushes. Steps are in
   `docs/RULES-BY-LEVEL.md`. Without this, a PR can edit the workflow that checks it.

A human overrides a block with `ALLOW_TEST_CHANGES=1` in CI (e.g. from a PR label), or by approving the
"ask" prompt locally.

## Docs

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

Not yet tested on Windows or macOS.
