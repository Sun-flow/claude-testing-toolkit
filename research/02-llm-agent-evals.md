# 02 — Testing LLM-calling code and agents (evals, nondeterminism, CI)

Researched 2026-11-12. Scope: code that calls LLMs, agents, and agent frameworks. Sources are primary where possible (Anthropic, OpenAI, UK AISI Inspect, framework docs, papers). Items marked *(unverified fetch)* were found by search but not read in full, because the shared WebFetch budget ran out.

## 1) Key findings

1. **Treat it as two disciplines: tests and evals.** Unit tests cover the code *around* the model (tools, prompt assembly, parsing, retries, validation) "with no model requests and the same result every run". Answer quality belongs in evals ([Pydantic AI testing guide](https://pydantic.dev/docs/ai/guides/testing/)). Mixing the two gives you flaky unit suites and evals with no statistical meaning.
2. **Frameworks now ship fake models, and that is the default.** Pydantic AI has `TestModel` and `FunctionModel`, plus `Agent.override` to swap the model in place. It also has `ALLOW_MODEL_REQUESTS=False`, which blocks real calls in tests globally (same source).
3. **Record/replay is the middle layer.** VCR-style cassettes (vcrpy, pytest-recording) and built-in HTTP caches give deterministic, free replays of real responses. LangSmith's pytest plugin caches HTTP to `LANGSMITH_TEST_CACHE`, and you can commit that directory for CI ([LangSmith pytest](https://docs.langchain.com/langsmith/pytest)). promptfoo caches responses on disk for 14 days by default, keyed on a hash of the request ([promptfoo caching](https://promptfoo.dev/docs/configuration/caching/)).
4. **Grader hierarchy (Anthropic):** use code-based grading first ("fastest and most reliable"), then LLM-based grading, then human grading ("avoid if possible"). "More questions with slightly lower signal automated grading is better than fewer questions with high-quality human hand-graded evals" ([Anthropic: develop tests](https://platform.claude.com/docs/en/test-and-evaluate/develop-tests)).
5. **Grade agents on outcomes, not routes.** Anthropic warns against rigid step-sequence checks, because "agents regularly find valid approaches that eval designers didn't anticipate". Check the end state instead, for example whether the reservation exists in the database ([Anthropic: Demystifying evals for AI agents](https://anthropic.com/engineering/demystifying-evals-for-ai-agents)). τ-bench grades by comparing the final database state with an annotated goal state ([τ-bench](https://export.arxiv.org/pdf/2406.12045)).
6. **Reliability needs pass^k, not just pass@k.** pass@k is the chance that at least one of k trials succeeds; pass^k is the chance that all k succeed. A 75% per-trial rate gives about 42% pass^3 (Anthropic). In τ-bench, gpt-4o succeeded on over 60% of retail tasks, but its pass^8 was below 25%. The unbiased estimator is E[C(c,k)/C(n,k)].
7. **Report eval scores with error bars.** Report the standard error of the mean, cluster standard errors for related questions, and resample answers to reduce variance. Compare models with question-level paired differences, and run a power analysis before trusting a delta ([Miller, "Adding Error Bars to Evals"](https://arxiv.org/html/2411.00640v1)). Inspect has `stderr(cluster=...)` and `bootstrap_stderr()` built in ([Inspect metrics](https://inspect.aisi.org.uk/metrics.html)).
8. **LLM judges are biased and must be calibrated against humans.** Known biases are position, verbosity and self-enhancement ([Zheng et al., MT-Bench](https://arxiv.org/abs/2306.05685)). Anthropic's advice: calibrate the judge against human experts, give it an "Unknown" exit, use one isolated judge per dimension, use structured rubrics, let the grader reason before scoring, and use a different model from the one that generated the output.
9. **Start small, from real failures.** "20–50 simple tasks drawn from real failures is a great start." Separate *capability* evals (low pass rate, a hill to climb) from *regression* evals (should stay near 100%). If a task passes 0% across many trials, suspect the task or the grader, not the agent (Anthropic).
10. **Sandbox agent evals.** Inspect gives each sample its own container and sets `network_mode: none` by default ([Inspect sandboxing](https://inspect.aisi.org.uk/sandboxing.html)). Anthropic: start every trial from a clean environment, because shared state "artificially inflate[s] performance".
11. **CI split:** keep cheap deterministic tests on every PR. On PRs, run a sampled or cached smoke eval (Braintrust's `bt eval --first N` / `--sample N`). Run the full eval on merge or nightly, and run red-team scans on a schedule ([Braintrust run-in-CI](https://docs.braintrust.dev/evaluate/run-in-ci); [promptfoo CI/CD](https://promptfoo.dev/docs/integrations/ci-cd/)).

## 2) Recommended test pyramid for LLM/agent code

| Layer | What | Model calls | Determinism | When it runs |
|---|---|---|---|---|
| **L0 Static/contract** | Schemas for structured output and tool definitions (Pydantic/JSON Schema); prompt templates render; tool-arg validation; type checks | none | full | every commit |
| **L1 Unit (fake model)** | Business logic, tool functions, parsing and repair, retry/backoff, error paths, message assembly. Uses `TestModel`/`FunctionModel` or a hand-rolled fake client that returns scripted tool calls, malformed JSON, refusals, 429/5xx | none (blocked globally) | full | every commit |
| **L2 Replay/integration** | Real SDK wire format via recorded cassettes (`--record-mode=none` in CI); streaming chunk handling; tool-call round trips | recorded only | full | every commit |
| **L3 Live smoke** | A handful of real calls that check auth, model-ID drift and API contract; loose assertions (schema-valid, non-empty, tool called) | few, cheap model | low | PRs from trusted branches / nightly |
| **L4 Evals** | Golden dataset + graders (code first, then LLM judge, with human calibration); repeated trials; pass rate ± stderr; pass^k for agents; sandboxed environment | many | statistical | merge / nightly / before a prompt or model change |
| **L5 Adversarial** | Red-team and prompt-injection suites (promptfoo redteam, AgentDojo-style injected tool outputs) | many | statistical | scheduled + before release |
| **Prod → L4 loop** | Turn production failures and user reports into regression-eval cases | — | — | continuous |

The pyramid shape holds: L0–L2 should be most of the test count and almost all of the per-PR runtime.

## 3) Guideline candidates (imperative, with rationale)

**Layering and isolation**
- **G1. Block real model calls in unit tests by default.** Set a global guard (`ALLOW_MODEL_REQUESTS=False`, network-blocking fixtures, or cassettes in `none` record mode), so that a missing mock fails loudly instead of quietly spending money. *Rationale:* determinism, cost, no secrets needed. [Pydantic AI testing]
- **G2. Inject the model or client as a dependency, and override it in tests** (`Agent.override`, constructor injection, a fixture). Do not monkeypatch deep SDK internals. *Rationale:* you can test without access to the call site, and the override survives SDK refactors. [Pydantic AI testing]
- **G3. Use a scriptable fake (`FunctionModel`-style) to reach every branch:** each tool, invalid tool args, malformed JSON, refusal, max-tokens truncation, rate-limit errors. A generic auto-fake will not reach every path. *Rationale:* `TestModel` "won't reach every branch" on its own. [Pydantic AI testing]
- **G4. Record provider traffic with VCR-style cassettes for SDK/wire-level tests.** Scrub `authorization`, `x-api-key` and `api-key` headers and org IDs before committing, and run CI in replay-only mode. *Rationale:* deterministic and free, catches serialization regressions; LangSmith and promptfoo both recommend committing or persisting the cache. [LangSmith pytest; promptfoo caching]
- **G5. Validate every structured output and tool call against a schema in code, and unit-test the validator with bad inputs.** *Rationale:* code-based grading is "fastest and most reliable". OpenAI publishes a separate structured-output eval cookbook. [Anthropic develop-tests; OpenAI structured-outputs cookbook *(unverified fetch)*]
- **G6. Keep evals out of the default `pytest` run.** Put them in a separate directory or marker (`-m eval`) with their own CI job and budget. *Rationale:* evals are statistical and costly, and a failure there means "quality moved", not "code broke". [Pydantic AI testing; Braintrust CI]

**Eval design**
- **G7. Start with 20–50 tasks from real failures, and add a case for every production incident.** *Rationale:* early signal; real failures beat synthetic guesses. [Anthropic agent evals]
- **G8. Write tasks unambiguous enough that two experts would give the same verdict. Attach a reference solution that passes every grader.** *Rationale:* this proves the task is solvable and the grader is correct. [Anthropic agent evals]
- **G9. Test both directions:** cases where the behavior should happen and cases where it should not (for example, tool *not* called, refusal *not* triggered). *Rationale:* prevents one-sided optimization. [Anthropic agent evals]
- **G10. Prefer code graders. Use an LLM judge only for what code cannot check, and make it emit binary or small-scale labels from an explicit rubric.** *Rationale:* reproducibility, cost, and qualitative scores are hard to aggregate. [Anthropic develop-tests]
- **G11. Calibrate each LLM judge against human labels before trusting it, and re-check periodically.** Use a different model family from the system under test, let it reason before the verdict, give it an "Unknown" option, and use one judge per criterion. *Rationale:* position, verbosity and self-preference bias. [Anthropic; Zheng et al.]
- **G12. For pairwise judging, swap the A/B order and count only verdicts that stay the same.** *Rationale:* position bias. [Zheng et al.]
- **G13. Label each suite as capability or regression.** Regression suites gate merges near 100%; capability suites are tracked, not gated. Graduate saturated capability tasks into regression. *Rationale:* gating on a hill-climbing metric blocks all progress. [Anthropic agent evals]
- **G14. Read transcripts.** Sample failing and passing runs every time grader or prompt logic changes. *Rationale:* "You won't know if your graders are working well unless you read the transcripts". [Anthropic agent evals]

**Nondeterminism and statistics**
- **G15. Run k trials per case and report pass rate ± standard error. For user-facing agents, report pass^k (the estimator is E[C(c,k)/C(n,k)]).** *Rationale:* a single run cannot tell a regression apart from noise, and consistency is what users experience. [τ-bench; Anthropic; Inspect epochs]
- **G16. Gate on a threshold with a margin, and compare candidate vs baseline with paired, per-question differences. Do not compare two summary numbers.** Run a power analysis to size the eval. *Rationale:* paired tests cancel shared question difficulty. [Miller 2024]
- **G17. Use clustered standard errors when cases share a source document or template.** *Rationale:* correlated cases make naive standard errors too small. [Miller 2024; Inspect `stderr(cluster=)`]
- **G18. Pin model snapshot IDs and record them, along with temperature, prompt hash and seed, alongside every eval result.** Treat temperature 0 and seeds as variance reducers, not guarantees. *Rationale:* reproducibility; providers do not guarantee determinism. [promptfoo `--tag git.sha`; LangSmith experiment metadata]
- **G19. Do not mark LLM-quality assertions as "flaky, retry until green".** Model them as a rate with a threshold. If a metric must be non-blocking, make that explicit (e.g. DeepEval `flaky=True` reports without failing). [DeepEval CI docs]

**Agents**
- **G20. Assert the final state of the environment (DB rows, files, API side effects) first. Use trajectory assertions only for hard constraints** (a forbidden tool must not be called, confirmation required before a write, call-count budgets). *Rationale:* agents find valid unexpected paths. [Anthropic; τ-bench; OpenAI trace grading *(unverified fetch)*]
- **G21. Run each agent trial in a fresh, isolated sandbox (a container per sample, network off by default, no writable host mounts).** *Rationale:* safety and no cross-trial contamination. [Inspect sandboxing; Anthropic]
- **G22. Harden graders against reward hacking.** Passing must require really solving the task: don't let the agent edit tests or graders, and hide expected outputs. [Anthropic agent evals]
- **G23. Include prompt-injection cases in which tool outputs, retrieved docs or web pages carry attacker instructions. Measure both utility and attack success rate.** *Rationale:* indirect injection is the main agent threat (OWASP LLM01). AgentDojo-style evals measure both. [AgentDojo; OWASP LLM Top 10 2025]
- **G24. Run red-team generation (promptfoo `redteam`) on a schedule, and promote confirmed findings into the regression suite.** [promptfoo CI/CD]

**Cost and secrets in CI**
- **G25. Never expose model API keys to untrusted PR code.** Run live and eval jobs only on trusted branches or behind an environment approval. Never check out fork code under `pull_request_target` with secrets. *Rationale:* GitHub withholds secrets from fork PRs for this reason. [GitHub secrets/fork docs and community guidance]
- **G26. Use dedicated, low-limit, rotatable CI keys** (project-scoped, with spend caps), stored as CI secrets. For sensitive data, strip outputs from logs (`PROMPTFOO_STRIP_RESPONSE_OUTPUT`, `PROMPTFOO_STRIP_TEST_VARS`). [promptfoo CI/CD]
- **G27. Cache model responses in CI, keyed on prompt and config hashes, so unchanged cases cost nothing.** Bust the cache deliberately (`--no-cache`) for scheduled full runs. [promptfoo caching; LangSmith cache]
- **G28. Budget every eval job (max cases, max concurrency, timeout, a $ ceiling) and run a sample (`--first N`/`--sample N`, `--limit`) on PRs, with the full set on merge or nightly.** [Braintrust CI; Inspect]
- **G29. Emit machine-readable results (JUnit XML or JSON) and post score deltas to the PR.** [promptfoo `-o results.junit.xml`; Braintrust eval-action]

## 4) Tools table

| Tool | What for | Language | Install | CI-friendly? | Link |
|---|---|---|---|---|---|
| Pydantic AI `TestModel`/`FunctionModel` | Fake models, override, block real requests | Py | `pip install pydantic-ai` | Yes, fully offline | https://pydantic.dev/docs/ai/guides/testing/ |
| vcrpy / pytest-recording | Record/replay HTTP cassettes | Py | `pip install vcrpy pytest-recording` | Yes (`--record-mode=none`) | https://github.com/kevin1024/vcrpy |
| promptfoo | Declarative YAML evals, assertions, red-teaming, caching | Node (any target) | `npx promptfoo@latest` (Node ≥22.22) | Yes: GH Action, JUnit, `--fail-on-error` | https://promptfoo.dev/docs/integrations/ci-cd/ |
| DeepEval | Pytest-style `assert_test` with LLM metrics (RAG, agent, G-Eval) | Py | `pip install deepeval` | Yes: `deepeval test run` | https://deepeval.com/docs/evaluation-unit-testing-in-ci-cd |
| Inspect (UK AISI) | Agent and benchmark evals; solvers/scorers; epochs and reducers (`pass_at_k`, `at_least_k`); Docker/k8s sandboxes; clustered stderr | Py | `pip install inspect-ai` | Yes (CLI, logs); needs Docker for sandboxes | https://inspect.aisi.org.uk |
| OpenAI Evals API / trace grading | Hosted evals; graders over agent traces | API | OpenAI SDK | Partly (hosted) | https://developers.openai.com/api/docs/guides/evaluation-best-practices |
| Braintrust | Experiments, scorers (autoevals), PR comments | Py/TS/Go | `npm i braintrust` / `pip install braintrust autoevals` | Yes: `braintrustdata/eval-action@v2`, `bt eval --sample N` | https://docs.braintrust.dev/evaluate/run-in-ci |
| LangSmith pytest/vitest | Tests logged as experiments; `expect` fuzzy matchers; HTTP cache | Py/TS | `pip install -U "langsmith[pytest]"` | Yes; `LANGSMITH_TEST_TRACKING=false` runs offline-ish | https://docs.langchain.com/langsmith/pytest |
| Ragas | RAG metrics (faithfulness, context precision/recall) | Py | `pip install ragas` | Yes, but uses an LLM judge (costly) | https://docs.ragas.io |
| AgentDojo | Prompt-injection attack/defense environment for tool agents | Py | `pip install agentdojo` | Scheduled jobs | https://arxiv.org/abs/2406.13352 |
| τ-bench | Tool-agent-user benchmark; pass^k methodology | Py | from GitHub | Reference design | https://export.arxiv.org/pdf/2406.12045 |

## 5) Anti-patterns

- Unit tests that hit a live model, with assertions on exact strings. These are flaky, expensive, and need a key on every PR.
- "Retry until it passes" on LLM-quality assertions. It hides real regressions; use rates and thresholds (G19).
- Checking the exact tool-call sequence for open-ended agents. It penalizes valid alternative routes (Anthropic).
- Trusting an off-the-shelf LLM judge (or a generic "helpfulness 1–10") without calibrating it against human labels. Same-model self-grading. Single-order pairwise judging (Zheng et al.).
- Comparing two prompts on one run of a small dataset and shipping the higher number. That is noise without stderr, pairing or a power analysis (Miller).
- Gating merges on capability evals, or letting regression evals drift below ~100% unnoticed.
- Shared, stateful environments across agent trials. They cause correlated failures and inflated scores.
- Graders the agent can reach or edit (reward hacking). Expected answers leaked into the prompt.
- Cassettes committed with auth headers. Production PII in golden datasets without scrubbing.
- Secrets exposed through `pull_request_target` checkouts of fork code. Unlimited-spend org keys in CI.
- A 0% pass task left in the suite. It is almost always a broken task or grader (Anthropic).
- Building evals only after launch. Anthropic and others recommend starting with a small set from day one.

## 6) Open questions

- How the kit should standardize a fake-client interface across SDKs (Anthropic, OpenAI, LiteLLM, LangChain) when a framework has no `TestModel` equivalent. A thin provider-agnostic port, or per-SDK fixtures?
- Default trial count k and gate thresholds per suite size. A sample-size calculator in the kit (from Miller's power analysis) is a candidate script.
- How to version golden datasets and cassettes when a model snapshot is deprecated (re-record policy, drift alerts).
- Whether to recommend one eval runner (Inspect for agents/sandboxes vs promptfoo for prompt/config regression vs DeepEval for pytest-native teams), or let projects choose. A decision matrix may be better.
- How Claude Code hooks should detect an un-mocked model call in tests (an env guard plus a network sandbox?).
- OpenAI trace grading and Hamel Husain's evals FAQ (error analysis first, binary judges, judge TPR/TNR alignment) were found but not fully read. Fetch budget was exhausted. Worth a follow-up.

## 7) Sources

- Anthropic, Demystifying evals for AI agents: https://anthropic.com/engineering/demystifying-evals-for-ai-agents
- Anthropic, Define success criteria and build evaluations: https://platform.claude.com/docs/en/test-and-evaluate/develop-tests
- Pydantic AI, Testing guide: https://pydantic.dev/docs/ai/guides/testing/
- promptfoo, CI/CD: https://promptfoo.dev/docs/integrations/ci-cd/
- promptfoo, Caching: https://promptfoo.dev/docs/configuration/caching/
- DeepEval, Unit testing in CI/CD: https://deepeval.com/docs/evaluation-unit-testing-in-ci-cd
- LangSmith, pytest integration: https://docs.langchain.com/langsmith/pytest
- Braintrust, Run in CI: https://docs.braintrust.dev/evaluate/run-in-ci
- Inspect, Sandboxing: https://inspect.aisi.org.uk/sandboxing.html
- Inspect, Scoring metrics / epochs: https://inspect.aisi.org.uk/metrics.html
- Inspect, Scorers: https://inspect.aisi.org.uk/scorers.html
- Yao et al., τ-bench (pass^k): https://export.arxiv.org/pdf/2406.12045
- Miller, Adding Error Bars to Evals: https://arxiv.org/html/2411.00640v1
- Zheng et al., Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena: https://arxiv.org/abs/2306.05685
- Debenedetti et al., AgentDojo: https://arxiv.org/abs/2406.13352v3
- OWASP Top 10 for LLM Applications 2025 (overview): https://www.hackerone.com/blog/owasp-top-10-llms-2025-how-genai-risks-are-evolving
- OpenAI, Evaluation best practices *(unverified fetch)*: https://developers.openai.com/api/docs/guides/evaluation-best-practices
- OpenAI, Trace grading *(unverified fetch)*: https://developers.openai.com/api/docs/guides/trace-grading
- OpenAI, Structured output evaluation cookbook *(unverified fetch)*: https://developers.openai.com/cookbook/examples/evaluation/use-cases/structured-outputs-evaluation
- Husain & Shankar, AI Evals FAQ *(unverified fetch)*: https://hamel.dev/blog/posts/evals-faq/
- vcrpy: https://github.com/kevin1024/vcrpy
- GitHub fork-PR secrets behaviour (community write-up): https://2i2c.org/blog/github-action-secrets-forked-repositories/

## Follow-up on leads (from 01-responsible-automation-blog.md §5a)

Background: Grizzaffi's "AI echo chamber" thesis. When one AI writes both the code and its tests, both come from one interpretation of the requirements, so checks can pass through circular validation. How independent the check needs to be should scale with the cost of change and the cost of failure ([AI Echo Chamber, 2026-03-31](https://responsibleautomation.wordpress.com/2026/03/31/ai-echo-chamber-is-one-ai-enough/); [GIGO, 2026-08-25](https://responsibleautomation.wordpress.com/2026/08/25/gigo-we-still-need-to-test-our-assumptions/)). The evidence below largely supports him, with one important caveat.

**A. Cross-model vs same-model checking (correlated errors)**
- Kim et al. (ICML 2025) studied more than 350 LLMs. Errors are "substantially correlated": when two models are both wrong on one leaderboard dataset, they give *the same* wrong answer 60% of the time. Shared provider and shared architecture increase correlation. The key caveat is that *larger, more accurate models have highly correlated errors even across different architectures and providers*. A different vendor therefore lowers the correlation but does not remove it ([Kim et al., Correlated Errors in LLMs](https://arxiv.org/abs/2506.07962v1)).
- Panickssery et al. (NeurIPS 2024) found that LLM evaluators recognize their own outputs and score them higher. Self-preference rises with self-recognition ability (abstract-level, from search; [paper](https://arxiv.org/abs/2404.13076v1)). Zheng et al. (MT-Bench) report self-enhancement bias. Anthropic advises grading with "a different model from the one used to generate the evaluated output".
- **Conclusion for the kit:** a different-family judge is necessary but not sufficient. The strongest independence comes from **non-LLM oracles**: code graders, end-state checks, property checks, and human-written acceptance criteria. That matches Grizzaffi's "independent test interfaces".

**B. Risk-tiered eval depth**
- None of the frameworks reviewed (promptfoo, DeepEval, Inspect, Braintrust, LangSmith) has a built-in "risk tier" concept. They do provide the building blocks: tags and metadata (promptfoo `--tag`, `LANGSMITH_EXPERIMENT_METADATA`), sampling (`bt eval --sample N`, Inspect `--limit`), epochs and reducers (Inspect `at_least_k`, `pass_at_k`), per-assertion thresholds, and clustered stderr. NIST AI 600-1 (GenAI profile) frames testing, evaluation, verification and validation (TEVV) as proportional to risk ([overview](https://www.anaconda.com/blog/nist-ai-600-1-generative-ai-profile-guide); not read in full). The kit has to define its own tiers.

**C. Clarification-seeking on ambiguous tasks**
- Ambig-SWE (Vijayvargiya et al., 2025) is an underspecified variant of SWE-bench Verified. It evaluates three steps: (1) detecting underspecification, (2) asking clarifying questions, (3) using the answers. Findings: "models struggle to distinguish between well-specified and underspecified instructions". When allowed to interact, they recover key information and perform up to 74% better than non-interactive runs. Agents that guess instead risk poor results and risky tool actions ([Ambig-SWE](https://arxiv.org/abs/2502.13069v3)).
- This directly supports the GIGO thesis that requirements are assumptions to test. It can be built as an eval: a simulated user that holds hidden details, paired fully-specified and underspecified versions of each task, and a scorer that checks for a clarifying question or an explicitly stated assumption before any irreversible action.

**D. Non-boolean / inconclusive outcomes**
- Inspect scores are not limited to boolean values: they can be correct, incorrect, partial or no-answer, numeric, or multi-dimensional (dict). Reducers then aggregate across epochs ([Inspect custom scorers](https://inspect.aisi.org.uk/custom-scorers.html) — value constants stated from prior knowledge, fetch budget exhausted). Anthropic recommends giving judges an "Unknown" exit and awarding partial credit for multi-step tasks. DeepEval's `flaky=True` reports a metric without failing the run. LangSmith logs continuous `expect.*_distance` scores, and they only become assertions when you add a predicate.
- This supports Grizzaffi's "automation assist": not every check has to be pass/fail. A good result can be *"you have data, triage it"*.

**Not re-verified:** OpenAI trace grading and evaluation best practices, the OpenAI structured-output cookbook, and Hamel Husain's evals FAQ. The WebFetch budget was exhausted again, and the curl proxy denies these hosts (403 CONNECT). They stay marked *(unverified fetch)* in §3 and §7.

### Additional guideline candidates
- **G30. Never let the generator be the only oracle.** When the cost of failure is above "low", check model output with at least one non-LLM oracle (code assertion, end-state check, property check, or human-written acceptance test). *Rationale:* errors are correlated even across vendors. [Kim et al. 2025; Grizzaffi 2026]
- **G31. When an LLM judge is used, take it from a different model family than the generator. Record both model IDs, and treat agreement between them as weak evidence, not proof.** *Rationale:* self-preference and shared blind spots. [Panickssery et al. 2024; Zheng et al. 2023; Anthropic develop-tests]
- **G32. Tier eval depth by risk, and declare the tier in the suite's metadata.** Low tier: code graders, a single run, sampled on PRs. Medium tier: k≥3 epochs, a cross-family judge calibrated against human labels, a stderr-aware gate. High tier: pass^k gating, an independent non-LLM oracle, a human review sample, and red-team cases. *Rationale:* rigour should be proportional to the cost of change and failure. No framework does this natively. [Grizzaffi 2026; NIST AI 600-1]
- **G33. Include underspecified variants of key agent tasks.** Score whether the agent detects the gap and asks a question or states its assumption *before* acting, and penalize irreversible actions taken on guessed details. *Rationale:* models rarely detect underspecification unprompted, and interaction yields large gains. [Ambig-SWE 2025; Grizzaffi GIGO]
- **G34. Allow three-valued grader outcomes (pass / fail / inconclusive) and send inconclusive results to a human triage queue instead of coercing them to pass or fail. Track the inconclusive rate as a metric.** *Rationale:* forcing ambiguous grades into a verdict hides grader weakness, and triage output is valuable on its own. [Anthropic agent evals; Inspect scoring; Grizzaffi automation assist]
- **G35. Name what was not evaluated** (task types, languages, tools, risk areas) in every eval report. *Rationale:* testing reports risk to decision-makers, so coverage gaps are findings. [Grizzaffi, Why Do We Test? 2024]

Added sources: https://arxiv.org/abs/2506.07962v1 · https://arxiv.org/abs/2404.13076v1 · https://arxiv.org/abs/2502.13069v3 · https://inspect.aisi.org.uk/custom-scorers.html · https://www.anaconda.com/blog/nist-ai-600-1-generative-ai-profile-guide · https://responsibleautomation.wordpress.com/2026/03/31/ai-echo-chamber-is-one-ai-enough/ · https://responsibleautomation.wordpress.com/2026/08/25/gigo-we-still-need-to-test-our-assumptions/
