---
name: test-review
description: Multi-agent review of the test changes on this branch - independent reviewers with different lenses in fresh contexts, verified findings, numbered proposals. Use before opening or merging a PR that adds or changes tests.
argument-hint: "[base branch, default {{BASE}}]"
---
Base branch: $ARGUMENTS (if empty, use {{BASE}}). Protocol: `docs/testing/REVIEW-PROTOCOL.md`.

1. Gather the evidence once: `git diff --stat <base>...HEAD`, `{{PY}} .claude/testing-kit/test_diff_guard.py --base <base>`, and the fast test run summary (`/run-tests`). Note the risk tier.
2. Launch three `test-reviewer` agents **in parallel**, each with one lens and the evidence above, and nothing of your own conclusions:
   - **Adversarial:** how could these tests pass while the behaviour is wrong? Look for gaming, special-casing, tautologies and loosened checks.
   - **Spec fidelity:** do expected values come from the spec? Is every requirement covered, failure paths included?
   - **Usability/quality:** naming, determinism, smells, mocks, maintainability.
   For high tier, add a fourth: **Mutation**, which runs `/mutation-check` and reviews the survivors.
3. Verify: for each Blocker/High finding, try to refute it yourself (read the code, run the test). Keep CONFIRMED and PLAUSIBLE ones and drop the rest, saying why.
4. Consolidate into one table `Id | Finding | From | Verdict | Proposed fix`. Number the proposals P1..Pn.
5. Apply only fixes that don't touch existing tests or harness (e.g. add a missing failure-path test). Anything that changes an existing test, removes a check or changes scope is a proposal for the user to approve.
6. Write the result to `reviews/<date>-<branch>.md` if the repo keeps reviews, or put it in the PR description. Post the summary: counts by severity, what you fixed, what needs the user.
