# Multi-Agent Review Protocol

> **Version** 0.1 · **Date** 2026-11-12
> Used to review this kit's documents and tooling, and packaged as the `/test-review` skill for reviewing test suites in any repo.

## Where this comes from

This project's memory was empty, so the pattern is taken from earlier repositories:

| Source | What it contributed |
|---|---|
| `an earlier project's EDGE-CASE-FINDINGS.md` | An adversarial review whose expected results come from **the brief's intent, not the code**; a findings table `Id · Area · Cases · What broke · Severity · Settled`; fixes offered as **numbered proposals (P1–P12) that the maintainer approves**, then recorded in `docs/decisions.md` (Decision / Rationale / Alternatives / Status). |
| `a memory bank` (log + decisions) | Each review is **its own dated file** (merge-proof: one file per entry, never a shared list). A review is "adopted with fixes", and open gaps become **numbered open questions**. |
| `claude-toolkit` (`/research` skill, `test-integrity` rule) | Reviewers write **proposals and never auto-apply** them; tests are never changed to match code without asking. |

Research adds three refinements: reviewers work in a **fresh context** and are not the author [R5 rule 12]; an LLM reviewer reading the diff was the most effective detector of test gaming [R5 §1]; and reviewers that chase every gap cause over-engineering, so findings carry a severity and a confidence [R5 F12].

## Roles

| Role | Sees | Doesn't see | Job |
|---|---|---|---|
| **Author** | Everything | — | Produced the work. Never reviews it. |
| **Reviewers** (3–5, in parallel) | The artifact, the spec/brief, the sources | The author's reasoning, other reviewers' findings | One lens each (below). Report findings in the table format. |
| **Verifier** | Each finding + the artifact | — | Tries to *refute* each finding. Keeps CONFIRMED and PLAUSIBLE ones, drops the rest. |
| **Consolidator** (the author's session) | Verified findings | — | Merges duplicates, writes numbered proposals, applies the ones within its mandate, asks the human for the rest. |

## Standard lenses

Pick the 3–5 that fit the artifact.

1. **Evidence:** is every claim backed by its cited source, with nothing overstated?
2. **Adversarial / gaming:** how would an agent satisfy the letter of this and defeat its purpose? Where are the loopholes?
3. **Mechanics:** do commands, config keys, hook payloads and paths actually work as written? (Run them where possible.)
4. **Usability and fit:** is it clear, consistent, not contradictory, sized right for an agent's context, and does it fit the repos it will be installed into?
5. **Spec fidelity** (for test suites): do expected values come from the spec? Is every requirement covered, including failure paths?

## Findings format

Each reviewer writes `reviews/<round>-<lens>.md`:

```markdown
# <Round> · <Lens> review of <artifact>  (reviewer: fresh context, <date>)

| Id | Where (file § / line) | What's wrong | Evidence | Severity | Confidence | Proposed fix |
|---|---|---|---|---|---|---|
| EV-1 | TESTING-GUIDELINES.md §3 TG-07 | ... | quote / command output / source | High | High | ... |

## Open questions
- Q1 ...
```

- **Severity:** *Blocker* (wrong or harmful if shipped), *High* (materially weakens the kit), *Medium*, *Low* (polish).
- **Confidence:** High / Medium / Low.
- Ids are prefixed by lens (EV, ADV, MECH, USE, SPEC) so findings from different files never collide.

## Consolidation

The consolidator writes `reviews/<round>-SUMMARY.md`:

| Id | Finding (merged) | From | Verdict | Settled |
|---|---|---|---|---|
| P1 | ... | EV-2, ADV-4 | Applied / Proposed to the maintainer / Rejected (why) | commit or section changed |

Rules:
- Blockers and Highs are fixed before anything ships, or listed for the maintainer as open questions.
- Anything that changes the kit's goals, removes a rule, or loosens an integrity check is a **proposal for the maintainer**, never applied silently.
- Rejected findings stay in the table with the reason. Nothing is deleted.
- Each round is its own file; rounds are never merged into one shared list.

## Running it with Claude Code

- **In this project:** the coordinator spawns one subagent per lens with the artifact paths, the lens description and the findings format, and **no summary of the author's conclusions**.
- **In a repo with the kit installed:** `/test-review [base-branch]` spawns the `test-reviewer` agent once per lens over the diff (lenses 2, 4 and 5 for test changes), then consolidates into `reviews/` or the PR description. In CI: `anthropics/claude-code-action` with `prompt: "/test-review"`.
