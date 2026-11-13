# Changelog

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
