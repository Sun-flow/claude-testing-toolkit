# Testing kit guide: set up, use, keep up

How to put the testing kit into a repository, what changes for the people and agents who work there, and
how to keep it current or take it out again. The kit itself lives at
https://github.com/Sun-flow/claude-testing-toolkit; if you are reading this as `docs/testing/KIT-GUIDE.md`
in your own repo, the installer copied it in.

Contents: [What you get](#what-you-get) · [Set up](#set-up) · [Check that the hooks fire](#check-that-the-hooks-fire)
· [Daily use](#daily-use) · [Configuration](#configuration) · [Stacks](#stacks) · [Upkeep](#upkeep)
· [Troubleshooting](#troubleshooting)

## What you get

Four layers. Each one catches what the layer above it lets through.

| Layer | What it is | Can an agent get around it? |
|---|---|---|
| Rules | `.claude/rules/testing.md` and a `## Testing` block in `CLAUDE.md`, loaded in every session: how to write tests, the commands to run, and never to weaken a test to get green | Yes. It is text |
| Hooks | Scripts in `.claude/testing-kit/` that Claude Code runs before and after edits and shell commands, and when Claude tries to finish | With effort. They are speed bumps, and they only run where hooks load (table below) |
| CI gates | Two jobs in `.github/workflows/testing-kit.yml`: did the branch weaken the suite, and do the base branch's tests still pass against the branch's code | Not from inside the pull request, once branch protection is on |
| Branch protection | You switch it on once on GitHub: `all-green` required, force pushes blocked, optionally Code Owner review | No |

It also adds four skills (`/write-tests`, `/run-tests`, `/test-review`, `/mutation-check`), two agents
(`spec-test-writer`, `test-reviewer`) and the long-form guidelines in `docs/testing/GUIDELINES.md`.

**Where it works.** The same repo behaves differently depending on where Claude runs:

| Where Claude runs | Rules and `CLAUDE.md` | Skills | Hooks | Agents |
|---|---|---|---|---|
| Claude Code in the repo (terminal, desktop app, IDE) | yes | yes | yes | yes |
| Claude Code cloud session opened on the repo | yes | yes | yes | yes |
| `claude -p` in a checkout (scripts, CI) | yes | yes | yes, but not with `--bare` | the `spec-test-writer`'s own hook does not apply |
| A claude.ai project thread with the repo attached | yes | yes | not confirmed: assume no | not confirmed |
| A chat that only reads files | no | no | no | no |

The project-thread row is from what one such thread loaded on 2026-11-13; the rest is from the Claude Code
documentation. Wherever the hooks don't run, the CI gates are the layer that holds, which is why step 6
below matters more than it looks.

## Set up

You need: a git repository (install at its root), Python 3.9 or newer on PATH, and a checkout of the kit
somewhere outside the repository. Allow ten minutes. On Windows, type `py` or `python` where this guide
says `python3`.

1. **Get the kit.** `git clone https://github.com/Sun-flow/claude-testing-toolkit`. The commands below run
   from that folder. Nothing is installed on your machine; the kit is standard-library Python.
2. **See what it would do.** `python3 install.py --project /path/to/repo --ci --dry-run` prints every file it
   would create or change, and writes nothing.
3. **Install.** `python3 install.py --project /path/to/repo --ci` (add `--owner your-team` if you want
   CODEOWNERS for the test harness). Read the first lines of the output:
   - `Detected stack: ...; fast tier: ...` is the test command the kit will run. If it says `none yet`, or
     the command is not the one you use, see [Stacks](#stacks).
   - `Test files recognised: N (...)` is what the kit will protect. If your tests are missing from it, see
     `extra_test_globs` under [Configuration](#configuration).
   - `CONFLICT` marks a file of yours that has the name of a kit file (often an existing `run-tests`
     skill). Yours is kept and the kit's version is beside it as `<name>.kit-new`.
4. **Check it.** `python3 install.py --check /path/to/repo --run` verifies the hooks are registered and can
   start, then runs the fast tier once, times it, and counts the tests in its report. Fix what it reports
   before going on. A fast tier that is red or slow here will be red or slow at the end of every turn.
5. **Restart Claude Code** in the repo. Hooks load when a session starts. Then do the two-minute check in
   the next section.
6. **Commit, and switch on the part that binds.**
   - Commit everything the installer wrote and open a pull request. The CI gates count kit files as test
     harness, so this pull request needs the `allow-test-changes` label.
   - On GitHub, create a label named `allow-test-changes`. Whoever may add it is whoever may approve a
     change to tests.
   - In the branch ruleset for the default branch: require the `all-green` status check, block force
     pushes, and (with `--owner`) require review from Code Owners. Until this is done, a pull request can
     edit the workflow that checks it.

### Options

| Option | What it does |
|---|---|
| `--profile minimal` | Guard hooks, rules and CI scripts only. No end-of-turn test run, no skills or agents. For small or hobby repos |
| `--profile standard` | The default: everything in this guide. Protected changes ask you first |
| `--profile strict` | As standard, but protected changes are refused instead of asked, and the default risk tier is medium. For shared or high-risk repos |
| `--ci` / `--no-ci` | Add (or remove again) the GitHub Actions workflow, and for Python a weekly flake finder |
| `--owner NAME` | With `--ci`: write CODEOWNERS entries for `.github/`, `.claude/` and test config. If the repo already has a CODEOWNERS file, the kit's lines go beside it for you to merge |
| `--env` / `--no-env` | Add a SessionStart script for cloud sessions that installs dependencies when the lockfile changed |
| `--fast CMD`, `--full CMD`, `--setup CMD` | Set the test commands yourself (see [Stacks](#stacks)) |
| `--tier low\|medium\|high` | The repo's default risk tier |
| `--dry-run` | Show the plan, write nothing |
| `--force` | Take the kit's version of files you changed. Your config is still kept |

Options are remembered: a later run without flags uses the profile and options of the last one.

`python3 install.py --user` is separate and optional. It adds a short rule file of personal testing habits
and a reviewer agent to `~/.claude`, for every repo you work in, and lets the usual test commands run
without a permission prompt. It adds no hooks.

### What the installer changes

| Path | What happens |
|---|---|
| `.claude/testing-kit/` | Created: the hook and gate scripts, and `manifest.json` (what was installed, for upgrades) |
| `.claude/testing-kit.json` | Created once with the detected commands. Yours from then on |
| `.claude/rules/testing.md`, `.claude/skills/`, `.claude/agents/` | Created. An existing file with the same name is kept |
| `.claude/settings.json` | Merged: the kit's hook entries, six `permissions.deny` rules and `"disableAllHooks": false` are added. Your own hooks and permissions stay, and the file keeps its indentation |
| `CLAUDE.md` | One block between `testing-kit` markers is added or refreshed. The rest is not touched |
| `docs/testing/` | Created: the guidelines, the review protocol and this guide |
| `.gitignore` | The kit's ignore lines are added (session state, `.reports/`, the allow marker, local settings) |
| `.github/workflows/testing-kit.yml`, `flake-finder.yml`, CODEOWNERS | Only with `--ci` (and `--owner`) |

It never writes through a symlink, and if `.claude/settings.json` or `.claude/testing-kit.json` is not
valid JSON it stops before changing anything.

## Check that the hooks fire

`--check` proves the scripts run. Only a real session proves that your Claude Code loads them, and that is
the one thing the kit's own tests cannot check for you. In a new session in the repo:

1. Type `/hooks`. You should see entries for PreToolUse, PostToolUse, Stop, SessionStart and ConfigChange
   whose commands point at `.claude/testing-kit/`.
2. Ask Claude to change an expected value in an existing test. You should get a permission prompt whose
   reason starts with `Testing kit:` (in the strict profile, a refusal with the same text). Decline it.
3. Ask Claude to add a comment to a source file and stop. When it finishes, there is a pause while the fast
   tier runs, and nothing else if the tests pass. Then ask a plain question: no pause this time, because
   nothing changed.
4. Optional: ask Claude to break a function on purpose and stop. It is told `The fast test tier fails` and
   keeps working, or stops with a report that starts with `BLOCKED:`.

If none of that happens, the hooks are not loading: see [Troubleshooting](#troubleshooting).

## Daily use

**What Claude does differently.** It reads the rules at the start of every session: list assumptions
first, write the test before the code and show it failing, take expected values from the spec and not from
running the code, cover failure paths, and report what was run and what was not. If it is stuck it stops
with a report that starts with `BLOCKED:` instead of bending a test.

**Skills you can call.**

| Skill | Use it when | What it does |
|---|---|---|
| `/write-tests <ticket or description>` | Adding behaviour or fixing a bug | Tier, assumptions, tests from the spec, red, implement, green, report. At medium and high tier the tests are written by the `spec-test-writer` agent, which cannot read the source |
| `/run-tests [path or tier]` | Before calling work done | Runs the narrowest tests, then the fast tier, and reports what ran, what failed by cause, what was not tested, and anything odd |
| `/test-review [base branch]` | Before a pull request that touches tests | Three independent reviewers with different lenses, verified findings, numbered proposals. Nothing is applied without you |
| `/mutation-check [base branch]` | Medium or high risk changes | Mutation testing on the changed lines, to see whether the tests can fail |

**Prompts you will see.** A prompt that starts with `Testing kit:` means Claude is about to do something
the kit treats as a change to the suite itself:

| Claude is about to | Why it asks |
|---|---|
| Change or remove lines in an existing test, or add `skip`, `xfail` or `.only` | A failing test is more often right than wrong. New test files and pure additions never ask |
| Edit runner or coverage config, `conftest.py`, CI workflows, or the kit's own files and settings under `.claude/` | These decide what the tests check, and what checks the tests |
| Regenerate a snapshot or golden file | Each changed hunk needs a human's eyes |
| Run a shell command that writes, moves or deletes one of the above | The same change by another route |

Approve when you agree with the change, decline when you don't. In the strict profile there is no prompt:
make the change yourself, or run `touch .claude/allow-test-edits` to allow test edits for two hours
(Claude cannot create that file).

**At the end of a turn.** When Claude has changed something in the session and tries to finish, the kit
runs the fast tier. If it fails, Claude is sent back once with the failures. If it still fails, Claude may
stop and you see `Testing kit: fast tests fail ... The work is not done.` A turn in which Claude only read
files or answered a question runs nothing, and neither do changes that were already in your working tree
when the session started. If the suite was red before Claude touched anything, Claude is told not to fix
unrelated code and to stop with `BLOCKED:` naming the tests that already failed.

**In a pull request.**

| Check | It fails when | What to do |
|---|---|---|
| `test-guard` | The branch deleted, skipped or renamed away tests, changed snapshots, harness files or test config, or made production code check whether it runs under a test | If that was intended, a person adds the `allow-test-changes` label and the gates re-run. Otherwise revert it |
| `base-tests` | A test that passes on the base branch fails against the branch's code, with the base's copy of the tests | Fix the code. If the old test was wrong and you agreed to change it, add the label |
| `all-green` | Any of the above, or the fast tier itself | This is the one check to require |

`test-guard` also prints warnings that do not fail the check: removed assertions, added sleeps or retries,
new tests with no failure path. They are worth a look in review.

**Risk tiers.** `default_tier` in the config says how much independence the tests need. Low: tests from
the spec, written before the code. Medium: tests written from the spec in a separate context, plus a
fresh-context review. High: also an oracle that is not an LLM and a mutation score. List riskier paths in
`high_paths` (for example `["payments/**", "auth/**"]`); the details are in `docs/testing/GUIDELINES.md` §1.

## Configuration

`.claude/testing-kit.json` belongs to you. The installer creates it once and afterwards only changes what
you ask for with a flag. After editing commands by hand, re-run the installer so `CLAUDE.md` and the
workflow show the same command (`--check` tells you when they don't).

| Key | Meaning |
|---|---|
| `commands.fast` | What runs at the end of a turn and in CI. Keep it under two minutes |
| `commands.full` | The whole suite, for `/run-tests full` and before releases |
| `commands.setup` | Installs dependencies. The base-tests gate and the cloud SessionStart script run it |
| `commands.mutation` | Optional: your own mutation-testing command for `/mutation-check` |
| `junit_path` | Where `commands.fast` writes JUnit XML. `""` means it writes none (see [Stacks](#stacks)) |
| `extra_test_globs` | Patterns for test files the kit does not recognise by itself, for example `["checks/**"]` |
| `not_test_globs` | Production files that only look like tests, for example `["src/**/test_runner.py"]` |
| `extra_harness_globs` | More files that count as test harness (asked about locally, blocked in CI) |
| `runner_files` | Files the test command goes through, such as a Makefile or `scripts/test.sh`. The base-tests gate takes them from the base branch, so a pull request cannot redefine what `make test` does. The installer fills this in from your commands |
| `harness_sections` | Sections of shared files that are test config, for example `scripts.test` in `package.json` |
| `default_tier`, `high_paths` | Risk tiers, as above |
| `enforcement` | `"ask"` (prompt) or `"deny"` (refuse). The strict profile sets `deny` |
| `stop_hook.enabled`, `stop_hook.timeout_s` | The end-of-turn run: on or off, and its time limit in seconds (300) |
| `src_dirs`, `spec_readable` | What the `spec-test-writer` agent may not read, and what it may |

Patterns are gitignore-style: `*` within a folder, `**` across folders.

## Stacks

| Repo | Detected by | Fast tier the installer writes | CI gate compares |
|---|---|---|---|
| Python | `pyproject.toml`, `requirements.txt`, `setup.py`, or pytest config or test files alone | `python3 -m pytest -q --junitxml=.reports/junit.xml` (with `uv run` when there is a `uv.lock`) | test by test |
| Node with Vitest or Jest | `package.json` | the runner with a JUnit reporter (Jest needs the `jest-junit` package) | test by test |
| Node with another runner | a `test` script in `package.json` | `npm test` | exit codes |
| Go | `go.mod` | `go test ./...` | exit codes |
| Rust | `Cargo.toml` | `cargo test` | exit codes |
| Anything else | not detected | none: give it with `--fast` | exit codes |

**Anything else.** Pass your command: `python3 install.py --project . --ci --fast "make test" --setup "make deps"`.
The kit works with any command that exits non-zero when a test fails. The generated workflow then has a
comment where your toolchain steps go; add them in both jobs. In a monorepo, install once at the root and
point the commands into the folders (`--fast "cd api && pytest -q"`). When a repo holds more than one
stack, the installer takes the first it finds (Python packaging files, then `package.json`, `go.mod`,
`Cargo.toml`), so say which one you mean with `--fast`.

**Test by test, or exit codes.** With a JUnit report the base-tests gate names each test that broke, and
it copes with a base branch that already has failures. Without one (`"junit_path": ""`) it compares the
exit code of the base's tests on the base with their exit code on your branch's code. That still catches
a bug hidden by editing its test, but it cannot name the test, and if the base is already red it asks for
a person. If your runner can write JUnit XML (`gotestsum --junitfile`, `cargo nextest` with a JUnit
profile, most others), add that to `commands.fast` and set `junit_path`.

**Limits to know about.**
- The base-tests gate works on test *files*. Tests that live in the same file as the code (Rust unit tests
  in `src/`, doctests) travel with the code, so the gate cannot hold them still. Integration tests in
  `tests/` are covered.
- The workflow runs on `ubuntu-latest`. If your tests need another system, change `runs-on` (the file is
  then yours; see Upkeep).
- Which tests were removed is worked out for Python, JavaScript/TypeScript and Go test functions. For other
  languages the kit still sees deleted, renamed and skipped test files.

## Upkeep

**Which version is installed?** `python3 install.py --check /path/to/repo` shows the installed version and
profile, the files you have changed since, anything waiting to be merged, and whether a newer installer is
being used than the one that installed it. Run it whenever something seems off. It changes nothing.

**Upgrading.** Update your checkout of the kit (`git pull`), then run the installer on the repo again with
no other flags: `python3 install.py --project /path/to/repo`. It reads `.claude/testing-kit/manifest.json`
and:
- updates every kit file you have not touched, and removes ones the new version no longer has;
- keeps a rule, skill, agent, doc or workflow you changed, and writes the new version beside it as
  `<name>.kit-new`. Merge what you want and delete the `.kit-new` file, or take the kit's with `--force`;
- always brings the scripts in `.claude/testing-kit/` to the new version, because they only work as a
  set. If you had changed one, your copy is saved beside it as `<name>.yours`;
- keeps `.claude/testing-kit.json` as it is, refreshes the kit's entries in `.claude/settings.json`, and
  rewrites the `CLAUDE.md` block.

Then restart running sessions, run `--check --run`, and commit. The upgrade pull request needs the
`allow-test-changes` label, like the first one. `CHANGELOG.md` in the kit says what each version changed.

**Changing your mind.**

| You want | Run |
|---|---|
| Another test command | `--project . --fast "<command>"`, or edit the config and re-run the installer |
| Another profile | `--project . --profile minimal` (or `standard`, `strict`). Files of the old profile that you did not change are removed |
| No CI workflow after all | `--project . --no-ci` |
| The default risk tier changed | `--project . --tier medium` |

**Keeping the end of a turn quick.** The fast tier runs each time Claude finishes a turn with changes.
When it grows past a minute or two, point `commands.fast` at a quick subset (unit tests, or
`-m "not slow"`) and leave the whole suite in `commands.full` and in your own CI. `--check --run` times it.

**Taking it out.** `python3 install.py --uninstall /path/to/repo` (add `--dry-run` to see the plan first)
removes the kit's hook entries and permissions from `.claude/settings.json`, the block from `CLAUDE.md`,
and every kit file you have not changed. Files you changed are kept and listed. `.gitignore` is left
alone. Afterwards restart any running Claude Code session in the repo (a session started earlier still
calls the removed scripts and blocks every tool call until it is restarted), commit, and on GitHub take
`all-green` out of the required checks.

**Installs from before 0.4.0** have no manifest, so nothing recorded their options: pass the flags you
used then (`--ci`, `--owner`, `--profile`) once more. That run replaces the scripts, moves the workflow
from `tests.yml` to `testing-kit.yml`, and marks other differing files as `CONFLICT`, because it cannot
tell an older kit file from one you edited. If you never edited them, run once more with `--force`.

## Troubleshooting

| What you see | Cause and fix |
|---|---|
| Every edit and shell command is blocked | A hook script that `.claude/settings.json` names is missing (deleted, or the session was started before an uninstall). Python then exits with 2, which Claude Code reads as "blocked". Run `--check`: it names the missing script. Re-run the installer to restore it, then restart the session. To get unstuck first, set `"disableAllHooks": true` in `.claude/settings.json` yourself and restart |
| Hook errors on every tool call, but nothing is blocked | The Python that the hook commands name is not on PATH in the shell Claude Code uses, so the protections are off. `--check` reports it. Put Python 3.9+ on PATH and re-run the installer (it writes the name that works on this machine) |
| Nothing happens: no prompts, no test run | Restart the session (hooks load at start). Look at `/hooks`. Check that `.claude/settings.json` does not say `"disableAllHooks": true` and that you accepted the folder's trust prompt. In a project thread hooks may not load at all: rely on CI there |
| `pytest is not installed for python3` from `--check` | The hooks run the fast tier with the Python on PATH. Start Claude Code from the activated virtualenv, or put the interpreter in the command: `.venv/bin/python -m pytest ...` |
| Claude keeps trying to fix tests it did not break | The suite was red before the session. Get the fast tier green, or point `commands.fast` at the part that passes. Claude may also stop with `BLOCKED:` |
| A long pause at the end of every turn | The fast tier is slow. See "Keeping the end of a turn quick". `stop_hook.timeout_s` is the limit, `stop_hook.enabled: false` turns it off |
| Prompts about a file that is not a test | Its name matches a test pattern. Add it to `not_test_globs` |
| Tests that are not protected | `--check` lists how many test files it recognises. Add your layout to `extra_test_globs` |
| `test-guard` fails on the pull request that installs or upgrades the kit | Expected: kit files are test harness. Add the `allow-test-changes` label |
| `base-tests` exits 2 with "No tests were collected on the base" | `commands.fast` wrote no JUnit report at `junit_path`. Fix the command or the path, or set `"junit_path": ""` |
| `base-tests` says setup failed | `commands.setup` failed in a clean copy of the branch. The output is shown. If it only fails because new config files were left out of that copy, a person can add the label |
| The workflow fails before any test runs | The toolchain or dependency steps are missing or wrong for your stack. Edit them in `.github/workflows/testing-kit.yml`, in both jobs |
| Claude cannot read `.env` | The kit adds `Read(./.env)` and `Read(./.env.*)` to `permissions.deny`. Remove them from `.claude/settings.json` if your work needs them |
| `--check` says CLAUDE.md or the workflow shows another fast command | The config was edited by hand. Re-run the installer |
| A report shows `\u0442\u0435\u0441\u0442` where a name should be | Windows: the name has characters the system code page lacks, and the kit prints them escaped rather than stop. Python's UTF-8 mode (`PYTHONUTF8=1` in the environment) prints them as they are |
