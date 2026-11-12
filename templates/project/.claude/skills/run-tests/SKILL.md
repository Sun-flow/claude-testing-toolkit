---
name: run-tests
description: Run the project's tests (or those related to the current change) and report the result in four parts - what ran, what failed grouped by cause, what was NOT tested, anomalies. Use before saying work is done.
argument-hint: "[path, pattern or tier: fast|full]"
---
Changed files: !`git status --porcelain`

1. Get the commands from `.claude/testing-kit.json` (`commands.fast`, `commands.full`) or the `## Testing` block in CLAUDE.md. Don't invent one; if none exists, say so and propose one.
2. Run the narrowest tests for $ARGUMENTS (or for the changed files), then the fast tier. Run the full tier only if asked or before a release.
3. Summarise with `python .claude/testing-kit/test_report.py` (reads the JUnit file at `junit_path`). If there's no JUnit output, report the runner's own summary line.
4. Report: the exact command(s); RAN / FAILED (grouped by cause) / NOT TESTED (skips, xfails, tiers and configurations not run) / ANOMALIES (zero tests collected, slow tests, passed only on rerun).
5. Don't fix anything in this skill, and never edit a test to make it pass.
