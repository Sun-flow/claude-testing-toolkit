---
name: write-tests
description: Write tests for a change the testing-kit way - assumptions first, tests from the spec, red before green, then implement and show green with a run report. Use when adding behaviour or fixing a bug.
argument-hint: "[ticket, spec path or description]"
---
Follow these steps for: $ARGUMENTS

1. **Tier.** Decide the risk tier (low / medium / high; see `docs/testing/GUIDELINES.md` §1, default in `.claude/testing-kit.json`). Say which and why in one line.
2. **Assumptions.** Write an `## Assumptions` list: each claim, its source, how you checked it. If two reasonable readings of the spec lead to different expected values, ask the user now.
3. **Tests from the spec.**
   - Low tier: write the tests yourself, before touching the implementation.
   - Medium/high tier: delegate to the `spec-test-writer` agent. Pass it only the ticket/spec paths and the public interface, not your plan for the code.
   - Pick the technique from guidelines §5 (property, table-driven, differential, snapshot...). Cover failure and boundary paths.
4. **Red.** Run the new tests with the fast command; show them failing for the expected reason. A test that passes before the change proves nothing: fix the test's premise, not by weakening it.
5. **Implement** the general fix. Never special-case test inputs.
6. **Green.** Run the narrowest tests, then the fast suite. Show the command, count collected and result; `python .claude/testing-kit/test_report.py` gives the four-part summary.
7. **High tier:** add the independent oracle (human-approved acceptance test, reference implementation, schema check, or reviewed properties) and run `/mutation-check`.
8. **Report** what you did not run and anything odd. If you got stuck, stop with `BLOCKED:` and the evidence.
