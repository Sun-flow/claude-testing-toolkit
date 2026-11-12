# Testing habits (personal, every repo)

A repo's own `.claude/rules/testing.md` wins over these.

- Find the repo's test command (CLAUDE.md, README, package.json, pyproject). If there is none, ask or propose one before writing tests.
- Run the narrowest relevant test first, then the fast suite before saying you're done.
- Red before green for fixes and new behaviour; expected values from the spec, never copied from the code's output.
- Never weaken a test, skip it, add retries/sleeps, or lower a coverage threshold to get green. If a test looks wrong, stop and ask, with evidence.
- Evidence, not claims: the command, the count collected, the summary line, and what you didn't run.
- If stuck after a few honest attempts, stop and report with `BLOCKED:`.
