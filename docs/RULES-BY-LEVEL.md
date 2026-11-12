# Testing Rules by Level: User, Project, Environment

> **Version** 0.1 (draft for review) · **Date** 2026-11-12
> Companion to `TESTING-GUIDELINES.md` (rule IDs TG-xx). This file says **where** each rule lives so it actually takes effect. Ready-to-copy files are in `kit/templates/`, and `kit/install.py` places them.

## The principle: advise in text, enforce in hooks and CI

Claude Code loads `CLAUDE.md` and `.claude/rules/*.md` as context. The docs say plainly that this is not enforced configuration, and that to block an action regardless of Claude's judgment you use a `PreToolUse` hook [R6 §1.2]. So every important rule appears twice: once as text the agent reads, and once as a deterministic check.

| Rule (from guidelines) | Text (advisory) | Enforced by |
|---|---|---|
| TG-14 don't edit existing tests | `.claude/rules/testing.md` | `protect_tests.py` PreToolUse hook (Edit/Write and Bash redirects into test paths) + CI test-count guard |
| TG-15 don't edit harness files | rule | same hook (harness globs) |
| TG-17 no snapshot regeneration | rule | `guard_bash.py` PreToolUse hook on snapshot-update commands (asks the human) |
| TG-18 / TG-28 no sleeps or retries as a fix | rule | `guard_test_edits.py` PostToolUse check of test diffs (feedback to Claude) |
| TG-04 red before green / TG-13 tests actually run | rule + `/write-tests` skill | Stop hook runs the fast suite; CI fails if new test files collect 0 tests |
| TG-33 / TG-34 coverage and mutation | rule | CI diff-cover gate; `/mutation-check` skill; CI mutation job |
| TG-49 report what was not tested | rule | `test_report.py` (JUnit summariser) used by the Stop hook and `/run-tests` |

---

## 1. User level (`~/.claude/`): your habits, every repo

Purpose: personal defaults that travel with you. **No blocking hooks here.** Enforcement belongs to the project, so collaborators and CI get the same behaviour [R6 §4].

**Files** (installed by `python kit/install.py --user`):

- `~/.claude/rules/testing-habits.md` (always loaded, no `paths:`). Contents:
  - Run the narrowest relevant test first, then the full fast suite before saying you're done (TG-31).
  - Show evidence: the command, the count collected, the summary line. Never write "tests pass" without it (TG-13).
  - Red before green for fixes (TG-04). Expected values from the spec (TG-05).
  - Never weaken a gate, skip, retry or sleep to get green; stop and report after 3 failed attempts (TG-14, TG-18, TG-19).
  - If the repo has no test command in CLAUDE.md, ask for it, or propose one, before writing tests.
  - When a repo has `.claude/rules/testing.md`, it wins over these habits.
- `~/.claude/agents/test-reviewer.md`: a read-only reviewer (`tools: Read, Grep, Glob, Bash`) that applies the checklist in guidelines §10 in a fresh context. Available in every repo as `@agent-test-reviewer`.
- `~/.claude/settings.json` additions (merged, never overwritten): `permissions.allow` for read-only test commands (`Bash(pytest *)`, `Bash(npm test *)`, `Bash(npx vitest *)`, `Bash(go test *)`, `Bash(cargo test *)`).

**Plugins at user scope** (see `CLAUDE-PACKAGES.md`): `superpowers`, `context7`, `pr-review-toolkit`, the `*-lsp` plugin for each language you use. You already run Superpowers, Ralph Loop and Context7.

## 2. Project level (committed in the repo): the main payload

Purpose: rules and checks that apply to everyone and every agent working in this repo, locally and in CI. Installed by `python kit/install.py --project <repo>`.

**Text**
- `CLAUDE.md` gets a `## Testing` block (appended between markers, idempotent), containing the exact commands per tier, the risk-tier rule, and `@docs/testing/GUIDELINES.md`. The installer detects the stack and fills in the commands; check them.
- `.claude/rules/testing.md` with `paths:` globs for test files, so it loads only when Claude touches tests. It holds the short form of TG-04..TG-19 and TG-24.
- `docs/testing/GUIDELINES.md`: a copy of the guidelines.

**Enforcement** (`.claude/settings.json`, merged)
- `PreToolUse` `Edit|Write|NotebookEdit` → `protect_tests.py`. It blocks edits to *existing* test and harness files (new test files are allowed) unless the human has created `.claude/allow-test-edits`. It runs fail-closed where supported (`onFailure: "block"`).
- `PreToolUse` `Bash` → `guard_bash.py`. It asks before snapshot-update commands and blocks shell writes (`sed -i`, `>`, `tee`, `rm`) into test or harness paths. Shell is the documented bypass for edit-only guards [R5 rule 11].
- `PostToolUse` `Edit|Write` → `guard_test_edits.py`. It flags added sleeps, skips, retries, broad `except`, and assertion-free tests in test files and feeds them back to Claude (non-blocking).
- `Stop` → `tests_on_stop.py`. If the working tree changed, it runs the fast tier. If it fails, it blocks stopping with a summary (grouped failures, plus what was not run). It respects `stop_hook_active` so it can't loop forever.
- `permissions`: allow the repo's test commands; `deny` reads of `.env*`; `ask` on editing golden/snapshot fixture directories.

**Agents and skills** (`.claude/agents/`, `.claude/skills/`)
- `spec-test-writer` agent: writes tests from the spec or ticket **without reading the implementation**. Its own frontmatter `PreToolUse` hook blocks Read/Grep/Glob under source directories. Optional `model:` override for cross-model independence at high tier (TG risk tiers) [R6 follow-up 1].
- `test-reviewer` agent: the project copy of the reviewer, which wins over the user one.
- Skills: `/write-tests` (assumptions → spec tests → red evidence → implement → green), `/run-tests` (detects the runner, reports with "not tested"), `/mutation-check` (diff-scoped mutmut/Stryker/cargo-mutants/PIT), `/test-review` (the multi-agent review protocol in `REVIEW-PROTOCOL.md`).

**CI** (`.github/workflows/tests.yml`, from `kit/templates/ci/`)
- Read-only token, SHA-pinned actions, `concurrency` cancel, timeouts, lockfile-enforced install, JUnit upload, diff-cover gate on PRs, a test-count guard against the base branch, one aggregate required check [R4 §3].
- Scheduled jobs: repeat-run flake finder, full mutation run, full evals (for LLM repos).

**Test config** (merged into `pyproject.toml` / `vitest.config.ts` only on request, printed otherwise): random order + seed, sockets off, per-test timeout, strict markers, `xfail_strict`, branch coverage [R4 §3].

## 3. Environment level: cloud sessions, devcontainers, CI runners

Purpose: make sure the tools exist and the project-level checks still apply in places that don't load your local setup. Two facts drive this level [R6 §5]:
- Cloud sessions don't load locally installed plugins.
- Repo hooks in `.claude/settings.json` may not apply in some cloud project threads.

**Cloud environment (claude.ai/code)**
- **Setup script** (environment settings, runs as root, cached if under ~5 min): system tools only, e.g. `apt-get install -y jq` or extra SDKs. Template: `kit/templates/env/setup-script.sh`.
- **SessionStart hook** in the repo (`scripts/session_start.sh`, guarded by `CLAUDE_CODE_REMOTE=true`): installs project deps idempotently (skips when the lockfile hash is unchanged), starts services the tests need, installs the plugins the repo expects (`claude plugin install … --scope project`), and prints the test commands as context [R4 E1–E3].
- Keep the default test command under the 2-minute Bash timeout and size parallelism to ~4 vCPU (`-n 4`) [R4 E5].
- Credentials: use the environment's network secrets, not plain environment variables, which anyone using the environment can read [R4 E7].

**Devcontainer** (optional, `kit/templates/env/devcontainer.json`): one image for humans, CI and agents; pinned runtime; non-root user; no mounted SSH keys or cloud credentials [R4 E6].

**CI agent runs** (`anthropics/claude-code-action@v1` or `claude -p`): `--bare` skips local hooks, plugins and CLAUDE.md, so pass `--settings .claude/settings.json` and the plugin list explicitly. Fail the job if the init event reports `plugin_errors` [R6 §2.8].

**Managed settings (optional, org-wide)**: the `protect_tests` hook with `onFailure: "block"` and a managed CLAUDE.md with the non-negotiable integrity rules. Only server-managed settings reach cloud sessions [R6 §2.2].

---

## Precedence and conflicts

1. CI gates (cannot be bypassed by an agent)
2. Project hooks and permissions
3. Project `.claude/rules/testing.md` and `CLAUDE.md`
4. User `~/.claude/rules/testing-habits.md`
5. Plugin skills (Superpowers TDD etc.): they are advice and work alongside the hooks, not instead of them.

When project text and user text disagree, the project wins. The human's instruction in the session wins over both, **except** that hooks still fire: to change a test legitimately, the human creates `.claude/allow-test-edits` (and deletes it afterwards) or edits the file themselves.
