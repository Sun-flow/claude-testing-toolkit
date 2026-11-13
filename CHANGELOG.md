# Changelog

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
