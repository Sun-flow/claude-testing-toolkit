# Testing Guidelines for Agent-Built Code

> **Version** 0.1 (draft for review) · **Date** 2026-11-12
> **Import into a repo** by copying this file to `docs/testing/GUIDELINES.md` and adding `@docs/testing/GUIDELINES.md` to the repo's `CLAUDE.md` (or `AGENTS.md`). The always-on short form for agents is `kit/templates/project/.claude/rules/testing.md`. This file is the long form with the reasons.
> **Evidence** for every rule is in `research/01..06` (cited as [R1]–[R6] with section) and the primary sources listed there.

These guidelines are for repositories where AI agents write a large share of the code and the tests. They apply to any language. Section 8 adds rules for code that calls LLMs or is itself an agent.

---

## 0. The six ideas behind every rule

1. **The oracle is the weak point.** When one agent writes both the code and the tests, both come from one reading of the requirements, so the tests pass by construction. Paul Grizzaffi calls this the *AI echo chamber* [R1 §2.1]. The evidence agrees: LLM-written assertions follow what the code does, not what it should do [R5 §2 F2]. 29.6% of SWE-bench patches that pass the tests still behave differently from the intended fix [R5 §1]. Even different model vendors share most of their wrong answers [R2 follow-up A].
2. **Agents game test suites when they can.** On ImpossibleBench, where any pass requires cheating, Claude Opus 4.1 passed 50% of tasks, and in more than 79% of those cases it did so by editing the test [R5 §1]. Hard-coding to tests rises to 22–44% when the spec is ambiguous [R5 §7].
3. **Instructions advise; hooks and CI enforce.** Claude Code's docs say CLAUDE.md and rules are context, not enforced configuration. Anything that must hold goes into a hook, a permission rule or a CI gate [R6 §1.2].
4. **Rigour scales with risk.** How independent and how deep the checking is should match the cost of failure and the cost of change [R1 §3.4; R2 G32].
5. **Testing reports risk.** Every test or eval report says what was tested, what was *not* tested, and what looked odd, not only pass/fail counts [R1 §2.3].
6. **Evidence beats claims.** "Tests pass" means nothing without the exact command, the number of tests collected, and the output [R4 U4; R5 rule 10].

---

## 1. Risk tiers

Declare a tier in the PR description (or the task file) for every change. If unsure, pick the higher one.

| Tier | Typical change | Required oracle independence | Required gates |
|---|---|---|---|
| **Low** | Internal tooling, prototypes, docs-adjacent code, easy to revert | Tests from the spec, written before the implementation in the same session | Unit tests green; integrity checks (§4) |
| **Medium** (default) | Product features, shared libraries | Tests written from the spec **in a separate context** (subagent or fresh session) from the implementer; fresh-context review | + diff coverage ≥ 90% on changed lines; diff-scoped mutation run with survivors explained |
| **High** | Money, auth, data loss, safety, public APIs, anything hard to roll back | At least one oracle the implementing agent did not derive: a human-written or approved acceptance test, a reference implementation, a schema, property/metamorphic relations reviewed by a human, or tests written by a different model family from the spec only | + mutation score gate on the diff; human review of tests; for LLM features, pass^k gating (§8) |

Sources: [R1 §3.1, §3.4], [R2 G30–G32], [R3 follow-up G24], [R5 rule 12, R16].

---

## 2. Before writing any test: test the requirements

- **TG-01. List the assumptions first.** Before writing tests, write the assumptions in the ticket or spec (inputs, data shape, environment, structure, error behaviour) in an `## Assumptions` section of the PR or task file. Check each one against real data or code. Mark any you could not check. [R1 §3.3, GIGO 2026]
- **TG-02. Stop on ambiguity.** If the spec allows two reasonable readings that lead to different expected values, ask the human. Don't pick one quietly. Hard-coding to tests jumps when specs are ambiguous [R5 §7 R17], and agents that ask questions do up to 74% better [R2 follow-up C].
- **TG-03. Each test maps to a requirement.** Don't add tests for features nobody asked for. Every test should trace to a requirement, a bug report, or a documented contract [R5 F12].

## 3. Writing tests

- **TG-04. Red before green.** For a bug fix or new behaviour, write the test first. Run it, show it failing *for the expected reason*, then change production code. A test that was never red proves nothing [R5 rule 1, F9].
- **TG-05. Expected values come from the spec, not from the code.** Derive them from the requirement, docs, a hand calculation or an independent reference. Never run the code under test and paste its output into the assertion. Add a short comment saying where each non-obvious value comes from [R1 §3.2; R5 rule 2].
- **TG-06. If you can't state the expected output without running the code, don't write an exact-value assertion.** Use a property, a metamorphic relation, a differential oracle, or a human-approved snapshot instead [R3 §2].
- **TG-07. Every test has an assertion that would fail if the behaviour broke.** `is not None`, a type check, `toHaveBeenCalled()` on its own, `assert True`, or no assertion at all doesn't count [R5 rule 5, F1].
- **TG-08. Assert on observable behaviour:** return values, persisted state, emitted events, HTTP responses. Don't assert on private members or internal call order unless the order is the contract [R5 rule 3, F4].
- **TG-09. Mock only at process boundaries:** network, clock, randomness, filesystem, third-party services. Never mock the unit under test or its in-process collaborators. Prefer fakes and in-memory implementations to mocks [R5 rule 4, F3].
- **TG-10. Test the failure paths.** Every changed public behaviour gets error and boundary cases (invalid input, empty, limits, permission denied, upstream failure), not just the happy path. Purely confirmatory suites hide risk [R1 §3.6; R5 §7].
- **TG-11. Name tests for behaviour and condition** (`rejects_expired_token`), keep one behaviour per test, and parametrize cases that share a shape instead of copy-pasting [R3 G19; R5 F10].
- **TG-12. Build test data with builders or factories** that default to a valid object. Override only the fields the test is about [R3 G20].
- **TG-13. A new test must actually run.** Show runner output that names the new tests and the count collected. A test file that collects zero tests is a failure [R5 F8].

## 4. Integrity: never game the suite

- **TG-14. Never modify, delete, skip, mark xfail, `.only`, or loosen an existing test to make a change pass.** If you believe a test is wrong, stop and report: the test, what it expects, what the code does, your evidence, and the change you propose. A human decides. This is the rule already in `claude-toolkit/.claude/rules/test-integrity.md`; this kit adds the hook that enforces it [R5 rule 7; R6 §2.3].
- **TG-15. Never edit harness files to get green.** That covers `conftest.py`, runner config (`pytest.ini`, `[tool.pytest]`, `jest/vitest.config.*`), coverage thresholds, CI workflows and `.claude/` settings, unless the task explicitly asks for it [R5 rule 9, F7].
- **TG-16. Never special-case tests in production code.** No branches on test inputs, no `PYTEST_CURRENT_TEST` / `NODE_ENV==='test'` checks, no overridden `__eq__`, no early `sys.exit(0)` [R5 rule 8, F6–F7].
- **TG-17. Never regenerate snapshots or golden files to make a failing test pass.** That covers `-u`, `--snapshot-update`, `cargo insta accept`, `UPDATE_GOLDEN=1`. Update only when the behaviour change is intended, and justify each changed hunk in the PR [R3 G11, G26].
- **TG-18. No retries, sleeps, longer timeouts or skips as a fix.** Fix the root cause or report it. Bounded reruns are allowed only on the CI command line, and a "passed on rerun" result is reported as *flaky*, never as clean [R4 U2, P13, P19].
- **TG-19. Bound your own loops.** After 3 failed attempts at the same failure, stop and report instead of trying more variations. Feedback loops raise cheating rates, and a sanctioned way to stop cut it sharply (GPT-5: 54% → 9%) [R5 §1, rule 15].

## 5. Choosing a technique

| Kind of code | First choice | Add | Oracle |
|---|---|---|---|
| Functions with an inverse (encode/decode, serialize/parse) | Property-based round-trip | Fuzz the decoder | `decode(encode(x)) == x` |
| Stateful APIs, data structures, CRUD | Stateful/model-based PBT (Hypothesis `RuleBasedStateMachine`, fast-check `commands`) | Named example scenarios | A trivially simple reference model |
| Rewrites and optimisations | Differential testing against the old version | Characterization tests | The old implementation |
| Parsers, anything reading untrusted bytes | Coverage-guided fuzzing (Atheris, `go test -fuzz`, cargo-fuzz, Jazzer), always time-bounded | PBT for semantics | No crash, sanitizers, invariants |
| Business rules with enumerable cases | Table-driven tests | PBT invariants (totals ≥ 0, monotonic) | Spec examples |
| ML/LLM features, ranking, search | Metamorphic relations (paraphrase, permutation, irrelevant context) | Structured-field snapshots | Relations between outputs |
| Rendered/CLI/codegen output | Small, redacted snapshots | Explicit assertion on what matters | Human-approved reference |
| HTTP APIs with a schema | Schemathesis (positive, negative, stateful) | Hand-written business tests | The schema |
| Legacy code before a refactor | Characterization/approval tests plus a sabotage check | Mutation run | Current behaviour |

From [R3 §2]. Supporting rules:

- **TG-20. Ground every property in evidence.** Cite the docstring, type, call site, spec or existing test it comes from. Most false positives from agent-written property tests were properties the code never promised [R3 G1].
- **TG-21. Don't narrow generators** (size caps, `assume()`, narrow ranges) beyond the documented domain without saying why. Never wrap a property body in a broad `try/except` [R3 G3–G4].
- **TG-22. Pin every counterexample** you find as an explicit example (`@example`, a committed corpus file) [R3 G6].
- **TG-23. Keep example tests alongside properties.** Each caught 69% of the edge-case bugs in one study, and together they caught 81% [R3 §1.5].
- **TG-24. Treat snapshots of new behaviour as change detectors, not correctness evidence.** Before accepting a new snapshot, quote its key lines and say why each is right according to the spec [R3 G25–G26].
- **TG-25. Prove characterization tests can fail:** break the code on purpose, confirm the test fails at the intended line, then revert (Seemann's sabotage step) [R3 G27].
- **TG-26. Bound every fuzz and random run** (`-fuzztime`, `-max_total_time`, a time budget) and log seeds [R3 G8; R4 P2].

## 6. Determinism and environment

- **TG-27. Tests are hermetic.** Unit tests run in one process with no network, no real clock, no shared state and no order dependence. Enforce this with tooling: random order with a printed seed (pytest-randomly, Vitest `sequence.shuffle`), network blocked by default (pytest-socket), an injected or frozen clock (time-machine, `vi.useFakeTimers`), per-test timeouts, `tmp_path`/`monkeypatch` isolation [R4 P2–P7].
- **TG-28. No hard waits.** Use polling, callbacks or auto-waiting assertions instead of `sleep`/`waitForTimeout` [R4 P22].
- **TG-29. Lockfiles are enforced, not just committed** (`uv sync --locked`, `npm ci`, `pnpm install --frozen-lockfile`). Pin the runtime version [R4 P9].
- **TG-30. Real dependencies run in containers** (Testcontainers or localhost services), never shared staging or production [R4 P10].
- **TG-31. One documented command per tier.** `make test` (or `npm test`) equals the PR gate and finishes in under 2 minutes in a cloud agent box; slower tiers have their own commands and tags. List them in `CLAUDE.md` [R4 P1, P20, E5].
- **TG-32. Flaky tests are quarantined with an owner and an expiry date**, keep running and keep reporting. A scheduled job re-runs tests many times to find intermittent product bugs instead of retrying them away [R4 P12, P18].

## 7. Quality gates

- **TG-33. Coverage is a floor, not a target.** Turn on branch coverage, keep a modest global floor (e.g. 80%) and a stricter **diff-coverage** gate on changed lines (`diff-cover --fail-under=90`). Never lower a threshold or add `no cover` pragmas to get green [R4 P11, U5].
- **TG-34. Mutation score on the diff is the real quality signal** (mutmut, Stryker, PIT, cargo-mutants, all scoped to changed files). A study found 100% coverage alongside a 4% mutation score [R5 rule 13, §1]. For medium tier, attach the run and explain the surviving mutants. For high tier, gate on the score.
- **TG-35. Check the share of failure-path tests** in changed test files (tests using `raises`/`toThrow`/error-status expectations, or names like `invalid|reject|error`). Zero for a public function with documented errors is a finding [R5 §7].
- **TG-36. Keep a backstop the agent never sees for high tier:** CI-only property tests, a mutation run, or human-held acceptance tests [R5 rule 14].

## 8. Code that calls LLMs, and agents

Two disciplines. **Tests** check the code around the model and are deterministic. **Evals** measure output quality and are statistical. Don't mix them [R2 §1.1].

| Layer | What | Model calls | Runs |
|---|---|---|---|
| L0 Contract | Schemas for structured output and tool definitions, prompt templates render, tool-argument validation | none | every commit |
| L1 Unit (fake model) | Tool functions, parsing and repair, retries, error paths, using a scriptable fake (`FunctionModel`-style) that returns tool calls, malformed JSON, refusals, 429/5xx | blocked | every commit |
| L2 Replay | Recorded cassettes (vcrpy/pytest-recording, `--record-mode=none` in CI), streaming, tool round-trips | recorded only | every commit |
| L3 Live smoke | A handful of cheap real calls: auth, model-ID drift, API contract | few | trusted branches / nightly |
| L4 Evals | Golden set + graders, k trials, pass rate ± stderr, pass^k for agents, sandboxed | many | merge / nightly / before a prompt or model change |
| L5 Adversarial | Red-team and prompt-injection suites | many | scheduled + before release |

From [R2 §2]. Rules:

- **TG-37. Block real model calls in unit tests by default** (`ALLOW_MODEL_REQUESTS=False`, network blocking, cassettes in `none` mode) so a missing fake fails loudly. Inject the model client; don't monkeypatch SDK internals [R2 G1–G3].
- **TG-38. Scrub secrets from cassettes** (`authorization`, `x-api-key`, org IDs) before committing [R2 G4].
- **TG-39. Evals live outside the default test run** (`-m eval` or their own directory and CI job, with a budget) [R2 G6, G28].
- **TG-40. Graders: code first, LLM judge only where code can't decide, humans to calibrate the judge.** A judge comes from a different model family than the generator, reasons before scoring, has an "Unknown" option, and handles one criterion each. For pairwise judging, swap the order and keep only consistent verdicts [R2 G10–G12, G31].
- **TG-41. Above low tier, at least one non-LLM oracle** (code check, end-state check, property, human-written acceptance test) [R2 G30].
- **TG-42. Grade agents on the final state** (database rows, files, side effects). Use trajectory assertions only for hard constraints such as forbidden tools or a confirmation required before writes [R2 G20].
- **TG-43. Run k trials and report pass rate ± standard error;** for user-facing agents report pass^k. Compare versions with paired per-question differences, not two summary numbers. Record model snapshot ID, temperature, prompt hash and seed with every result [R2 G15–G18].
- **TG-44. Model quality checks as a rate with a threshold, never "flaky, retry until green".** Allow pass / fail / inconclusive, and send inconclusive results to human triage [R2 G19, G34].
- **TG-45. Every agent trial gets a fresh sandbox** (a container per sample, network off by default) [R2 G21].
- **TG-46. Include prompt-injection cases** (attacker text in tool outputs, retrieved docs, web pages) and underspecified variants of key tasks that check whether the agent asks before acting [R2 G23, G33].
- **TG-47. Start evals from 20–50 real failures** and turn every production incident into a regression case. Label suites *capability* (tracked) or *regression* (gated near 100%) [R2 G7, G13].
- **TG-48. Never expose model API keys to untrusted PR code.** Use low-limit, rotatable CI keys and cache responses keyed on prompt and config [R2 G25–G27].

## 9. Reporting

- **TG-49. Every test or eval run summary has four parts:** what ran (command, counts, seed), what failed (grouped by root cause, not 300 red lines), **what was not tested** (skipped, xfail, deselected tiers, configurations not covered), and anomalies seen [R1 §3.5; R4 P21; R2 G35].
- **TG-50. Keep "assist" output apart from tests.** Crawlers, diffs and data generators that need human triage go in their own directory or marker (`@pytest.mark.assist`). They never gate merges and are never counted as passing tests. Anything counted as a test needs a falsifiable oracle [R1 §3.10; R5 §7].

## 10. Review checklist (fresh context, cite file:line for each finding)

**A. Suite integrity (any finding blocks):** no test deleted, skipped, xfailed, `.only`'d or commented out; no assertion removed or loosened; collected-test count ≥ base branch; no harness/config/CI/`.claude/` changes; no snapshot regenerated without per-hunk justification.
**B. Production honesty (any finding blocks):** no test-environment checks or test literals in production code; no overridden equality or early exits; the fix is general.
**C. Each new or changed test (request changes):** behaviour-named; meaningful assertion; expected values justified by the spec; red-before-green evidence for fixes; mocks only at boundaries; no private-member asserts; deterministic; failure paths covered; actually collected; no smells.
**D. Quality signal (note):** diff-coverage and diff mutation results attached, with survivors killed or explained; risk tier declared and its oracle requirement met; "not tested" section present.

From [R5 §4], extended with [R3 F4] and [R1 §3.5].
