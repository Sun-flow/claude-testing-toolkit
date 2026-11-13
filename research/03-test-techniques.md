# 03 — Test techniques with strong oracles (and how well agents use them)

Research date: 2026-11-12. Scope: property-based testing (PBT), fuzzing, snapshot/approval/golden tests, contract testing, metamorphic testing, table-driven tests, test data builders, characterization tests, and evidence on LLM-written properties.
Citation key: [n] refers to section 6. Sources marked (F) were fetched and read for this report. Sources marked (S) were found by search, and the claims made about them are standard, well-known content. The shared web-fetch budget ran out partway through, so some secondary pages could not be re-read.

---

## 1) Key findings

1. **The main weakness of agent-written tests is the oracle.** When the same model writes the code and the example-based tests, the tests inherit the same misreading of the spec. PGS calls this a "cycle of self-deception": a `factorize(12)` test expecting `[2, 3]` passes buggy code [5](F). Properties such as "the product of the factors equals the input" don't need the agent to predict exact outputs. PGS reports 23–37% relative pass@1 gains over TDD-style baselines. On a hard LiveCodeBench subset, property feedback raised repair success from 46.6% to 75.9% compared with public tests alone [5](F).
2. **Agents can find real bugs with PBT when properties are grounded in evidence.** Anthropic's agent (Claude Code, Opus 4.1, Hypothesis) ran on 100 PyPI packages and produced 984 reports. On manual review, 56% were valid and 32% were worth reporting. After ranking with a 15-point rubric, the top reports were 86% valid. Merged fixes landed in NumPy, aws-lambda-powertools and tokenizers [1](F)[2](F). The bugs came from round-trip, distinctness ("different inputs hash differently"), output-format (regex) and domain-invariant properties [2](F).
3. **The most common failure is a wrong guess about intent.** False positives came from properties the code never claimed, or from inputs that callers never pass, such as NaN or a Gregorian-only assumption in `dateutil.easter`. Mitigations: derive each property from docstrings, types, call sites or existing tests; reflect on every failure; and prefer properties that are "sound but incomplete" [1][3](F).
4. **Agents also write weak properties.** Examples include over-restricted strategies (capped list sizes), tests that pass only because of a `try/except`, and trivially true assertions [2][3](F). An early study found that only 41% of LLM-written property tests ran and passed, and at most 21% of documented properties were covered [1](F). Agentic loops that run and reflect do much better than one-shot generation.
5. **PBT and example tests complement each other.** In a small study (16 HumanEval+ edge-case bugs, Claude Sonnet 4), PBT and EBT each caught 68.75%, and the two together caught 81.25%. PBT was better at wide input ranges and performance cliffs. EBT was better at specific boundary values. PBT runs took about 2.4× longer [4](F).
6. **LLM-generated fuzz harnesses work when they get compile, run and triage feedback.** OSS-Fuzz-gen added 370k+ lines of coverage across 272 C/C++ projects and found 26 new vulnerabilities, including OpenSSL CVE-2024-9143. The main lesson: give the model indexed project context (types, call sites, unit tests) and have it triage crashes as either harness bugs or project bugs [6](F).
7. **Snapshot and golden tests are cheap oracles but easy to rubber-stamp.** Kent C. Dodds, the Jest docs and the insta and syrupy tools all name the same risk: reflexive regeneration of large, unreviewed snapshots [8][9](F). For an agent, `-u`, `--snapshot-update`, `cargo insta accept` and `INSTA_UPDATE` all mean "make the test pass by rewriting the oracle." Tooling helps. Jest won't write new snapshots in CI. Syrupy fails on missing or unused snapshots by default. Insta keeps pending `.snap.new` files for review and can reject unreferenced snapshots in CI [9][10][11](F).
8. **Contract and schema tools give specification-derived oracles.** Schemathesis generates property-based tests from OpenAPI (2.0–3.2), GraphQL and gRPC schemas. Default checks include no 5xx responses, status, content-type, header and response-schema conformance, rejection of invalid inputs, auth bypass, and stateful use-after-free [12][13](F). Pact suits services you control on both sides, in-house microservices with few consumers. It does not suit public APIs, pass-through BFFs or providers you don't control [14][15](F).
9. **Go native fuzzing gives agents a cheap regression mechanism.** Minimized failing inputs are written to `testdata/fuzz/FuzzX/`, and plain `go test` replays them from then on. Fuzzing never ends unless `-fuzztime` is set, which matters for agents [7](F).
10. **The tooling is current.** Hypothesis ships an official `/hypothesis` Claude Code command (Nov 2025) [3](F) and HypoFuzz [16](F). Atheris 3.1.0 (June 2026) supports Python 3.11–3.14 [17](F). Jazzer is open source again under Apache-2.0 [18](F).

---

## 2) Decision guide: which technique for which kind of code

| Kind of code | First choice | Add | Oracle source |
|---|---|---|---|
| Pure functions with an inverse (encode/decode, serialize/parse, compress) | PBT round-trip | Fuzz the decoder | `decode(encode(x)) == x` |
| Data structures / stateful APIs (caches, queues, repos, CRUD) | Stateful/model-based PBT (Hypothesis `RuleBasedStateMachine`, fast-check `commands`, `proptest-state-machine`) | Example tests for named scenarios | Simple reference model (dict/list) |
| Optimized rewrite / alternative implementation | Differential PBT against the reference or old version | Characterization tests | Old implementation |
| Parsers, decoders, anything reading untrusted bytes | Coverage-guided fuzzing (Atheris, cargo-fuzz, `go test -fuzz`, Jazzer) | PBT for semantics | No crash/panic/hang, plus sanitizers and asserted invariants |
| Business rules with enumerable cases (pricing tiers, validation) | Table-driven / parametrized tests | PBT for invariants (e.g. total ≥ 0, monotonic in quantity) | Spec examples |
| Numeric / scientific code | PBT invariants plus metamorphic relations (scaling, permutation, symmetry) | Tolerance-aware oracles | Math identities |
| ML models, LLM features, search/ranking (no exact oracle) | Metamorphic testing (paraphrase, irrelevant-context, permutation invariance) | Snapshot of *structured* features, not raw text | Relations between outputs |
| Rendered output, CLI output, compiler/IR, codegen | Snapshot/golden (insta, syrupy, Jest inline) with small, redacted snapshots | Property checks on structure | Human-approved reference |
| HTTP APIs you publish with a schema | Schemathesis (positive, negative, stateful) | Hand-written tests for business semantics | Schema |
| Internal service-to-service integrations you own on both sides | Pact (consumer-driven) | Schemathesis on provider | Consumer expectations |
| Legacy code before refactor | Characterization/approval tests (ApprovalTests, combination approvals) | Mutation checks to prove they bite | Current behaviour |
| Complex object setup in any test | Test data builders / factories (one valid default, override what matters) | Hypothesis `builds()`, fast-check `record` | — |

Quick rule: if the agent cannot state the expected output *without running the code*, it should not write an exact-value assertion. It should use a property, a metamorphic relation, a differential oracle, or a human-approved snapshot.

---

## 3) Guideline candidates (imperative, with rationale)

**PBT**
- **G1. Ground every property in evidence.** Before writing a property, cite where it comes from (docstring, type, call site, existing test, or spec) in a comment. *Why:* most agent false positives were properties the code never promised [1][2][3].
- **G2. Prefer the strongest cheap property families, in this order:** round-trip/inverse, differential (vs. reference or old version), model-based/stateful, invariants (sizes, ordering, conservation, ranges, format regex), metamorphic, then "does not crash". *Why:* these families found the validated bugs [2]. "Does not crash" alone is weak but is still worth having as a floor [1]. See Wlaschin's property catalogue [19](S).
- **G3. Don't narrow strategies beyond the documented input domain.** Don't add `max_size` caps, `assume()` filters or narrow ranges unless the domain requires them, and give the justification when you do. *Why:* the Hypothesis team found agents over-restrict generators even when told not to [3].
- **G4. Never catch broad exceptions inside a property body.** Assert on the specific exception the contract documents. *Why:* a try/except-wrapped test passed vacuously and hid a real bug [2].
- **G5. Triage before reporting.** When a property fails, decide whether the input is realistic, whether the code claims the property, and whether the result reproduces. Fix the test if the property was wrong, and file or fix the code otherwise. *Why:* this reflection step is what lifted precision in [1][2].
- **G6. Pin found counterexamples as explicit examples.** Use `@example(...)` in Hypothesis, `examples` in fast-check, or committed corpus files in Go and proptest, so the regression runs deterministically. *Why:* reproducible CI. Go does this automatically [7].
- **G7. Keep example tests next to properties for named boundaries.** *Why:* EBT caught specific boundary bugs that PBT missed. Combining them gave the best detection [4].

**Fuzzing**
- **G8. Fuzz anything that parses untrusted input. Commit seed corpora and always bound runs** (`-fuzztime`, `-max_total_time`, `-runs`) in agent and CI contexts. *Why:* fuzzing runs forever by default [7].
- **G9. Make fuzz targets deterministic and stateless, and assert semantic invariants.** Don't settle for crash-only checks where a cheap invariant exists. *Why:* the Go docs require this for parallel, non-deterministic scheduling. Invariants turn fuzzing into an oracle [7][6].
- **G10. Triage crashes as harness bug vs. code bug before you change product code.** *Why:* LLM harnesses produce their own crashes [6].

**Snapshots / golden files**
- **G11. Never run snapshot-update commands to make a failing test pass unless the behaviour change was intended.** This covers `-u`, `--snapshot-update`, `cargo insta accept`, `INSTA_UPDATE=always`, `UPDATE_GOLDEN=1` and similar. When you do update, explain why each diff hunk is intended in the commit or PR. *Why:* rubber-stamping turns the oracle into "whatever the code does now" [8][9].
- **G12. Keep snapshots small, deterministic and redacted.** Use inline snapshots for short outputs. Redact or match timestamps, IDs and paths (Jest property matchers, syrupy matchers/`exclude`, insta redactions). Lint large snapshots (`jest/no-large-snapshots`). *Why:* nobody reviews big snapshots, and noise trains people to accept changes [8][9][10].
- **G13. Run snapshot tests in CI with writes disabled and unused snapshots failing.** Use Jest `--ci`, syrupy defaults, and insta `--unreferenced=reject` or `auto`. *Why:* stops new or orphaned snapshots from silently passing [9][10][11].
- **G14. Pair each snapshot with at least one explicit assertion** on the property that matters. *Why:* snapshots record behaviour without stating intent [8].

**Contracts / APIs**
- **G15. Run Schemathesis against every API with an OpenAPI or GraphQL schema** in CI. Include negative and stateful phases. *Why:* the schema is a ready-made oracle, and it finds 5xx, schema drift, auth gaps and validation gaps [12][13].
- **G16. Use Pact only where both sides are under your control and consumers are few.** Use provider-side schema testing for public APIs. *Why:* Pact's own guidance [15].

**Legacy, ML, structure**
- **G17. Before an agent refactors untested code, pin the current behaviour with characterization or approval tests.** Then show the tests fail when the code is deliberately broken, using mutation or "break it on purpose". *Why:* characterization tests are only useful if they can fail. Seemann's "empirical characterization testing" makes this point [20](S) (Feathers, *WELC*).
- **G18. For ML and LLM components, test with metamorphic relations, not exact outputs.** Examples: label invariance under paraphrase, monotonicity under feature increase, order invariance. Assert on structured fields. *Why:* no exact oracle exists. MT is the standard approach in the 2025–26 surveys [21][22](S).
- **G19. Use table-driven or parametrized tests when cases share one shape, and name every case.** *Why:* failures stay readable and adding a case is cheap [23](S).
- **G20. Build test objects through builders or factories that default to a valid object, and override only the fields relevant to the test.** *Why:* the setup shows what matters, and schema changes touch one place [24](S).

---

## 4) Tools table

| Tool | Language | Install | Link |
|---|---|---|---|
| Hypothesis (+ `/hypothesis` Claude Code command) | Python | `pip install hypothesis`; copy `.claude/commands/hypothesis.md` to `~/.claude/commands/` | https://hypothesis.readthedocs.io · https://github.com/HypothesisWorks/hypothesis/blob/master/.claude/commands/hypothesis.md |
| HypoFuzz | Python | `pip install hypofuzz` | https://hypofuzz.com |
| fast-check | JS/TS | `npm i -D fast-check` (`@fast-check/vitest`, `@fast-check/jest`) | https://fast-check.dev |
| proptest / proptest-state-machine | Rust | `cargo add --dev proptest proptest-state-machine` | https://docs.rs/proptest · https://docs.rs/proptest-state-machine |
| QuickCheck / Hedgehog | Haskell (idiom origin) | `cabal install QuickCheck` | https://hackage.haskell.org/package/QuickCheck |
| jqwik | Java | Maven/Gradle `net.jqwik:jqwik` | https://jqwik.net |
| Go `testing` fuzz | Go ≥1.18 | built-in; `go test -fuzz=FuzzX -fuzztime=30s` | https://go.dev/doc/security/fuzz/ |
| Atheris 3.1 | Python 3.11–3.14 (Linux/macOS) | `pip install atheris` | https://github.com/google/atheris |
| cargo-fuzz | Rust (libFuzzer, nightly) | `cargo install cargo-fuzz` | https://github.com/rust-fuzz/cargo-fuzz |
| Jazzer / Jazzer.js | JVM / Node | Maven `com.code-intelligence:jazzer-junit`; `npm i -D @jazzer.js/core` | https://github.com/CodeIntelligenceTesting/jazzer |
| OSS-Fuzz-gen | C/C++ (LLM harness gen) | clone | https://github.com/google/oss-fuzz-gen |
| syrupy | Python/pytest | `pip install syrupy` | https://syrupy-project.github.io/syrupy/ |
| Jest / Vitest snapshots | JS/TS | built-in | https://jestjs.io/docs/snapshot-testing |
| insta + cargo-insta | Rust | `cargo add --dev insta`; `cargo install cargo-insta` | https://insta.rs |
| ApprovalTests | Java, .NET, Python, JS, C++, … | e.g. `pip install approvaltests` | https://approvaltests.com · https://github.com/approvals |
| Schemathesis | any HTTP API (Python CLI) | `pip install schemathesis` / `uvx schemathesis`; `st run <schema-url>` | https://schemathesis.readthedocs.io |
| Pact | many | e.g. `npm i -D @pact-foundation/pact`, `pip install pact-python` | https://docs.pact.io |
| factory_boy / Fishery / make-it-easy | Python / TS / Java | `pip install factory_boy` etc. | https://github.com/npryce/make-it-easy |

---

## 5) Agent-specific pitfalls and mitigations

| Pitfall | What it looks like | Mitigation (kit mechanism) |
|---|---|---|
| **Rubber-stamp snapshot updates** | Agent hits a failing snapshot and runs `-u` / `cargo insta accept` / `--snapshot-update`, and the test passes | **PreToolUse hook** that blocks or asks about these commands unless the task says the behaviour change is intended. A **Stop/commit check** that flags any `.snap`, `.ambr` or `__snapshots__` diff without a rationale line. CI in `--ci` / `--unreferenced=reject` mode (G11, G13) |
| **Tautological oracle** | Expected values computed with the code under test, or copied from its output | Rule: expected values must come from spec or examples, or the test must be a property. Review skill asks "could this assertion fail if the code were wrong?" Mutation testing spot-checks |
| **Weak properties** | `assert result is not None`, `isinstance` checks, "doesn't raise" only, properties that restate the implementation | Property-family checklist (G2). Require at least one non-trivial relation per function. Mutation testing (mutmut, Stryker, cargo-mutants) to show the property kills mutants |
| **Over-constrained generators** | `max_size=5`, `min_value=1`, heavy `assume()`, so the bug space is never reached | Lint or review step that flags strategy bounds without a justification comment (G3). Hypothesis health checks for filtering |
| **Vacuous passes** | `try/except` around the body, early `return`, skipped tests, or properties that never execute (zero examples) | Hook greps new tests for broad `except`/`catch` inside property bodies. Check Hypothesis statistics (`--hypothesis-show-statistics`) |
| **Intent false positives** | Agent "fixes" code to satisfy a property the code never promised (NaN handling, calendar semantics) | G1 evidence comment plus G5 triage. Never change product semantics to satisfy a new property without human confirmation |
| **Weakening the test to go green** | Deleting the property, loosening tolerance, adding `@example` skips, `xfail` | Stop hook diffs tests: flag removed assertions, new skips/xfails, widened tolerances |
| **Unbounded fuzz / PBT runs** | `go test -fuzz` with no `-fuzztime`, huge `max_examples` | Rule G8. Use CI profiles (Hypothesis `settings.register_profile("ci", ...)`) |
| **Flaky snapshots** | Timestamps, UUIDs, absolute paths, dict order | Redactions/matchers (G12). Seed and freeze clocks |
| **Mocks instead of contracts** | Agent mocks the HTTP provider with invented response shapes | Generate mocks from the OpenAPI schema or Pact. Run Schemathesis on the provider |
| **Characterization tests that can't fail** | Approved output captured once and never shown to detect a change | G17: break the code on purpose or run mutation testing before relying on the tests |

Also worth knowing: the official `/hypothesis` command is a ready-made skill pattern (explore → read call sites → write grounded tests → run → triage) that the kit can adopt or wrap for other languages [3].

---

## 6) Sources

1. Maaz, DeVoe, Hatfield-Dodds, Carlini. *Agentic Property-Based Testing: Finding Bugs Across the Python Ecosystem*, arXiv:2510.09907 (Oct 2025; NeurIPS 2025 DL4Code workshop). https://arxiv.org/html/2510.09907v1 (F)
2. Anthropic Frontier Red Team, *Finding bugs with Claude and property-based testing*, 14 Jan 2026. https://www.anthropic.com/research/property-based-testing (F) (also red.anthropic.com/2026/property-based-testing)
3. DeVoe et al., *A Claude Code command for Hypothesis*, hypothesis.works, 1 Nov 2025. https://hypothesis.works/articles/claude-code-plugin/ (F)
4. Tanaka et al., *Understanding the Characteristics of LLM-Generated Property-Based Tests in Exploring Edge Cases*, arXiv:2510.25297 (Oct 2025). https://arxiv.org/pdf/2510.25297 (F)
5. *Use Property-Based Testing to Bridge LLM Code Generation and Validation* (Property-Generated Solver), arXiv:2506.18315 (Jun 2025). https://arxiv.org/html/2506.18315v1 (F)
6. Google Security Blog, *Leveling Up Fuzzing: Finding more vulnerabilities with AI*, Nov 2024. https://security.googleblog.com/2024/11/leveling-up-fuzzing-finding-more.html (F); https://github.com/google/oss-fuzz-gen
7. Go docs, *Go Fuzzing*. https://go.dev/doc/security/fuzz/ (F)
8. Kent C. Dodds, *Effective Snapshot Testing*. https://kentcdodds.com/blog/effective-snapshot-testing (F)
9. Jest docs, *Snapshot Testing*. https://jestjs.io/docs/snapshot-testing (F)
10. syrupy docs. https://syrupy-project.github.io/syrupy/ (F)
11. insta docs, *cargo-insta CLI*. https://insta.rs/docs/cli/ (F)
12. Schemathesis docs. https://schemathesis.readthedocs.io/en/stable/ (F)
13. Schemathesis checks reference. https://schemathesis.readthedocs.io/en/stable/reference/checks/ (F)
14. Pact docs. https://docs.pact.io/ (F)
15. Pact, *What is Pact good for?* https://docs.pact.io/getting_started/what_is_pact_good_for (F)
16. hypothesis.works articles index (HypoFuzz Nov 2025; Hypothesis Corpus Apr 2026). https://hypothesis.works/articles (F)
17. Atheris on PyPI (3.1.0, 17 Jun 2026). https://pypi.org/project/atheris/ (F)
18. Code Intelligence, *Jazzer back to open source*. https://www.code-intelligence.com/blog/jazzer-back-to-open-source (F)
19. Scott Wlaschin, *Choosing properties for property-based testing*. https://fsharpforfunandprofit.com/posts/property-based-testing-2/ (S)
20. Mark Seemann, *Empirical characterization testing*, 3 Nov 2025. https://blog.ploeh.dk/2025/11/03/empirical-characterization-testing/ (S); see also *Critiquing tests*, Feb 2026, https://blog.ploeh.dk/2026/02/16/critiquing-tests/ (S)
21. *Metamorphic Testing of Large Language Models*, arXiv:2511.02108 (Nov 2025). https://www.alphaxiv.org/abs/2511.02108 (S)
22. *Bidirectional Empowerment of Metamorphic Testing and Large Language Models: A Systematic Survey*, arXiv:2605.13898 (May 2026). https://arxiv.org/abs/2605.13898 (S)
23. Go Wiki, *TableDrivenTests*. https://go.dev/wiki/TableDrivenTests (S)
24. Nat Pryce, make-it-easy / Test Data Builders. https://github.com/npryce/make-it-easy ; Seemann, *Test Data Builders in C#*. https://blog.ploeh.dk/2017/08/15/test-data-builders-in-c/ (S)
25. Vikram, Lemieux, Padhye, *Can Large Language Models Write Good Property-Based Tests?*, arXiv:2307.04346 (2023). https://arxiv.org/abs/2307.04346 (S; figures cited via [1])
26. Stateful/model-based PBT docs: Hypothesis https://hypothesis.readthedocs.io/en/latest/stateful.html ; fast-check https://fast-check.dev/docs/advanced/model-based-testing/ ; proptest-state-machine https://docs.rs/proptest-state-machine (S)
27. Stack Overflow Blog, *The regression tests nobody writes: capturing how software actually behaves*, 22 Oct 2026. https://stackoverflow.blog/2026/10/22/the-regression-tests-nobody-writes-capturing-how-software-actually-behaves/ (S, not read)

---

## Follow-up on leads (from 01-responsible-automation-blog.md §5(b))

Context: Grizzaffi's "AI Echo Chamber" thesis (2026-03-31) says that when one AI writes both the app and its checks, both come from one reading of the requirements, which leads to shared blind spots and circular validation. His fix is independent test interfaces or a different checker, scaled to the cost of failure. This matches the "cycle of self-deception" in [5] and the intent-ambiguity failures in [1][2]. The follow-up asks which techniques give an oracle that does *not* come from the agent's own interpretation.

Verification status: WebFetch's shared budget was exhausted again and curl to every external host returned a proxy 403. I re-verified one (S) source in full (Seemann, below). The others are still (S): found by search, and described here by their standard, well-known content.

### F1. Randomised/monkey testing vs stateful PBT vs model-based testing
- **Monkey testing** (Grizzaffi's "Random Clicker"; Gremlins.js [F-a](S); shinytest2's monkey-testing vignette [F-b](S)) fires random UI events. Its oracle is weak and generic: no crash, no console error, no 5xx, no layout anomaly. Often a human triages the results. It is cheap, finds robustness bugs, and does not depend on the agent's spec reading, so it sits outside the echo chamber. It can't judge correctness, and its failures are often not minimised or reproducible unless you log the seed.
- **Stateful PBT** (Hypothesis `RuleBasedStateMachine`, fast-check `commands`, proptest-state-machine [26]) is the disciplined version of the same idea. It generates random *sequences* of operations, checks invariants after each step, *shrinks* failures to a minimal sequence and replays them from a seed.
- **Model-based testing** adds a reference model, a dict or list for example, and compares the system with it after every command. The oracle is only as independent as the model. An agent-written model shares the agent's reading of the spec, so the model should be minimal and obviously correct, ideally written or reviewed by a human or taken from the spec.
- **Guideline candidates:**
  - **G21.** For UIs and long-lived stateful systems, add a seeded random-action run (monkey or Gremlins-style) with generic oracles: no uncaught errors, no 5xx, invariants hold. Log the seed and action trace, and bound the run by time.
  - **G22.** Prefer stateful PBT over plain random sequences wherever an API exists, because shrinking and replay make the failures actionable.
  - **G23.** Keep model-based reference models trivially simple, and have them reviewed separately from the implementation.

### F2. Kaner's High-Volume Automated Testing (HiVAT) and modern equivalents
Kaner, Oliver and Fioravanti describe HiVAT as the massively automated generation, execution and evaluation of many tests, where the value comes from volume and from the oracle, not from individually designed cases [F-c][F-d](S). Mapping the HiVAT families to today's tools:

| HiVAT family (Kaner) | Oracle | Modern equivalent |
|---|---|---|
| Function equivalence testing (compare with a reference implementation) | Reference implementation | Differential PBT; Mokav-style LLM differential testing [F-e](S); Csmith-style compiler differential fuzzing |
| Long-sequence regression / diagnostic assertions (run long random sequences with assertions and probes switched on) | Built-in assertions, sanitizers, invariants | Stateful PBT; coverage-guided fuzzing with ASan/UBSan; HypoFuzz [16]; deterministic simulation testing [F-f](S) |
| Random input with weak oracle (crash/hang) | "Didn't crash" | libFuzzer, Atheris, `go test -fuzz`, Jazzer, monkey testing |
| Comparison against a constraint or spec | Spec checks | Schemathesis schema conformance [12][13]; output-format regex properties [2] |

Grizzaffi's "automation assist" outputs ("you have data", not pass/fail) correspond to HiVAT runs whose anomalies a human triages. For agents, the triage step is the part to keep (G5, G10).

### F3. Independent oracles that break the echo chamber
Ranked by how independent the oracle is from the agent's own reading of the spec:
1. **Differential against an artefact the agent didn't write**: a previous release, a reference library, another vendor's implementation, or another language's port. Grizzaffi's English-vs-Spanish DOM diff is an example. Independence is high because the oracle exists already. Disagreements still need triage, since the reference may be wrong.
2. **Spec- or schema-derived checks** (Schemathesis, Pact contracts written by the consumer team). These are independent if a human or another team owns the spec.
3. **Metamorphic relations.** The agent still picks the relation, but a relation such as "permuting the input doesn't change the output" is much harder to get subtly wrong than an exact expected value. Relations should be reviewed by a human.
4. **Approval/characterization tests on *pre-existing* behaviour.** These are independent of the *new* change, which makes them good refactoring guards. They are not evidence that the original behaviour was correct.
5. **Snapshots generated from the agent's own new code.** These are *not* independent. They pin the agent's interpretation. Treat them as change detectors, not correctness evidence (Grizzaffi's snapshot caveat).
6. **Cross-model checking** (model B writes the tests for model A's code). This is the blog's suggestion and plausibly reduces correlated errors. I found no strong quantitative evidence in this slice. It belongs to the evals researcher (lead 5(a)).

- **G24.** For high cost-of-failure code, require at least one oracle from levels 1–3 that the authoring agent did not derive from its own implementation, and say which one in the PR.
- **G25.** Label agent-generated snapshots of new behaviour as "change detectors" in the test name or docstring, and never count them as correctness coverage.

### F4. Reviewing snapshots and approvals
- **Make each check falsifiable** (re-verified, Seemann [20](F)). For a characterization or approval test: write it and see it pass, *sabotage* the system under test so each assertion fails (comment out a call, drop a condition), confirm the failure comes from the intended assertion and line, revert, and see it pass again. "If you haven't touched the production code, but the test passes, odds are that there's something wrong with the test." Seemann prefers this to Feathers' "write a failing assertion, then copy in the actual value" recipe, because the copy step can hide a tautology.
- **Review checklist for any approved or snapshot diff** (combining [8][9][10][11] with the above):
  - Is every changed hunk explained by the stated intent of the change?
  - Is the snapshot small enough to read, and are volatile fields redacted?
  - Is there at least one explicit assertion on the property that matters?
  - For *new* snapshots, did a human (or a second model) read the content as a spec, rather than only checking that a file exists?
  - Was the snapshot shown to fail under sabotage?
- **G26.** Before accepting a new snapshot or approval file, the agent must quote its key lines in the PR description and state why each is correct according to the spec. Reviewers approve the *content*, not the file.
- **G27.** Add a "sabotage check" step to the kit's characterization-test skill: inject a temporary fault, confirm the new test fails at the intended line, then revert. Mutation testing (lead 5(d)) is the automated form of this.

### Follow-up sources
- [20] re-verified: Seemann, *Empirical characterization testing*, 2025-11-03. https://blog.ploeh.dk/2025/11/03/empirical-characterization-testing/ (F)
- [F-a] Gremlins.js. https://github.com/marmelab/gremlins.js ; https://marmelab.com/blog/2020/06/02/gremlins-2.html (S)
- [F-b] shinytest2, *Monkey testing* vignette. https://cran.r-project.org/web/packages/shinytest2/vignettes/using-monkey-testing.html (S)
- [F-c] Kaner, *An Overview of High Volume Automated Testing*. https://kaner.com/?p=278 (S)
- [F-d] Kaner, Oliver, Fioravanti, *HiVAT* (STAR 2013). https://kaner.com/pdfs/StarHiVAT2013KanerOliverFioravantiFinal.pdf (S)
- [F-e] *Mokav: Execution-driven Differential Testing with LLMs*, arXiv:2406.10375. https://arxiv.org/html/2406.10375v2 (S); also *LLM-Powered Test Case Generation for Detecting Tricky Bugs* (differential prompting), arXiv:2404.10304 (S)
- [F-f] Wickström, *Finding Bugs in a Coding Agent with Lightweight DST*, 2025-08-28. https://wickstrom.tech/2025-08-28-findings-bugs-coding-agent-lightweight-dst.html (S)
- Grizzaffi, *AI Echo Chamber – Is One AI Enough?*, 2026-03-31, as summarised in 01-responsible-automation-blog.md §2.1.
