<!-- testing-kit:start (managed by the testing kit installer; edit the commands, keep the markers) -->
## Testing

- Fast tier (the PR gate, run before saying you're done): `{{FAST}}`
- Full tier: `{{FULL}}`
- Run one test: {{ONE}}
- Rules: `.claude/rules/testing.md` (always loaded). Long form with reasons: `docs/testing/GUIDELINES.md`. Review protocol: `docs/testing/REVIEW-PROTOCOL.md`.
- Default risk tier for this repo: **{{TIER}}** (guidelines §1).
- Skills: `/write-tests`, `/run-tests`, `/mutation-check`, `/test-review`. Agents: `spec-test-writer`, `test-reviewer`.
- Hooks in `.claude/testing-kit/` ask before existing tests, snapshots or test config change, and stop you finishing while the fast tier fails. If you're stuck, stop with a `BLOCKED:` report.
<!-- testing-kit:end -->
