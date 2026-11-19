# Changelog

## 0.5.0 (2026-11-19): protect the base branch's tests, not work in progress

Found by running several agent sessions in parallel in a real project: each was asked to approve every
changed line of test files it had written minutes before, and nobody could usefully judge those prompts.

**The base-branch rule**
- A test is the specification once it is on the base branch. The edit hook now reads each test file as
  the base branch had it where the current branch left it. A test file the base branch doesn't have,
  and tests the branch added to a file it does have, can be reworked without a prompt. Changing or
  removing a base line, adding `skip`/`only`, or defining a base test a second time still asks. A base
  test file deleted on the branch and written again now asks (it did not before).
- The shell guards follow the same rule: `rm`, `mv` or `git mv` on a test that is new on the branch no
  longer asks, and the audit after a shell command no longer reports it. Harness files (runner config,
  `conftest.py`, CI, the kit) are protected as before, new or not.
- New config key `base_branch` (for example `"origin/main"`). The installer fills it in on a new
  install, preferring origin's branch. Left empty, the hooks use origin's default branch as the clone
  recorded it. When neither is there the hooks protect every test file on disk, as 0.4 did. Existing
  installs keep their config: add the key yourself, or rely on origin's default.
- `--check` reports the base branch in use, and warns when it can't be worked out or isn't in the clone.
- The CI gates run by hand without `--base` use `base_branch` first, which helps in a clone that doesn't
  record origin's default branch.
- Because the base branch now decides which tests are protected, git commands that move it ask first:
  `git branch -f/-D/-m`, `git checkout -B`, `git update-ref`, `git symbolic-ref`,
  `git remote set-head`, a fetch or push straight into the base branch, and a `git reset` to a commit
  from before the branch left the base (which would keep newer base tests on disk as if they were new).
- On a filesystem that ignores case (macOS, Windows), a path spelled with different capitals still
  finds the base branch's copy.

What this gives up: Claude can write a test, see its code fail it, and loosen its own new test without
a prompt. CI never caught that either. The defences are the ones for any new test: red before green
(TG-04), expected values from the spec (TG-05), the `test-reviewer` agent and the mutation check.

**Sessions that start above the project**
- The hooks find the project from the kit's own location, so they work when Claude starts in a folder
  above the repository (`CLAUDE_PROJECT_DIR` names that folder then).
- The shell guard resolves relative paths from the shell's directory. Before, `rm ../tests/test_x.py`
  run from a subfolder was not noticed.

**Also**
- The CI gate blocks a committed draft of a test (`x.test.draft.ts`, `x.draft.test.ts`,
  `test_x.draft.py`), so a working copy kept out of the guards can't be merged.
- Copy commands (`cp`, `rsync`, `install`, `ln`, `Copy-Item`) are checked by their destination only.
  Copying a protected test to a new file no longer asks.

92 new tests.

## 0.4.1 (2026-11-13): documentation is not production code

Found by the first install into a real project: the CI gate reported the installed guidelines as production code that checks for a test environment.

- The CI gate and the edit hook no longer apply TG-16 (code that detects tests) and TG-33 (coverage pragmas) to documentation (`.md`, `.markdown`, `.mdx`, `.rst`, `.txt`, `.adoc`), which may describe both. Code files are checked as before. Two new tests, seen to fail first.

## 0.4.0 (2026-11-13): drop into any repo, and stay there

Found by installing the kit into existing Python, Node and Go repos and into one with its own Claude setup.

**Guide**
- New `docs/GUIDE.md`: set up, the live check that the hooks fire, daily use, configuration, stacks,
  upkeep and troubleshooting. Installed into each repo as `docs/testing/KIT-GUIDE.md`.

**Any repo**
- Any stack works: `--fast`, `--full` and `--setup` set the test commands when they are not detected.
  Python repos without packaging files are detected (pytest config or test files alone).
- One workflow for every stack, `.github/workflows/testing-kit.yml`. Go, Rust and hand-given commands
  get it too (there was no template for them). The command comes from your config and may contain
  quotes, backslashes or several lines. The file was `tests.yml`, a name many repos use for their own
  CI; an upgrade removes the old kit file.
- The base-tests gate compares exit codes when the test command writes no JUnit report
  (`"junit_path": ""`, as with `go test`, `cargo test` or `npm test`): coarser, but it still catches a
  bug hidden by editing its test. Before, the gate could only say that no tests were collected.
- Files the test command goes through (a Makefile, a script, an npm script) are recorded as
  `runner_files` and taken from the base branch in CI.
- New config keys `extra_test_globs`, `not_test_globs` and `extra_harness_globs` for layouts the built-in
  patterns miss; test files of Ruby, Kotlin, C#, Swift, PHP, Elixir and Dart are recognised.
- The gates, the skills and the workflow use the repo's default branch instead of assuming `main`.
- CODEOWNERS entries go where the repo already keeps its CODEOWNERS (a new file in `.github/` would
  switch off one kept at the root or in `docs/`).
- The installer says which test files it recognises, and warns when the target is not the root of a git
  repository.

**Upkeep**
- The installer records what it wrote in `.claude/testing-kit/manifest.json`. Re-running it upgrades:
  untouched kit files are updated, files the kit dropped are removed, a rule, skill, agent, doc or
  workflow you changed is kept (the new version goes beside it as `<name>.kit-new`), and the profile and
  options of the last run are remembered. The scripts in `.claude/testing-kit/` are always replaced as a
  set; one you had changed is saved as `<name>.yours`.
- `--uninstall` removes the kit's hooks, permissions, `CLAUDE.md` block and unchanged files.
- `--check` shows the installed version, what you changed, pending merges, a registered hook whose
  script is missing, a `CLAUDE.md` block or workflow that no longer shows the config's command, and the
  recognised test files. `--check --run` runs the fast tier once and times it.

**Hooks**
- End of turn: the fast tier runs only when the session changed something. A SessionStart hook notes
  what the working tree looked like, so changes that were already there, turns that only read files, and
  a state that already passed run nothing. A failing run is repeated once, then only reported until
  something changes.
- Protected sections of `package.json` (`"jest"`, `scripts.test`, ...) are compared now. The patterns
  never matched before.

**Fixed**
- CI: the `base-tests` job never received the `allow-test-changes` label; the report upload was empty
  (`.reports/` is a hidden folder); `cache: pip` and `cache: npm` were written without a file to key on;
  a setup failure in the gate is explained; files that only pin a tool version (`.python-version`,
  `.nvmrc`) stay in the branch copy.
- Installer: a command with a quote, backslash or newline stopped it with a JSON error; `--owner @team`
  wrote `@@team`; `settings.json` was rewritten with `\u` escapes and other indentation; an invalid
  `settings.json` stopped the run after files were written; every kit file that differed counted as a
  conflict; `--force` reset the config; `--check` mistook `pytest -m "not slow"`, `cd x && ...` and
  `./script` for missing programs.
- Windows: a hook read its input in the system code page, so an edit whose text had an accent or a curly
  quote was not checked; it is read as UTF-8 now. The reports and the installer stopped with
  `UnicodeEncodeError` on a name or runner output the pipe could not carry; such characters are shown as
  `\uXXXX`. Git's answers (file names, the committed config) are read as UTF-8.

**Tests**
- 86 new tests in `tests/test_drop_in.py`. Each was seen to fail without its fix (run before the fix, or
  with the fix undone in a scratch copy), except for the last Windows item (how git's output is decoded),
  which no test can fail on Linux or macOS.
- Four existing tests changed, on purpose. Three read `.github/workflows/testing-kit.yml` instead of
  `tests.yml`, and one of them expects `python3 "$KIT/..."` where the workflow said `python`. The test
  that keeps the author's own project names out of installed docs checks them by digest now; a new test
  does the same for every installed file, and found one leftover reference in the guidelines (removed).

**Not verified**
- The hooks firing inside a live Claude Code session (the guide has a two-minute check), and the
  generated workflow running in GitHub Actions (it passes `actionlint` for every detected stack).
- The Windows fixes in a live session on Windows. The tests force a Windows code page onto the pipes, on
  every system the suite runs on.

## 0.3.0 (2026-11-13): code-improvement pass

**CI gates**
- Both gates read `.claude/testing-kit.json` from the base branch, so a PR can't point them at a fake test
  command or shrink what counts as a test. The workflow templates run the gate scripts from the base
  branch's copy when it has one.
- A newly added `setup.cfg` / `pyproject.toml` / `package.json` with a runner section is flagged by the
  diff guard and ignored by the base-tests run.
- Non-ASCII file names are handled; `--base` without a value is a usage error, not a traceback; restoring
  thousands of base test files no longer overflows the command line.

**Hooks**
- `protect_tests`: rebinding the code under test in a test file (a second import source, a `def`, `class`
  or assignment with the imported name) asks. Uses the Python AST, so multi-line imports work.
- `guard_bash`: looks inside `bash -c "..."`, `sh -c`, `eval`; catches `dd of=<file>`, `--output=<file>`
  and `find ... -delete/-exec`; `cd -`, `cd ~`, `cd $VAR` no longer confuse path resolution.
- `bash_audit`: one snapshot per tool call (parallel Bash calls used to overwrite each other's); also
  covers tests that aren't committed yet.
- `tests_on_stop`: runs when Claude committed during the session (a clean tree used to skip it); ending
  on a question lets Claude stop but tells the user the tests fail; a stale report from an earlier run is
  never read.
- `no_src_access`: nothing can be chained after a configured test command; `git log -p` and similar are
  blocked for the spec-test-writer.
- `guard_test_edits`: `kit: allow` can't excuse test detection in production code; test names are matched
  whole.
- `kitlib`: `./.github/...` paths matched no glob (the leading dot was stripped); globs ignore case on
  macOS and Windows; dead config removed.

**Installer**
- `settings.json`, `CLAUDE.md` and `.gitignore` are never written through a symlink; invalid
  `settings.json` stops the install with a clear message; the detected Python command uses the
  interpreter name that exists on the machine (`python3` on Debian/Ubuntu).

**Repo**
- The kit has its own CI on Linux, macOS and Windows, Python 3.9 to 3.13. Its first run found that the
  installer crashed on Python 3.9 (`Path.write_text(newline=)` needs 3.10); fixed.

## 0.2.0 (2026-11-12)
Fixes for the 40 findings of the second review round.

## 0.1.0 (2026-11-12)
First version.
