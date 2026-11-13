# Research 01b: "Responsible Automation" blog, follow-up reading

Follow-up to `01-responsible-automation-blog.md` (report 01). Source: https://responsibleautomation.wordpress.com/ (Paul Grizzaffi). Read 2026-11-13.

**Coverage.** I read all 12 items in report 01 §6 with WebFetch. Items 11 and 12 are two posts each, so that is 14 posts. WebFetch gives a model summary of the page plus verbatim quotes I asked for; I did not get raw HTML. Quotes below are the ones the fetch returned as verbatim. None of the 14 posts has a "2026 Thoughts" section yet. Posts in report 01 §2.5 that are *not* in this list are still unread (see §2).

Guideline candidates are written as imperative, testable rules ("G-n"). The TG mapping is in §3.

---

## 1. Per post

### 1.1 Welcome To The Test Automation Illusion (2023-04-11)
https://responsibleautomation.wordpress.com/2023/04/11/welcome-to-the-test-automation-illusion/
- The "illusion" is the vendor promise of total automation: "'100% automated testing' is almost always a fantasy." It is **not** about an illusion of coverage (report 01 §4 guessed that wrongly).
- Big tech companies have different money and risk tolerance; copying them "simply because they do it is a bad idea."
- New tools are not automatically better, and giving one to untrained people is like handing over a chainsaw.
- Switching tools has hidden costs: rebuild everything, or run two toolchains with duplicated helpers (login/logout), both kept in sync and supported in CI.
- Warns about the sunk-cost fallacy and opportunity cost. "The number one wrong way of determining that answer is ignoring our context."
- **G-1.** Don't introduce a second test framework, runner or assertion library into a repo that already has one unless the human asks. If you think one is needed, propose it with the duplicate-maintenance cost spelled out.

### 1.2 Automation State – Answer Me, These Questions Three (2024-05-01)
https://responsibleautomation.wordpress.com/2024/05/01/automation-state-answer-me-these-questions-three/
- Three questions: do we have the *right* automation, *enough* automation, *too much* automation? Value is the measure for all three.
- "Right": ask "Why should we automate this?" and "Which business goal will this help us attain?" Sometimes automation costs more than it returns. Non-test-case automation can be worth as much or more.
- "Enough": look for where testing effort goes, repetitive work, and "programmatically straightforward" areas. API automation is usually easier to build and maintain and runs much faster than UI automation. Example: a smoke suite cut from 30 to 8 minutes.
- "Too much": teams add automation to show progress without checking that existing automation still pays off. Review it all; stale automation is a candidate for removal or merging.
- **G-2.** Test behaviour at the lowest layer that can observe it: write an API or unit test, not a UI test, unless the behaviour under test is the UI itself.
- **G-3.** When a change makes a test obsolete or duplicate, propose removing or merging it in the PR with the reason. Don't delete it yourself (TG-14 still applies).

### 1.3 Does Test Automation Necessarily Make Our Jobs Easier? (2024-04-02)
https://responsibleautomation.wordpress.com/2024/04/02/does-test-automation-necessarily-make-our-jobs-easier/
- Rebuts a vendor post. "adding automation can increase stress and pressure, especially initially."
- "automation will cause more disruptions, at least initially": new scripts need fixing, unattended runs produce failures to investigate, and too many failures cause "failure fatigue", which leads teams to skip risk analysis.
- Developer–tester disputes ("passes manually", flaky, "works on my machine") go *up* at first. They fall only once the automation earns trust, consistency and availability.
- Test-data storage (Excel etc.) is a team decision. Don't rely only on a tool's built-in test-data features.
- **G-4.** Treat a growing count of unexplained failures as a defect in the suite: each red result in the PR gate must have an owner and an explanation in the run report, or be quarantined (TG-32). Never leave failures that the team learns to ignore.

### 1.4 Should Test Automation "Just Handle It"? (2023-01-31)
https://responsibleautomation.wordpress.com/2023/01/31/should-test-automation-just-handle-it/
- "Handling" means coding around differences in the workflow: dismissing a popup, refreshing on "System is unavailable" (QA-only), logging in a second time, OS popups in a random order. Doing so means "we may be masking legitimate issues that should be evaluated and possibly addressed."
- Key distinction: **appreciable** differences (intolerable risk if treated as equivalent, generally higher risk) and **non-appreciable** ones (tolerable risk if handled). Which is which depends on context, and stakeholders must decide.
- Examples: iOS location/push popups in either order counted as non-appreciable, so it was handled. A "missing signature" prompt that depends on data counted as appreciable, so it got separate scripts per case.
- "The trust approach": an appreciable difference may be handled in later tests only if other tests have already explored it well enough.
- Start scripts as close to the scenario as possible to avoid the need to handle anything. "script success is not the goal for automation"; "obtaining useful information is the goal".
- Note: the post does **not** discuss auto-retry or "self-healing" locators. Report 01 §4 overreached there.
- **G-5.** Before adding code to a test that tolerates a variation (optional dialog, alternate order, refresh-on-error, re-login), classify the variation as appreciable or non-appreciable and record why in a comment. Handle it only if non-appreciable. If appreciable, write a separate test for each variant, or ask the human.
- **G-6.** Every handler that tolerates a variation must log when it fires, so that the run report can count how often it was needed.

### 1.5 How to Stamp Out Intermittent Testing Issues With Periodic Automation (2020-01-25)
https://responsibleautomation.wordpress.com/2020/01/25/how-to-stamp-out-intermittent-testing-issues-with-periodic-automation/
- Running automation only at event boundaries (after a deploy) gives few chances to catch intermittent bugs. Run it on a schedule as well: "It doesn't have to be fancy; you just need it to run more often."
- Based on Kaner's HiVAT and long-sequence regression testing: take scripts known to pass, run them many times (for example 1,000), and investigate the failures.
- If every script starts and stops the application, problems that appear only after long runtime are missed, so adjust setup and teardown for this mode.
- Manage failure fatigue: "Don't run your tests more often than you are prepared to triage the results." Keep scripts short and logs diagnostic.
- It is not for everyone. It fits teams that have intermittent problems and the capacity to triage.
- **G-7.** Run passing tests repeatedly on a schedule (not in the PR gate) to surface intermittent *product* bugs. Set the frequency to the team's triage capacity, and treat an intermittent failure as a product-bug lead before calling it test flakiness.
- **G-8.** Include at least one long-running sequence in the scheduled tier that does not restart the system between tests, so that leaks and state build-up can show.

### 1.6 Assertions In Automation Scripts – I Assert That They're Optional (2021-04-07)
https://responsibleautomation.wordpress.com/2021/04/07/assertions-in-automation-scripts-i-assert-that-theyre-optional/
- "zero is also a number, meaning we can have test scripts with no explicit checks or assertions." He also says this is usually weak: an order script that never checks the order "likely missed the point." He criticises teams that commented out assertions to "get the automation to pass".
- Implicit checks can make explicit ones redundant. Example: if the API helper already fails on a non-200 status, re-asserting the status adds nothing. Another example is a browser walk across distributed components, where reaching the last page proves they are up: "all the checks were implicit in the behavior of each script".
- When checking is costly or non-deterministic, automate only the stimulus and the response, store the responses in a known place, and let testers judge them afterwards.
- **G-9.** A test may rely on an implicit check (a helper that raises on a bad status, a navigation that fails if the element is missing) only if that helper's failure behaviour is itself tested or documented. Name the implicit check in a comment. Otherwise add an explicit assertion.
- **G-10.** A script with no oracle that saves responses for a human goes in the assist tier (TG-50), never in the test suite.

### 1.7 Stimulus, response, check: The core of test automation (2021-06-02)
https://responsibleautomation.wordpress.com/2021/06/02/stimulus-response-check-the-core-of-test-automation/
- Automation is a stimulus, then a response, then one or more checks, which are "usually implemented as assertions". One stimulus can produce several responses and the other way round.
- Behaviours ("Add an item to cart") can be carried out through different stacks (GUI, API). Adjacent stacks allow **cross-technology checks**: update a profile through the GUI, then confirm it through the API or SQL.
- "One check per script" keeps scripts small and fast with fewer reasons to fail. It breaks down when setup is slow (GUI), where several checks per script make sense, at the risk that one failure hides the later checks.
- "Most of the time, deterministic checks are required to produce trustworthy and valuable results". Non-deterministic checks fit only in automation assist, where they flag results for a human.
- **G-11.** For an end-to-end test of a write path, check the persisted result through a different channel from the one that performed the write (for example, write through the UI and read back through the API or DB).
- **G-12.** When one slow-setup test makes several checks, use soft or aggregated assertions, so that every failed check is reported rather than only the first.

### 1.8 Did The Script Pass? Automation Results Might Be Non-Boolean Too! (2018-11-11)
https://responsibleautomation.wordpress.com/2018/11/11/did-the-script-pass-automation-results-might-be-non-boolean-too/
- Correction to report 01: he *prefers* pass/fail for script automation, because a fail means someone must investigate. Multi-status systems tend to collapse back into two buckets. At one company "warn" was counted as a pass in the percent-pass metric.
- "if we aren't going to treat scripts with different results differently, then why bother with different results". Any extra status needs its own action.
- He accepts **"indeterminate"** results. Example (Greg Paskal): scripts that were slowly taking longer to run had not failed, but the trend predicted trouble. Present such results so they "scream" for attention.
- Collect the data that the extra statuses need: add logging, and cross-check automation logs against product logs (all steps pass, but the product logged a warning, so the result is indeterminate).
- **G-13.** Never count an indeterminate, warning or inconclusive result as a pass in any summary metric. Each non-pass status must map to a stated action (for example, inconclusive goes to human triage).
- **G-14.** The run report flags duration regressions (a test much slower than its recent baseline) as an anomaly even when it passes.
- **G-15.** For integration and end-to-end runs, scan the product's logs for errors and warnings during the test window, and report them as anomalies even when every assertion passed.

### 1.9 Kill More Bugs! Add Randomization To Your Web Testing (2023-05-31)
https://responsibleautomation.wordpress.com/2023/05/31/kill-more-bugs-add-randomization-to-your-web-testing/
- Motivation is Beizer's pesticide paradox: bugs remain where testing hasn't been "applied". A random clicker reaches valid but unintuitive paths.
- Fuzzing here means "you don't necessarily know what *should* happen": watch for things that must not happen (404s, crashes) using heuristics.
- Reproducibility is the main objection: "Your automation has little value if you can't reproduce the situation that caused a specific unexpected behavior." The fix is breadcrumbs: a log of each page, screenshots of each odd state, and *which heuristic flagged it*.
- The post does **not** mention random seeds. Seed logging in TG-26 is the kit's own addition, not his.
- It is "assistance, not testing". Output is two piles (nothing odd, odd); humans triage the odd pile. Report false positives to the tool owner, and drop a heuristic if its false positives cost more than the bugs it finds.
- **G-16.** Every random-exploration or fuzz finding must carry enough to replay or locate it: the seed or action sequence, the state or URL, an artifact (screenshot or input), and the name of the heuristic or invariant that flagged it.
- **G-17.** Track false-positive rates per heuristic in assist tools. Remove or tune a heuristic whose findings are mostly false positives.

### 1.10 Test Your Assumptions (2022-11-15)
https://responsibleautomation.wordpress.com/2022/11/15/test-your-assumptions/
- Grad-school story: a sewing-pattern generator kept producing wrong curves. He checked his maths for hours. The cause was a landmark whose position differed between the visual model and the data model he had been given. "I had assumed that everything I was given was accurate; clearly, this was not so."
- No one acted in bad faith; the cause was communication gaps between several people.
- "we frequently take too many things at face value." Question inherited requirements and data, and don't assume others share your understanding.
- He asks questions such as whether a requirement conflicts with other parts of the approach, and whether a test case tests what it is meant to test.
- **G-18.** Treat given fixtures, reference data and inherited models as assumptions: before debugging your own logic for a long time, check that two sources describing the same thing agree (for example, schema against sample data, or spec table against fixture).

### 1.11a Ten More Commandments Of Automation (2020-09-14)
https://responsibleautomation.wordpress.com/2020/09/14/ten-more-commandments-of-automation/
- I: don't automate only "from test cases". II: "Automation development *is* software development." III: follow the language's idioms. IV: plan for maintenance.
- V: **no scripts that depend on each other.** They can't run alone or in parallel. The one exception is a single shared setup script.
- VI: emit logging and reports that are "detailed but digestible". VII: influence testability by telling developers what testing needs. (Second VII, numbering error in the post): don't give in to the sunk-cost fallacy; sometimes "we should just start over."
- IX: beware Rube Goldberg machines, automation that costs more to maintain than doing the task by hand.
- X: **don't make test data depend on transient data.** A script broke at the July to August change because it hardcoded July dates. "dynamically create the dates based on the current month."
- **G-19.** No test may depend on another test's side effects or run order. Shared setup goes in fixtures. (Restates TG-27.)
- **G-20.** Never hardcode calendar-relative dates in test data. Either freeze or inject the clock, or compute dates relative to the injected "now". Add a test run at a month or year boundary for date-sensitive logic.

### 1.11b The 11th Commandment: The Automation Golden Rule (2020-09-08)
https://responsibleautomation.wordpress.com/2020/09/08/the-11th-commandment-the-automation-golden-rule/
- "Thou shalt automate responsibly." "Responsible" means doing what is right, and "right" depends on context.
- A Pyrrhic victory is a win whose cost is more than its value: "our automation might cost us more than the value it provides".
- "We must make deliberate decisions about how, when, where, and why to automate". That includes knowing when not to automate, when to stop and when to change approach.
- Following the rule does not guarantee success.
- No new testable rule. It supports the kit's sanctioned stop (TG-19) and tiering (§1).

### 1.12a Maintaining Value – Automation's Forgotten Cost (2017-11-15)
https://responsibleautomation.wordpress.com/2017/11/15/maintaining-value-automations-forgotten-cost/
- First automation efforts seldom plan for maintenance. When the next release breaks scripts, the effort is labelled a failure, when the real failure was in planning.
- Four forgotten costs: licences and support, script maintenance, tool and framework maintenance, and documentation.
- Codeless tools are not exempt, because they still sequence commands and so are software.
- Correction to report 01 §3.13: this post is about *budgeting* maintenance. It does not say to audit and delete tests. The "remove stale automation" point is in Automation State (1.2).
- **G-21.** When adding test infrastructure (a new helper layer, fixture framework, page objects, test-only service), list in the PR what will need upkeep when the product changes. (Weak: process advice, hard to test mechanically.)

### 1.12b My Automation's Not Finding Bugs, But That's OK (2018-01-02)
https://responsibleautomation.wordpress.com/2018/01/02/my-automations-not-finding-bugs-but-thats-ok/
- Leaders called the automation worthless because it had found no bugs. He disagrees: bug-finding is one value. Others are pace (faster releases) and coverage.
- Automation finds bugs mostly when it is first written and when code changes. A mature, rarely changed product gives few finds (pesticide paradox).
- The smoke suite was chosen to support a faster release cadence, and it did.
- **G-22.** Don't judge a suite by the bugs it has found. Judge its power to detect a defect with mutation testing on changed code (TG-34), and judge its value by what it enables (gate speed, release cadence).

---

## 2. Status of report 01's [title-only] points

| Report 01 point | Status | Note |
|---|---|---|
| §2.5 Assertions: "I Assert That They're Optional", "Stimulus, response, check" | **Confirmed, sharpened** | Zero explicit checks is valid only with implicit checks or human review of stored responses. He says most scripts need ≥1 explicit check and criticises commenting out assertions. |
| §2.5 Soft asserts: "Asserting Them Softly" (2022), "Diamond Visions Softly Asserting Fire" (2021) | **Unverified** | Stimulus-response (1.7) supports several checks per slow-setup script; the soft-assert posts themselves are unread. |
| §2.5 Results: "Did The Script Pass? … Non-Boolean" | **Confirmed with correction** | He prefers pass/fail. Extra statuses ("indeterminate") are worth having only if they get different actions and stand out. |
| §2.5 Logs (2019), "Lazy Automation – Defer Locating" (2019) | **Unverified** (titles) | Logging emphasis is confirmed by Commandment VI and the periodic post. |
| §2.5 "Periodic Automation" | **Confirmed** | Adds a triage-capacity limit and long runs without restarts. |
| §2.5 "Should Test Automation 'Just Handle It'?" | **Confirmed, with correction** | It is about appreciable vs non-appreciable workflow differences, decided with stakeholders. It is not about auto-retry or self-healing (report 01 §4 overreached). |
| §2.5 Hard waits, SPA waits, "Slow Down!", "Can't Get My Scripts To Pass" | **Unverified** | Not read. |
| §2.5 "Kill More Bugs! Add Randomization" | **Confirmed** | Breadcrumbs, not seeds; assist not testing. |
| §2.5 "Maintaining Value" | **Confirmed, corrected** | About budgeting maintenance costs, not auditing or deleting tests. |
| §2.5 "Don't Eat Stale Automation", "Automation IRS", "How To Measure…", "Quick Wins" | **Unverified** | "Remove stale automation" is confirmed via Automation State (2024). |
| §2.5 "My Automation's Not Finding Bugs" | **Confirmed** | |
| §2.5 "Test Automation Illusion" | **Corrected** | It is about "100% automation" and tool-chasing, not an illusion of coverage. |
| §2.5 Parallelism and execution (4 posts) | **Unverified** | Commandment V (no inter-script dependency, needed for parallelism) is confirmed. |
| §2.5 Locators and testability posts | **Unverified** | Commandment VII ("influence testability") is confirmed. |
| §2.5 Commandments | **Confirmed** | |
| §2.5 BDD "Necessary and Sufficient" | **Unverified** | |
| §3 candidate 7 (diagnosable logs; logs posts title-only) | **Confirmed** via Commandment VI and periodic post | |
| §3 candidate 13 (audit and delete; cited Maintaining Value and IRS) | **Confirmed, re-sourced** | Source is Automation State 2024. Maintaining Value doesn't say this; IRS unread. |
| §4 "just handle it auto-retry/self-healing" | **Partly corrected** | Handling can mask issues, yes; retry and self-healing aren't discussed. |
| §4 hard waits; running too fast | **Unverified** | |
| §4 stale automation | **Confirmed** (Automation State) | |
| §4 "quick wins" | **Unverified** | |
| §4 "illusion of coverage" | **Corrected** | It is the illusion of 100% automation / panacea tools. |
| §5(d) assertions-optional vs vacuous tests | **Resolved** | His "optional" means implicit checks or human-reviewed output, which is assist. It isn't licence for `assert True`. |

## 3. Mapping new points to TESTING-GUIDELINES.md (TG-01..TG-50)

| Candidate | Mapping |
|---|---|
| G-1 no second framework without asking | **New:** "TG-new-a. Use the repo's existing test runner, assertion and mocking libraries. Don't add another without the human's agreement; if you propose one, state the duplicate-maintenance cost." |
| G-2 lowest layer that observes the behaviour | **New** (partly implied by TG-28a): "TG-new-b. Test each behaviour at the lowest layer that can observe it; use UI/E2E tests only for UI behaviour and a few smoke journeys." |
| G-3 propose removing obsolete tests | **Supports TG-14** (agent proposes, human decides); adds a positive duty. Could join TG-14: "When a test becomes obsolete, say so in the PR with the reason." |
| G-4 no ignored failures / failure fatigue | **Supports TG-32, TG-49** |
| G-5 appreciable vs non-appreciable handlers | **New, sharpens TG-18:** "TG-new-c. Code in a test that tolerates a variation (optional dialog, alternate order, retry-on-error page, re-login) needs a comment saying why the variation is harmless. If it could hide a product bug, write a separate test for each variant or ask the human." |
| G-6 log when a handler fires | **New, part of TG-new-c**; feeds TG-49 anomalies |
| G-7 scheduled repeat runs, triage-capacity limit | **Supports TG-32** (scheduled re-runs). Adds "frequency ≤ triage capacity" and "treat as a product-bug lead first" |
| G-8 long sequence without restart | **Tension with TG-27** (hermetic, no shared state). No contradiction, because TG-27 covers unit tests and this is a separate scheduled tier. **New** note under TG-32: "the scheduled tier may include long-running, non-restarting sequences." |
| G-9 implicit checks need a tested or documented helper | **Contradicts TG-07 in part:** TG-07 says "no assertion at all doesn't count", while Grizzaffi accepts tests whose only check is implicit in a helper that raises. Proposed TG-07 addition: "An implicit check counts only if the helper's failure behaviour is itself tested, and the test names it in a comment." |
| G-10 oracle-less scripts are assist | **Supports TG-50** |
| G-11 cross-channel verification of writes | **Supports TG-08**; **new** E2E detail: "verify a write through a different channel from the one that made it." |
| G-12 soft asserts for slow-setup multi-check tests | **Tension with TG-11** ("one behaviour per test"). It is compatible if the checks cover one behaviour. Proposed note on TG-11: "for slow setup, several checks of one behaviour are fine; use soft or aggregated assertions so all failures show." |
| G-13 non-pass is never counted as pass; each status has an action | **Supports TG-44**; **sharpens TG-49:** "Summaries never count inconclusive/warn/xfail-pass results as passes." |
| G-14 duration regression is an anomaly | **New, extends TG-49:** "Report tests much slower than their baseline as an anomaly." |
| G-15 product-log scan during E2E | **New, extends TG-49 / TG-28b:** "Integration runs collect product error and warning logs for the test window and report them." |
| G-16 replay data for random findings | **Supports TG-26**, which adds seeds (Grizzaffi doesn't mention seeds). Sharpen: also record the triggering heuristic and an artifact. |
| G-17 track false positives per heuristic | **Supports TG-50**; small new clause |
| G-18 check inherited fixtures and models agree | **Supports TG-01** (check assumptions against real data); extend the list to "given fixtures and reference data" |
| G-19 no inter-test dependence | **Supports TG-27** |
| G-20 no hardcoded calendar dates | **Supports TG-27** (frozen clock); **new** explicit clause: "Never hardcode dates relative to today; derive from an injected clock, and test month/year boundaries for date logic." |
| G-21 list upkeep for new test infrastructure | **New, weak** (hard to check). Probably fold into the review checklist D. |
| G-22 judge suites by mutation score, not bugs found | **Supports TG-34** |
| 11th commandment: know when to stop | **Supports TG-19** |

### Contradictions and tensions
1. **TG-07 vs "assertions are optional".** Grizzaffi accepts tests with no explicit assertion when a lower layer checks implicitly. TG-07 rejects "no assertion at all". Reconcile with the G-9 amendment; keep `assert True` and assertion-free smoke tests outside the suite (TG-50).
2. **TG-11 vs several checks per script.** He favours several checks per script when setup is slow. Compatible if TG-11 means one *behaviour* and not one *assertion*; worth saying explicitly.
3. **TG-27 hermetic vs periodic long runs without restarts.** These are different tiers, so it's not a real conflict, but TG-32 should allow it.
4. **TG-26 seeds attributed to R1?** TG-26 cites R3/R4, not R1, which is fine. Note that Grizzaffi's randomisation post relies on breadcrumbs and never mentions seeds, so don't cite him for seed logging.
5. Report 01 itself: "illusion of coverage", "self-healing/auto-retry" and candidate 13's source were wrong or overreached (see §2).
