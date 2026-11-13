# Testing Rules by Level: User, Project, Environment

> **Version** 0.4 (kit 0.4.0) · **Date** 2026-11-13
> Companion to `TESTING-GUIDELINES.md` (rule IDs TG-xx). This file says **where** each rule lives so it actually takes effect. Every file named here exists in `templates/` and is placed by `install.py`. For setting the kit up and living with it, read `GUIDE.md`.

## The principle: text advises, hooks slow down, CI decides

1. **Text** (`CLAUDE.md`, `.claude/rules/*.md`) tells the agent what to do. Claude Code treats it as context, not enforced configuration [R6 §1.2].
2. **Hooks** catch most mistakes and most gaming at the moment they happen. But they are speed bumps: they don't load in some environments (table below), and an agent can route around them.
3. **CI plus branch protection** is the gate an agent can't edit its way past, *if* the workflow and test files need a human's approval to change.

## What loads where

This decides which layer you can rely on. From the Claude Code docs, checked 2026-11-12 [round1-MECHANICS MECH-1, MECH-4]. The project-thread column was corrected on 2026-11-13 from what such a thread actually loaded: it found the repo's skills and rules, including ones in nested `.claude` folders. Whether it runs repo hooks or agents has not been confirmed either way.

| | Local session (CLI, desktop, IDE) | Cloud session on one repo | **Cloud thread in a claude.ai project**  | `claude -p` in CI | `claude --bare -p` |
|---|---|---|---|---|---|
| `CLAUDE.md` + unscoped `.claude/rules/*.md` | ✓ | ✓ | ✓ | ✓ | ✗ |
| Rules with `paths:` | ✓ | ✓ | ✗ | ✓ | ✗ |
| Repo hooks (`.claude/settings.json`) | ✓ | ✓ | not confirmed: assume ✗ | ✓ (no trust prompt) | ✗ even with `--settings` |
| Repo skills and agents (incl. agent frontmatter hooks) | ✓ | ✓ | skills ✓; agents not confirmed | skills ✓; agent hooks ✗ | ✗ |
| Plugins | ✓ (installed) | account/project plugins | account/project plugins | `--plugin-dir` / Action inputs | `--plugin-dir` |
| Server-managed settings (Team/Enterprise) | ✓ | ✓ | ✓ | ✓ | ✓ |
| CI gates on the PR | ✓ | ✓ | ✓ | ✓ | ✓ |

Consequences for the design:
- The always-loaded rule `.claude/rules/testing.md` has **no `paths:`** so it reaches project threads.
- In project threads, count on the integrity rules as text only (and the skills), so **CI is the enforcement there**. That is why the kit's CI jobs (below) matter more than its hooks.
- For CI agent runs, use `claude -p` in the checkout (hooks run), not `--bare`.

---

## 1. User level (`~/.claude/`): your habits, every repo

Installed by `python install.py --user`. **No blocking hooks here**: enforcement belongs to the project so collaborators and CI see the same thing.

| File | What it does |
|---|---|
| `~/.claude/rules/testing-habits.md` | 6 lines, always loaded: find the repo's test command; narrowest test first, then the fast tier; red before green, expected values from the spec; never weaken a test to get green; evidence, not claims; stop with `BLOCKED:` when stuck. A repo's own `testing.md` wins. |
| `~/.claude/agents/test-reviewer.md` | A reviewer with no file-edit tools (`disallowedTools: Edit, Write, NotebookEdit`) that applies the checklist in guidelines §10. `@agent-test-reviewer` in any repo. |
| `~/.claude/settings.json` (merged) | `permissions.allow` for the usual test commands, so running tests doesn't prompt. |

On Windows, the PowerShell tool may be the main shell; add `PowerShell(...)` equivalents to the allow list if you rely on it [MECH-2].

**Plugins at user scope:** your language's LSP plugin. Keep Superpowers, Ralph Loop and Context7 as you have them. See `CLAUDE-PACKAGES.md` for when to use which.

## 2. Project level (committed in the repo): the main payload

Installed by `python install.py --project <repo> [--profile minimal|standard|strict] [--ci] [--env]`.

| Profile | For | Adds |
|---|---|---|
| `minimal` | Hobby repos, static sites, games | Always-loaded rule, CLAUDE.md block, guidelines, the guard hooks (PreToolUse protect/guard, Bash audit, ConfigChange), report and CI scripts. Stop hook off. Default tier **low**. |
| `standard` (default) | Most repos | + PostToolUse review of test edits, Stop hook, `spec-test-writer` and `test-reviewer` agents, the four skills |
| `strict` | Shared or high-risk repos | + `enforcement: "deny"` (refuse instead of asking), default tier **medium**, CODEOWNERS with `--ci` |

### Text

- **`.claude/rules/testing.md`**, always loaded (~25 lines): assumptions and ambiguity check, the tier rule, red before green, expected values from the spec, meaningful assertions, failure paths, mocks at boundaries, no hard waits; the MUST integrity rules; the `BLOCKED:` exit; evidence and "not tested" reporting. This **replaces** `claude-toolkit/.claude/rules/test-integrity.md` (same rule: ask the human, then they decide) [USE-5].
- **`CLAUDE.md`** gets a `## Testing` block between `testing-kit` markers: the fast and full commands, how to run one test, the repo's default tier, and pointers to the rules, guidelines, skills and agents. The guidelines are mentioned by path, not `@`-imported, so they cost nothing until needed [USE-2].
- **`docs/testing/GUIDELINES.md`** and **`docs/testing/REVIEW-PROTOCOL.md`**: copies of the long-form docs.
- **`.claude/testing-kit.json`**: the commands per tier (`setup`, `fast`, `full`, `mutation`), `junit_path` (`""` when the runner writes no JUnit XML), `extra_test_globs` and `not_test_globs` (your own test layout), `runner_files` (a Makefile or script the test command goes through), `default_tier`, `high_paths`, `enforcement` (`ask` or `deny`), `spec_readable`, and the Stop-hook switch. The installer detects the stack (Python with uv or pip, Node with Vitest/Jest/npm test, Go, Rust) or takes the command from `--fast`, and fills in the commands; check them. `GUIDE.md` has the full list of keys.
- **`docs/testing/KIT-GUIDE.md`**: a copy of `GUIDE.md`, so the people in the repo know what the prompts mean and how to upgrade or remove the kit.

### Hooks (`.claude/settings.json`, merged; scripts in `.claude/testing-kit/`, Python stdlib only)

| Event · matcher | Script | Behaviour | Rules |
|---|---|---|---|
| PreToolUse · `Edit\|Write\|NotebookEdit` | `protect_tests.py` | New test files: allowed. Existing test files (on disk **or tracked at HEAD**, so delete-and-recreate doesn't work): only pure additions pass. Changing or removing lines, adding skip/xfail/only or no-cover markers, or redefining an existing test name triggers the permission prompt with the reason. Snapshot/golden files, harness files (conftest, runner/coverage config, CI, `.claude/` settings and kit, `sitecustomize.py`, `*.pth`) and the test/coverage **sections** of `pyproject.toml`, `setup.cfg` and `package.json` likewise. Additions to `conftest.py` pass unless they add an autouse fixture or a `pytest_*` hook. | TG-14, 15, 17 |
| PreToolUse · `Bash\|PowerShell` | `guard_bash.py` | Asks before shell commands that write, move, delete or restore protected files (incl. `python -c`, `git checkout -- tests/`, `Remove-Item`), snapshot-update commands and retry flags. Blocks attempts to create the allow marker or start Claude with other settings. | TG-14, 17, 18 |
| Pre+PostToolUse · `Bash\|PowerShell` | `bash_audit.py` | Hashes every tracked test/harness file before each shell command and compares after, so *any* route (a script, `make`) that changes one is reported back. | TG-14, 15 |
| PostToolUse · `Edit\|Write` | `guard_test_edits.py` | Feedback (Claude must respond) on added sleeps, retries, skips, swallowed exceptions, assertion-free Python tests, and production code that checks for a test environment. `# kit: allow <reason>` exempts a line. | TG-07, 16, 18, 28 |
| SessionStart | `tests_on_stop.py baseline` | Notes what the working tree looks like when the session starts (kept per session in `.claude/testing-kit/.state/`, git-ignored). The first edit or shell command does the same if this hook didn't run. | TG-49 |
| Stop | `tests_on_stop.py` | If this session changed the working tree (or what is checked out) since it started, and that state hasn't already passed, runs the fast tier; on failure blocks the stop once with a grouped summary. Changes that were there before the session don't trigger a run. A message containing `BLOCKED:` always gets through; a second stop gets through with a warning to the user; while nothing changes after a failed run, later turns repeat the warning instead of running again. Off in `minimal`. | TG-04, 19, 49 |
| ConfigChange | `config_guard.py` | Refuses mid-session changes to project or local settings (e.g. `disableAllHooks` in `settings.local.json`). | ADV-2 |

**Asking, not denying.** By default a protected change shows Claude Code's permission prompt with the reason, so the human approves legitimate test changes in place, the same as the toolkit's "ask the user" rule. With `enforcement: "deny"` the change is refused, and the human either edits the file themselves or creates `.claude/allow-test-edits` (it stops counting after 2 hours; the agent can't create it; it's gitignored). Whether a hook's "ask" still prompts under `bypassPermissions` is an open question; use `strict` if you run in that mode.

**Permissions** (merged): deny reading `.env*`; deny Write/Edit of the allow marker and `settings.local.json`.

**Windows.** The installer picks the Python command that works on the machine (`py`, `python` or `python3`) and writes it into the hook commands; paths are quoted. Hooks need Python ≥ 3.9 on PATH. `onFailure: "block"` (Claude Code ≥ 2.1.295) is deliberately **not** used, because a wrong interpreter would then block every edit [MECH-3, MECH-7].

### Agents and skills

| | What | When |
|---|---|---|
| `spec-test-writer` agent | Writes tests from the spec only. Its frontmatter hook is an **allowlist**: read only docs, specs, README, existing tests, type stubs and schemas (`spec_readable`); write only test files; run only the configured test commands. Works for flat repos. Reduces, doesn't eliminate, leakage: the parent's prompt and stack traces can still leak. Doesn't run in project threads or `-p` (agent hooks don't load there). | Medium/high tier |
| `test-reviewer` agent | Checklist reviewer, no edit tools, takes a lens | Before a PR; from `/test-review` |
| `/write-tests` | Tier → assumptions → spec tests (delegates to `spec-test-writer` at medium+) → red → implement → green → report | Any behaviour change |
| `/run-tests` | Runs the right tier and reports RAN / FAILED by cause / NOT TESTED / ANOMALIES via `test_report.py` | Before saying you're done |
| `/mutation-check` | Diff-scoped mutmut / Stryker / cargo-mutants / PIT / go-mutesting, survivors explained | Medium/high tier |
| `/test-review` | The multi-agent review protocol over the branch's diff | Before a PR with test changes |

If `claude-toolkit` already links a `run-tests` skill into the repo, the installer leaves the link alone and reports it.

### CI (`--ci`; one workflow, `.github/workflows/testing-kit.yml`, with setup steps for the detected stack)

| Job | Checks | Why |
|---|---|---|
| `test` | Fast tier with JUnit output, the four-part report, diff coverage on PRs | TG-31, 33, 49 |
| `test-guard` (`test_diff_guard.py`) | Against the merge base: deleted or renamed-away test files, removed test functions, added skip/xfail/only, changed snapshots, changed harness files or test/coverage config sections, test-environment checks and no-cover pragmas in production code. Warns on removed assertions, added sleeps/retries, new tests with no failure path. A human's `allow-test-changes` PR label overrides. | TG-14..18, 33, 35 |
| `base-tests` (`base_tests.py`) | Puts the merge base's tests, harness **and runner files** over this branch's code (removing branch-only test/harness files) and requires every test that passed on the base to still pass. Editing, skipping, deleting, renaming or shadowing tests can't satisfy it. Without a JUnit report (`"junit_path": ""`: `go test`, `cargo test`, a Makefile target) it compares the two runs' exit codes instead: coarser, and it asks for a human when the base is already red. | ADV-5, 6, 7 |
| `all-green` | The one required status check | |
| `flake-finder` (scheduled, Python only) | Repeats the fast tier in random order to surface intermittent failures | TG-32 |

**For CI to bind** (the installer prints this) [ADV-10]:
- A branch ruleset on the default branch: require `all-green`, block force pushes and direct pushes.
- In `strict`: `CODEOWNERS` for `.github/`, `.claude/`, `conftest.py`, `pyproject.toml`, `package.json`, with "require review from Code Owners". On a solo repo this stops you merging your own PR without an admin bypass, so it's opt-in.
- Without these, an agent can edit the workflow in the same PR.

Not built yet (proposals): a mutation-score gate job for high tier, and per-path tier detection in CI.

## 3. Environment level: cloud sessions, devcontainers, CI runners

| Where | Do this |
|---|---|
| **Cloud environment** | **Setup script** (environment settings; runs as root; cached if it finishes in ~5 min): system tools only (`templates/env/setup-script.sh`). **SessionStart hook** (`--env`): `session_start.sh`, cloud-only (`CLAUDE_CODE_REMOTE=true`), installs project deps when the lockfile hash changed and prints the test command. It does **not** install plugins, because a plugin installed from a hook only loads next session: enable plugins on your account or in Project settings instead [MECH-8]. In project threads the repo's SessionStart hook doesn't run either, so put dependency installs in the environment's setup script for those. |
| | Keep `commands.fast` under the 2-minute Bash default; size parallelism to ~4 vCPU (`-n 4`). Credentials go in the environment's network secrets, not plain environment variables. |
| **Devcontainer** (optional) | `templates/env/devcontainer.json`: one image for people, CI and agents; non-root; nothing mounted from your home folder. |
| **CI agent runs** | `anthropics/claude-code-action@v1` with `plugin_marketplaces` / `plugins` inputs, or `claude -p` in the checkout. Not `--bare`: it skips hooks even with `--settings`, and skips skill discovery. To fail when a plugin didn't load, use `--output-format stream-json --verbose` and read the first `system/init` event [MECH-4, MECH-11]. |
| **Managed settings** | Only if the org is on Team/Enterprise (open question for the maintainer). A managed hook applies to every repo, so it must exit 0 in repos without the kit; never point it at a repo-relative script with `onFailure: "block"` [MECH-6]. |

---

## Precedence

1. CI gates with branch protection
2. Project hooks and permissions
3. Project `testing.md` (always loaded) and `CLAUDE.md`
4. User `testing-habits.md`
5. Plugin skills (Superpowers TDD etc.): advice that works alongside the hooks.

The human's instruction in the session wins over text. Hooks still fire: the permission prompt is where the human says yes.
