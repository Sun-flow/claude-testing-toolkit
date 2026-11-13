# Research 01: "Responsible Automation" blog (Paul Grizzaffi)

Source: https://responsibleautomation.wordpress.com/ ("Paul Grizzaffi's blog about being responsible with test automation, testing, AI, and other software things"). There are about 98 posts from 2016-08 to 2026-08, across 10 index pages (`/page/2/` … `/page/10/`).

**Coverage note (read this first).** I listed all 98 post titles. I read 9 posts in full: every AI post from 2025–2026, both "automation assist" posts, and the risk and value posts. After that, the session's shared WebFetch budget of 100 calls per hour ran out, and curl access to the host is blocked by the egress proxy. Claims marked *[title-only]* come from a post's title and its place in the index, not from reading its text. Section 6 lists the posts that should be read next once fetch budget is available.

---

## 1. Core thesis and recurring principles

- **Automation is a tool used to deliver value, not a goal in itself.** "Automation is not an 'all or nothing' endeavor" (2025). Judge it by the value it delivers and the human effort it frees up, not by how much is covered or how fast it runs.
- **Testing exists to uncover and report risk to decision-makers.** It does not guarantee quality, and bugs are a by-product. A report must state what was tested, what was *not* tested, and what was observed (2024, 2025).
- **"It's all software."** Automation code, and now AI-generated code, must be tested and engineered like product code.
- **Test your assumptions.** This recurs from 2022 to 2026. Wrong assumptions about requirements or system structure undermine both the product and the automation built to check it.
- **Automation assist.** Mechanisation that does not come from test cases and helps testers (crawl, diff, flag, generate data) is often worth more than scripted test cases. Its output can be "good or not good" or "you have data" rather than pass/fail.
- **Context over absolute rules.** "In some contexts, 'slow' may actually be 'fast enough'." Question absolute claims, including your own.
- **Use the appropriate tool, even if that means more than one.** Hybrid systems beat single tools (2019). In 2026 this became: do not let a single AI both build and check.
- **Weigh the cost of change against the cost of failure** to decide how much independence and rigour a check needs (2026).

## 2. Findings by theme

### 2.1 AI-written code and AI-written tests

- **AI Echo Chamber – Is One AI Enough?** (2026-03-31) https://responsibleautomation.wordpress.com/2026/03/31/ai-echo-chamber-is-one-ai-enough/
  - When the same AI writes the app and its tests, both come from one interpretation of the requirements. The checks "might 'pass the test' simply because the expected interpretation was implemented in the app." The post calls the risks shared blind spots, circular validation and overconfidence. He asked MS Copilot and Claude, and both agreed these risks exist.
  - Telecom analogy: two components were built from the same misreading of a protocol spec, then tested against each other, so the bug was hidden until a customer's network exposed it. The fix was *independent test interfaces*, which cost more to build but likely lowered total cost of ownership.
  - Decision rule: if the cost of change and the cost of failure are both low, one AI may be acceptable. When they are high, use a *different* AI (or an independent oracle) to test. Mentions Google Jules as a vendor pitching "AI writes and tests code".
- **GIGO: We Still Need To Test Our Assumptions** (2026-08-25) https://responsibleautomation.wordpress.com/2026/08/25/gigo-we-still-need-to-test-our-assumptions/
  - Requirements in Jira, ADO or Rally tickets are now fed to an AI acting as a "system creator", and the assumptions inside them go along unexamined. Humans "are not great at 'specifying all the things'". Expecting an AI flow to turn a ticket into correct, well-checked code is a risky bet.
  - "Review, i.e., test, our requirements and assumptions" *before* handing them to AI. Rewriting tickets to be "AI-friendly" may change the assumptions too. Treat the AI itself as an assumption to be tested.
- **2026 – Changing Gears** (2025-12-15) https://responsibleautomation.wordpress.com/2025/12/15/2026-changing-gears/
  - "Commodity AI" has changed testing enough that he will re-evaluate every old post ("do I still believe this?") and add "2026 Thoughts" sections. *Lead:* future revisions of older posts will show which pre-AI positions he has dropped.
- **"Sherman, Set The WABAC Machine" – AI Hybrids and the Appropriate Tools** (2019-11-20) https://responsibleautomation.wordpress.com/2019/11/20/sherman-set-the-wabac-machine-ai-hybrids-and-the-appropriate-tools/
  - Covers a neural network combined with an expert system (an ORNL paper). "Each of these AI systems had a different strength." Use the appropriate tool even if that means more than one, and accept that "one tool may not be able to solve all of a specific organization's needs."

### 2.2 Automation assist: non-pass/fail tooling

- **Been A Long Time Since I Wrote And Rolled: Automation Assist To The Rescue!** (2025-06-03) https://responsibleautomation.wordpress.com/2025/06/03/been-a-long-time-since-i-wrote-and-rolled-automation-assist-to-the-rescue/
  - Translation checker: crawl the sitemap, collect the English and Spanish DOM, compare element counts, then flag elements whose text is identical in both versions (likely untranslated). It was built on the *stated* assumption that the two DOMs matched one-to-one. They did not.
  - Options weighed: drop the automation, make it more complex, or keep it as is and accept noise. They kept it. The costs were cascading duplicate failures (like one missing semicolon producing many compiler errors), inconclusive "good or not good" output, and a weak heuristic that flagged addresses which are meant to stay untranslated. Testers still saved effort because they triaged the output instead of gathering it.
- **"Sherman, Set The WABAC Machine" (Slight Return) – Automation Assist** (2021-07-19) https://responsibleautomation.wordpress.com/2021/07/19/sherman-set-the-wabac-machine-slight-return-automation-assist/
  - The term was coined with Mas Kono. Examples are a protocol message tool that generates scripts, **Random Clicker** (clicks random elements and reports anomalies for a human to judge), a pre-production account creator, and a context-sensitive value replacer that edits hundreds of files. Compared to **Cem Kaner's High-Volume Automated Testing (HiVAT)**. "Automated crank turning."

### 2.3 Purpose of testing, risk and reporting

- **Why Do We Test?** (2024-07-25) https://responsibleautomation.wordpress.com/2024/07/25/why-do-we-test/
  - Written after the CrowdStrike outage. "We test to provide information to decision-makers." "At its core, testing is about uncovering and reporting risk." Treating testing or automation as purely *confirmatory* is a hidden risk: "We need to test scenarios where things go wrong or might go wrong."
  - Report untested configurations explicitly. Use **pre-mortems** to generate test ideas and testability asks. Automation gives these benefits only if "we … trust our automation", which requires good logging and reporting.
- **You Broke Me? Why We Release With Bugs** (2025-08-05) https://responsibleautomation.wordpress.com/2025/08/05/you-broke-me-why-release-with-bugs/
  - Releasing with known bugs is a business decision. The useful question is not "would a user ever do that?" but whether enough users will do it to hurt the business. Automation is a "force multiplier" because it runs sooner, checks whether the build is "egregiously broken", and flags anything unusual in newly deployed code. "Automation doesn't have to be a pass or fail endeavor." Cites Ben Simo (QualityFrog). Example bug: a signup flow that accepted birth year 2025 and reported the user's age as 0.

### 2.4 Speed, testability and value

- **My Automated Test Script Takes 45 Minutes To Run! Is This OK?** (2024-06-13) https://responsibleautomation.wordpress.com/2024/06/13/my-automated-test-script-takes-45-minutes-to-run-is-this-ok/
  - The ideal test starts from any product state, runs in seconds and parallelises easily, like a unit test against deployed software. When the system was not built for testability (sequential workstations, no way to inject data), a 45-minute happy-path script that replaces more than 8 hours of manual work is still a large win. Push for testability interfaces (start at workstation N) as a medium-term fix. Value includes the tester's reduced opportunity cost.

### 2.5 Mechanics of automation [title-only, to be verified]

The titles show the author holds positions on the following:
- Assertions: "Assertions In Automation Scripts – I Assert That They're Optional" (2021), "Stimulus, response, check: The core of test automation" (2021), "Asserting Them Softly – Soft Asserts In Practice" (2022), "Diamond Visions Softly Asserting Fire" (2021)
- Results: "Did The Script Pass? Automation Results Might Be Non-Boolean Too!" (2018), "It's Automation Logs! Better Than Bad, They're Good!" (2019), "Lazy Automation – Defer Locating For Better Logs" (2019)
- Flakiness and waits: "How to Stamp Out Intermittent Testing Issues With Periodic Automation" (2020), "Automation, Hard Waits, and The Six Million Dollar Man" (2023), "A Day at the Automation SPA Means Waiting for Elements to Disappear" (2023), "Slow Down! You're Running Automation Way Too Fast" (2023), "Should Test Automation 'Just Handle It'?" (2023), "Oh No! I Can't Get My Test Automation Scripts To Pass!" (2022)
- Randomisation: "Kill More Bugs! Add Randomization To Your Web Testing" (2023)
- Value and maintenance: "Maintaining Value – Automation's Forgotten Cost" (2017), "Don't Eat Stale Automation" (2017), "Be the Automation IRS – Auditing Your Automation" (2019), "How To Measure An Automated Test Script?" (2019), "My Automation's Not Finding Bugs, But That's OK" (2018), "Welcome To The Test Automation Illusion" (2023), "Automation Quick Wins: Who's Really Winning?" (2017)
- Parallelism and execution: "Parallelizing test automation? Read this first." (2021), "Automation Execution – Here There Everywhere" (2019), "Production Deploy with Every Check-In? You Gotta Go TWO Low!" (2022), "An Automated Smoke Test Failed; Should We Still Test The Deployment?" (2023)
- Locators and testability: "Searchiiiiiing, Seek And Locate…But Only With Appropriate Attributes for Automation" (2020), "How Am I Going to Test This?" (2020)
- Rules: "The 11th Commandment: The Automation Golden Rule" (2020), "Ten More Commandments Of Automation" (2020)
- BDD: "Necessary and Sufficient – The Logic of BDD and Automation" (2022)

## 3. Guideline candidates (imperative, testable)

1. **Don't let the same agent session write both the implementation and the only tests for it when failure is costly.** Instead, generate or review tests from the *spec*, in a separate context or model, before reading the implementation. Reason: a single model produces circular validation. *(AI Echo Chamber, 2026)*
2. **Derive expected values from the requirement or an independent oracle, never by running the code under test and copying its output into the assertion.** Reason: that encodes the implementation's interpretation as the oracle. *(AI Echo Chamber, 2026)*
3. **Before writing tests, write down the assumptions in the ticket or spec (inputs, environment, data shape, structure) and check each one,** for example by inspecting real data or the DOM. Write any you cannot verify into the PR. *(GIGO, 2026; Automation Assist, 2025)*
4. **Scale the independence and rigour of checks to the cost of failure and the cost of change.** State which applies (low or high) in the test plan or PR. *(AI Echo Chamber, 2026)*
5. **Every test-run report states what was tested, what was not tested (skipped, unreproducible environments or configs), and observed anomalies,** not just pass/fail counts. *(Why Do We Test?, 2024)*
6. **Include negative and failure-path tests for every feature** (invalid input, boundary dates such as a birth year equal to the current year, error states). Reason: purely confirmatory suites hide risk. *(Why Do We Test?, 2024; You Broke Me?, 2025)*
7. **Make test output diagnosable:** log the stimulus, the response and the check, with enough context to debug without rerunning. Reason: automation that people do not trust gives no value. *(Why Do We Test?, 2024; logs posts [title-only])*
8. **Prefer tests that can start from any state through setup APIs or data injection.** When the app lacks such seams, file a testability issue rather than silently writing long end-to-end chains. *(45 Minutes, 2024)*
9. **Don't reject a slow or noisy check purely on duration or noise.** Keep it if it replaces more human effort than it costs, but tag it (for example `@slow` or `@assist`) and keep it out of the fast gate. *(45 Minutes, 2024; Automation Assist, 2025)*
10. **Separate "assist" tooling (crawlers, diffs, heuristics producing triage reports) from pass/fail gates.** Assist output must not break CI but must be published for a human. *(Automation Assist 2021/2025; You Broke Me?, 2025)*
11. **Treat test code and AI-generated code as production software:** review, lint, version and maintain it. *(AI Echo Chamber: "it's all software")*
12. **Keep a fast "are we egregiously broken?" smoke check that runs on every deploy.** *(You Broke Me?, 2025)*
13. **Periodically audit the suite and delete or repair tests that no longer provide value.** *(Maintaining Value 2017, Automation IRS 2019 [title-only])*

## 4. Anti-patterns the author warns about

- **The AI echo chamber:** one model writes the code and the tests, so the tests pass by construction. *(2026-03-31)*
- **GIGO prompting:** handing an untested ticket to an AI and trusting confident-looking output. *(2026-08-25)*
- **Building automation on unverified structural assumptions,** such as "the DOMs match". *(2025-06-03)*
- **Confirmatory-only testing and automation:** happy paths only. *(2024-07-25)*
- **Equating testing with bug counts or quality guarantees,** and dismissing risk reports as "QA is just complaining". *(2024, 2025)*
- **Absolute speed rules** ("automation should always run in seconds") applied without context. *(2024-06-13)*
- **All-or-nothing automation thinking:** discarding useful but imperfect tools. *(2025-06-03)*
- **Untrusted automation:** poor logs and reports make results get ignored. *(2024-07-25)*
- **Cascading failures:** one root cause reported as N failures, which hides the signal. *(2025-06-03)*
- *[title-only]* Hard waits; "just handle it" auto-retry or self-healing that hides issues; running too fast for the app (timing races); stale or unmaintained automation; "quick wins" that look good on paper; the test-automation "illusion" of coverage.

## 5. Leads for other researchers

### (a) LLM/agent evals and testing AI libraries
- **Independent oracle versus self-consistency.** Look for evidence on *cross-model* checking (model A writes, model B tests or judges) versus same-model checking. How much does a different model family reduce correlated errors? Search terms: "LLM-as-judge self-preference bias", "correlated errors across LLMs", "N-version programming with LLMs".
- **Cost-of-failure-weighted eval rigour.** Find frameworks that tier eval depth by risk (for example, risk-based eval gating in promptfoo, Inspect, OpenAI Evals, DeepEval).
- **Requirement and spec ambiguity as an eval target.** Look for evals that test whether an agent *asks about* or *surfaces* assumptions in an ambiguous ticket instead of guessing (the author's GIGO thesis). Benchmarks on clarification-seeking (for example "ambiguous SWE tasks").
- **Non-boolean results.** Find eval harnesses that support graded or "inconclusive" outcomes and human triage queues, not just pass/fail.
- Vendor claim to verify: **Google Jules** "writes and tests code". What independence safeguards, if any?

### (b) Property-based, fuzz, snapshot and approval testing
- **Random Clicker** and "Kill More Bugs! Add Randomization To Your Web Testing" (2023) are the author's randomised and monkey testing. Compare with Hypothesis or fast-check stateful testing, Gremlins.js, and model-based testing.
- **Cem Kaner's High-Volume Automated Testing (HiVAT)** is the conceptual root for long-sequence and random-input automation. Find modern equivalents.
- **Differential or oracle-by-comparison checks** (English versus Spanish DOM diff). Research differential testing, metamorphic testing, and approval or snapshot tests as *independent* oracles that break the AI echo chamber.
- Snapshot caveat: snapshots generated from current output encode the implementation's interpretation (echo-chamber risk). Look for guidance on reviewing or approving snapshots.

### (c) CI and test-environment hygiene (flakiness, isolation, determinism)
- Read these posts (not yet read): "How to Stamp Out Intermittent Testing Issues With Periodic Automation" (2020), "Automation, Hard Waits, and The Six Million Dollar Man" (2023), "Slow Down! You're Running Automation Way Too Fast" (2023), "Should Test Automation 'Just Handle It'?" (2023), "Parallelizing test automation? Read this first." (2021), "An Automated Smoke Test Failed; Should We Still Test The Deployment?" (2023), "Production Deploy with Every Check-In? You Gotta Go TWO Low!" (2022).
- Concepts to chase: running scheduled (periodic) automation to *detect* intermittent product bugs rather than retrying them away; the self-healing and auto-retry debate; testability seams (start from any state, data injection) that enable parallelism and isolation; tagging slow or assist suites out of the PR gate; collapsing cascading failures to a root cause in reports.

### (d) Agent-written test quality and mutation testing
- **Circular validation** is the central risk. Research mutation testing (Stryker, PIT, mutmut, cargo-mutants) as an *objective* check that agent-written tests can fail. Also research "tests written after code by an LLM assert current behaviour" (test oracle problem) and spec-first or test-first prompting.
- **Confirmatory bias:** measure the share of negative or failure-path tests in agent-written suites. Look for linters or heuristics that flag happy-path-only suites.
- **Assertions:** the author argues assertions can be "optional" and favours soft asserts in some contexts (2021–2022 posts, unread). Reconcile with agents that write assertion-free or `assert True` tests. Where does "assist" end and "vacuous test" begin?
- **Measuring test value** ("How To Measure An Automated Test Script?" 2019; "Need a Testing Metric? Put Points on Your Test Cases" 2023). Candidate metrics beyond coverage.

### (e) Claude Code skills, plugins, hooks and MCP for testing
- **Independent-reviewer subagent or skill:** a skill that spawns a fresh-context or different-model subagent that writes tests from the spec or ticket *only* (no implementation access), which directly addresses the echo chamber. Check how Claude Code subagents can be restricted from reading `src/`.
- **Assumption-check skill or hook:** before generating tests, the agent writes an "Assumptions" list (from the ticket) and verifies each one. A Stop or PreToolUse hook could require the list in the PR body.
- **Run-report hook:** a PostToolUse hook on test commands that summarises tested, not tested (skipped or xfail) and anomalies, instead of bare pass/fail.
- **Guard hooks:** block commits that add hard sleeps (`sleep`, `Thread.sleep`, `waitForTimeout`), blanket retries, or tests whose expected values were copied from a just-run output.
- **MCP:** ticket-system MCPs (Jira, Azure DevOps, Rally, as named by the author) to pull requirements as the oracle source; browser MCPs (Playwright) for randomised exploration in the style of Random Clicker that produces triage reports, not gates.

## 6. Posts to read next (priority order)
1. Welcome To The Test Automation Illusion (2023-04-11)
2. Automation State – Answer Me, These Questions Three (2024-05-01)
3. Does Test Automation Necessarily Make Our Jobs Easier? (2024-04-02)
4. Should Test Automation "Just Handle It"? (2023-01-31)
5. How to Stamp Out Intermittent Testing Issues With Periodic Automation (2020-01-25)
6. Assertions In Automation Scripts – I Assert That They're Optional (2021-04-07)
7. Stimulus, response, check (2021-06-02)
8. Did The Script Pass? … Non-Boolean (2018-11-11)
9. Kill More Bugs! Add Randomization (2023-05-31)
10. Test Your Assumptions (2022-11-15)
11. Ten More Commandments / 11th Commandment (2020-09)
12. Maintaining Value (2017-11-15); My Automation's Not Finding Bugs, But That's OK (2018-01-02)

URLs follow `https://responsibleautomation.wordpress.com/YYYY/MM/DD/<slug>/`. Index pages 2–10 list them all.


## 7. Corrections after the follow-up (2026-11-13)

See `01b-blog-followup.md`, which read the 12 posts in §6. "Test Automation Illusion" is about the promise of 100% automation, not an illusion of coverage. "Just Handle It" doesn't discuss auto-retry or self-healing; it is about tolerated variations (now TG-18a). "Maintaining Value" is about budgeting for maintenance; the "remove stale automation" point (candidate 13) comes from "Automation State" (2024). The randomisation post relies on logs and screenshots, not seeds. Still unverified: the posts listed at the end of 01b.
