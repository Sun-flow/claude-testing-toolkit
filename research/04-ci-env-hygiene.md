# 04 — CI pipelines and test-environment hygiene

Scope: making test runs fast, deterministic, isolated and trustworthy, both in CI and in the ephemeral cloud containers coding agents use. Researched 2026-11-12. Note: the session's WebFetch budget ran out near the end, so a few tool details (Jest `--shard`, pre-commit, alls-green, JUnit actions) are cited from search results and official doc URLs rather than full-page reads.

## 1. Key findings

1. **Flakiness is common and erodes trust.** Google measured that ~1.5% of test runs report a flaky result, ~16% of tests show some flakiness, and 84% of observed pass-to-fail transitions involve a flaky test [S1]. The *Software Engineering at Google* (SWE@G) book says "as you approach 1% flakiness, the tests begin to lose value" [S3].
2. **Most root causes are in the environment.** Google groups the causes by component. The test itself: bad setup or cleanup, assumptions about time or data, timing, order dependence. The framework: too few resources, interference between tests. The app: races, leaks, slow services. The OS and hardware: network, disk, contention. Its conclusion: "Hermetic environments, in general, are less likely to be flaky" [S2].
3. **Quarantine works only with a time limit; retries hide bugs.** Fowler says to quarantine non-deterministic tests and to cap how many tests or how long they stay there [S4]. Google's "fail 3 times before reporting" and auto-quarantine reduce noise, but they delay real breakages and can hide real race conditions [S1]. Trunk prefers quarantine (the test keeps running and reporting) over disabling it, and notes that auto-reruns corrupt the data used to detect flaky tests [S5].
4. **Hermetic, size-bounded tests.** SWE@G's sizes: *small* tests run in one process with no sleep, no I/O and no network; *medium* tests may use localhost only; *large* tests may go multi-machine. Its rule: "a test should contain all of the information necessary to set up, execute, and tear down its environment" [S3].
5. **Determinism has to be enforced by tooling, not by convention.** Useful tools: randomized order with a reproducible seed (pytest-randomly, Vitest `sequence.shuffle`/`seed`) [S6][S7], socket blocking (pytest-socket) [S8], a wrapped or frozen clock [S4][S20], and per-test timeouts (pytest-timeout) [S9].
6. **Coverage is a floor signal, not a goal.** "Code coverage only measures that a line was invoked, not what happened as a result." 80% targets turn into ceilings. Google suggests measuring coverage from small tests only [S3]. Gate on *diff* coverage (diff-cover `--fail-under`) and turn on *branch* coverage (`branch = true`) [S10][S11].
7. **Lockfiles must be enforced, not just committed.** `uv sync --locked` errors if the lockfile is stale. `--frozen` skips that check [S12]. For npm, the equivalent is `npm ci`.
8. **GitHub Actions hygiene is now security-critical.** Pin actions to a full commit SHA ("the only way to use an action as an immutable release"). Default `GITHUB_TOKEN` to read-only. Avoid `pull_request_target`. Pass untrusted input through env vars, never inline `${{ }}` in scripts [S13]. Use `concurrency` to cancel superseded PR runs [S14].
9. **Claude Code cloud sessions** run on fresh Ubuntu 24.04 x86_64 VMs (~4 vCPU / 16 GB / 30 GB). They come with Python + pytest/uv, Node 20–22, Docker, and PostgreSQL 16 / Redis 7 (installed but not started). Default "Trusted" network allows package registries only [S15].
   - A **setup script** provisions the VM. It runs as root before Claude starts, and is snapshot-cached only if it finishes in about 5 minutes; the cache is rebuilt about every 7 days.
   - A **SessionStart hook** in the repo's `.claude/settings.json` handles project deps. It runs on every start and resume, both locally and in the cloud. Scope it with `CLAUDE_CODE_REMOTE=true` and make it idempotent.
   - Foreground commands time out at 2 min by default (max 10 min). Hooks time out at 600 s [S15].
10. **Agents need a deterministic check they can run.** "Give Claude a check it can run… It's the difference between a session you watch and one you walk away from." Put test commands in CLAUDE.md, "prefer running single tests", and use Stop hooks as a deterministic gate [S16]. Devcontainers give agents an isolated environment that is identical for everyone, with optional egress firewalling. They don't stop exfiltration under `--dangerously-skip-permissions` [S17].

## 2. Guideline candidates

### User-level (personal `~/.claude/CLAUDE.md` / agent habits)

- **U1. Run the narrowest relevant test first, then the full suite before declaring done.** This keeps feedback fast and context small. The full run catches cross-test interactions [S16].
- **U2. Never "fix" a failure by adding retries, sleeps, longer timeouts, or skip/xfail without a root-cause note.** Retries mask real races, and bare sleeps are a top flakiness source: "Never use bare sleeps… use a callback or polling" [S1][S4].
- **U3. When a test fails intermittently, reproduce it with the recorded seed** (`pytest -p randomly --randomly-seed=<n>` or `--randomly-seed=last`; `vitest --sequence.seed=<n>`) before changing code [S6][S7].
- **U4. Show evidence:** paste the exact command and the pass/fail summary, not "tests pass" [S16].
- **U5. Never weaken a gate to get green.** Don't lower coverage thresholds, add `# pragma: no cover`, widen `--allow-hosts`, or delete assertions unless the user explicitly asks [S3][S10].
- **U6. Never put secrets in test fixtures, snapshots, or environment-variable files that get committed.** Use fakes. In cloud environments, use the platform's network-secret mechanism [S13][S15].

### Project-level (repo config, CLAUDE.md, CI)

- **P1. Provide one documented command per tier**, e.g. `make test` (fast/small), `make test-integration`, `make check` (lint + types + tests), and list them in CLAUDE.md. Agents cannot guess bespoke commands [S16].
- **P2. Randomize test order in every run and print the seed** (pytest-randomly is on by default once installed; Vitest `sequence.shuffle`) [S6][S7]. Order dependence is a named Google flakiness cause [S2].
- **P3. Reset all randomness per test from one seed** (pytest-randomly reseeds `random`, Faker, factory_boy and NumPy) [S6].
- **P4. Block the network in unit tests by default** (`--disable-socket --allow-unix-socket`). Opt specific tests in with `@pytest.mark.enable_socket` or `allow_hosts([...])` [S8]. This mirrors Google's small/medium boundaries [S3].
- **P5. Inject or freeze the clock.** Wrap the system clock, and consider a lint that flags direct `datetime.now()` [S4]. Use `time-machine` (Python) or `vi.useFakeTimers()`/`vi.setSystemTime()` (Vitest) [S20].
- **P6. Isolate filesystem and env.** Use `tmp_path` and `monkeypatch.setenv` (pytest); `unstubEnvs`/`unstubGlobals`/`restoreMocks` (Vitest). Build state fresh rather than relying on cleanup, and use transaction rollback for DB tests [S4].
- **P7. Enforce per-test timeouts** (pytest-timeout, e.g. 10–60 s; Vitest `testTimeout`) plus a job-level `timeout-minutes` [S9][S14].
- **P8. Strict config:** use `--strict-markers` and `--strict-config`, and set `xfail_strict = true` so a test that unexpectedly passes is flagged (pytest docs; widely used convention).
- **P9. Make dependencies hermetic and enforced.** Commit lockfiles. CI uses `uv sync --locked` / `npm ci` / `pnpm install --frozen-lockfile`. Pin the runtime version (`.python-version`, `.nvmrc`/`engines`) [S12].
- **P10. Use real dependencies in containers, not shared environments.** Use Testcontainers (ephemeral DB per session or module), or local services on localhost. Never run tests against shared staging or production [S2][S18].
- **P11. Coverage policy.** Turn on branch coverage. Set a modest global floor (`fail_under`) and a stricter diff-coverage gate on changed lines (`diff-cover --fail-under=90`). Don't treat a coverage percentage as a quality target [S3][S10][S11].
- **P12. Flaky-test policy.** Detect flaky tests automatically (Buildkite Test Engine, Trunk, or rerun-based detection). Quarantine with an owner, a ticket and an expiry date, and keep the test running. Cap the quarantine size. Delete or fix the test before the expiry [S4][S5][S19].
- **P13. Retries only in CI, only bounded, and always reported.** Put `--reruns 2` on the CI command line, not in `addopts`, so local runs show the first failure. Report "passed on rerun" as flaky, never as a clean pass [S9][S5].
- **P14. Emit JUnit XML from every runner** (`--junitxml`, Vitest `junit` reporter). Upload it with `if: ${{ !cancelled() }}`. Flaky-detection and reporting tools all consume JUnit [S5][S7].
- **P15. Parallelize safely.** Use `pytest -n auto` (xdist), with `--dist loadgroup` + `xdist_group` for tests that share a resource [S21]. Vitest/Jest sharding splits by file. Merge blob reports in a final job [S7]. Parallelism exposes shared state, so fix the shared state rather than serializing.
- **P16. Pre-commit for cheap checks only** (format, lint, secret scan). Keep the full test suite in CI. Run `pre-commit run --all-files` in CI so hooks can't be skipped (pre-commit.com).
- **P17. GitHub Actions baseline:**
  - Set top-level `permissions: contents: read` and pin third-party actions by SHA [S13].
  - Use `concurrency` with `cancel-in-progress` for PRs [S14].
  - Set `timeout-minutes` and `fail-fast: false` on test matrices.
  - Cache dependencies via setup-uv/setup-node caching.
  - Make a single aggregate job (e.g. `re-actors/alls-green`) the one *required* status check, so matrix renames don't break branch rules.

### Environment-level (cloud agent containers, devcontainers, CI runners)

- **E1. Split provisioning from project setup.** The cloud **setup script** installs system toolchains (apt, extra SDKs, `docker compose pull`), and it must stay under about 5 minutes to be cached. The repo's **SessionStart hook** installs project deps idempotently, guarded by `CLAUDE_CODE_REMOTE` [S15].
- **E2. Make the SessionStart hook idempotent and fast.** Hash the lockfile and manifest, and skip the install when they're unchanged. Never start long-running servers synchronously; use `async: true` or start them on demand [S15].
- **E3. Start services explicitly per session** (`service postgresql start`, `docker compose up -d`). Snapshot caches keep files, not processes [S15].
- **E4. Use the most restrictive network level that lets installs succeed** (Trusted, or Custom allowlist). Tests should pass with registries reachable and nothing else, which surfaces hidden network dependencies [S15].
- **E5. Fit the suite to the box.** About 4 vCPU and 16 GB means `-n 4`, not `-n 32`. Keep the default test command under the 2-minute Bash default, or set `BASH_DEFAULT_TIMEOUT_MS` [S15].
- **E6. Provide a devcontainer** so humans, CI and agents share one image. Pin the Claude Code version for reproducibility, run as non-root, and add an egress firewall if bypassing permissions. Never mount `~/.ssh` or cloud credentials [S17].
- **E7. Keep secrets out of agent-visible environment variables.** Cloud environment variables are readable by anyone who uses the environment. Use network secrets, which the agent proxy attaches outside the sandbox. In CI, use OIDC and short-lived tokens, and mask derived values [S13][S15].

## 3. Example config snippets

### pyproject.toml (pytest + coverage)
```toml
[dependency-groups]
dev = [
  "pytest>=8", "pytest-randomly", "pytest-socket", "pytest-timeout",
  "pytest-xdist", "pytest-cov", "time-machine", "diff-cover",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = [
  "-ra",                      # summary of skips/xfails/failures
  "--strict-markers",
  "--strict-config",
  "--import-mode=importlib",
  "--disable-socket",         # pytest-socket: no network by default
  "--allow-unix-socket",
]
xfail_strict = true
timeout = 60                  # pytest-timeout, per test (seconds)
junit_family = "xunit2"
markers = ["integration: needs real services (localhost / containers)"]

[tool.coverage.run]
branch = true
source = ["src"]
parallel = true               # required with xdist / subprocesses

[tool.coverage.report]
fail_under = 80               # global floor; stricter gate is diff-cover
show_missing = true
skip_covered = true
exclude_also = ["if TYPE_CHECKING:", "raise NotImplementedError"]
```
Integration tests opt in to the network with `@pytest.mark.enable_socket` (or `@pytest.mark.allow_hosts(["127.0.0.1"])`) [S8]. To reproduce a failing order, run `pytest -p randomly --randomly-seed=last` [S6].

### conftest.py (isolation helpers)
```python
import pytest

@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    # Hermetic HOME/cwd and no leaked credentials from the host/agent VM.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    for var in ("AWS_ACCESS_KEY_ID", "GITHUB_TOKEN", "DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
```

### vitest.config.ts
```ts
import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    sequence: { shuffle: { files: true, tests: true } }, // seed printed; override with --sequence.seed=N
    restoreMocks: true,
    unstubEnvs: true,
    unstubGlobals: true,
    testTimeout: 10_000,
    reporters: process.env.CI ? ['default', 'junit'] : ['default'],
    outputFile: { junit: 'reports/junit.xml' },
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov', 'cobertura'],
      thresholds: { branches: 80, lines: 80 },
    },
  },
})
```
Sharding: `vitest run --reporter=blob --shard=${i}/${n}` per job, then `vitest run --merge-reports` in a final job [S7]. Jest has the equivalent `--shard=i/n` (jestjs.io CLI).

### .github/workflows/tests.yml
```yaml
name: tests
on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.head_ref || github.run_id }}
  cancel-in-progress: true

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 15
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      # In real repos pin every action to a full commit SHA (comment the tag).
      - uses: actions/checkout@v5
        with:
          fetch-depth: 0            # diff-cover needs the base branch
      - uses: astral-sh/setup-uv@v7
        with:
          enable-cache: true
          python-version: ${{ matrix.python-version }}
      - run: uv sync --locked       # fail if uv.lock is stale
      - name: Run tests
        run: >
          uv run pytest -n auto --reruns 2
          --cov --cov-report=xml --junitxml=reports/junit.xml
      - name: Diff coverage gate
        if: github.event_name == 'pull_request'
        env:
          BASE_REF: ${{ github.base_ref }}   # untrusted input via env, not inline
        run: uv run diff-cover coverage.xml --compare-branch="origin/$BASE_REF" --fail-under=90
      - uses: actions/upload-artifact@v4
        if: ${{ !cancelled() }}
        with:
          name: junit-${{ matrix.python-version }}
          path: reports/junit.xml

  all-green:                        # the ONE required status check
    if: always()
    needs: [test]
    runs-on: ubuntu-latest
    steps:
      - uses: re-actors/alls-green@release/v1
        with:
          jobs: ${{ toJSON(needs) }}
```
`--reruns` needs `pytest-rerunfailures` in the dev group. Leave it out if the policy is "no retries". If kept, feed the JUnit file to a flaky-detection tool so reruns stay visible [S5][S9].

### Claude Code cloud: `.claude/settings.json` + `scripts/install_pkgs.sh` (adapted from [S15])
```json
{
  "hooks": {
    "SessionStart": [
      { "matcher": "startup|resume",
        "hooks": [{ "type": "command",
                    "command": "bash \"$CLAUDE_PROJECT_DIR\"/scripts/install_pkgs.sh" }] }
    ]
  }
}
```
```bash
#!/bin/bash
[ "$CLAUDE_CODE_REMOTE" = "true" ] || exit 0          # cloud only
cd "$CLAUDE_PROJECT_DIR" || exit 1
stamp=.venv/.install.sha256
if ! sha256sum --check --status "$stamp" 2>/dev/null; then
  rm -f "$stamp"
  uv sync --locked && sha256sum pyproject.toml uv.lock scripts/install_pkgs.sh > "$stamp"
fi
exit 0
```
Environment **setup script** (runs as root, cached when it finishes in under about 5 minutes), for system-level items only:
```bash
apt-get update && apt-get install -y --no-install-recommends shellcheck &
docker compose -f compose.test.yml pull &
wait
```

## 4. Tools table

| Tool | Ecosystem | Install | Purpose | Link |
|---|---|---|---|---|
| pytest-randomly | Python | `uv add --dev pytest-randomly` | Random order, per-test reseed, `--randomly-seed` | github.com/pytest-dev/pytest-randomly |
| pytest-socket | Python | `uv add --dev pytest-socket` | Block or allowlist network in tests | github.com/miketheman/pytest-socket |
| pytest-timeout | Python | `uv add --dev pytest-timeout` | Per-test timeout | pypi.org/project/pytest-timeout |
| pytest-xdist | Python | `uv add --dev pytest-xdist` | Parallel `-n auto`, `--dist loadgroup/worksteal` | pytest-xdist.readthedocs.io |
| pytest-rerunfailures | Python | `uv add --dev pytest-rerunfailures` | Bounded reruns (CI only) | pypi.org/project/pytest-rerunfailures |
| time-machine | Python | `uv add --dev time-machine` | Fast clock freezing (`travel`, fixture) | time-machine.readthedocs.io |
| coverage.py / pytest-cov | Python | `uv add --dev pytest-cov` | Branch coverage, `fail_under` | coverage.readthedocs.io |
| diff-cover | Python (any Cobertura/LCOV) | `uv add --dev diff-cover` | Coverage gate on changed lines | pypi.org/project/diff-cover |
| Testcontainers | Py/JS/Java/Go/.NET | `uv add --dev testcontainers` / `npm i -D testcontainers` | Throwaway real dependencies | testcontainers.com |
| Vitest | JS/TS | `npm i -D vitest` | Shuffle/seed, shard + blob merge, junit | vitest.dev |
| Jest | JS/TS | `npm i -D jest` | `--shard`, `--randomize`, `--seed` | jestjs.io/docs/cli |
| uv | Python | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | Lockfile, `sync --locked` | docs.astral.sh/uv |
| pre-commit | any | `uv tool install pre-commit` | Fast local hooks, CI enforcement | pre-commit.com |
| alls-green | GitHub Actions | action | One aggregate required check | github.com/re-actors/alls-green |
| Buildkite Test Engine | CI SaaS | collector | Flaky detection, quarantine, auto-recovery | buildkite.com/docs/test-engine |
| Trunk Flaky Tests | CI SaaS | JUnit upload | Flaky detection, quarantine via exit-code override | docs.trunk.io/flaky-tests |
| Dev Containers + Claude Code feature | any | `.devcontainer/devcontainer.json` | Reproducible agent env, egress firewall | code.claude.com/docs/en/devcontainer |
| Nix / devbox | any | nix installer | Fully pinned toolchains (heavier alternative to devcontainers) | nixos.org |

## 5. Anti-patterns

- **Blanket retries** (`addopts = --reruns 3`, or `retry: 3` on every job). These turn real races into silent passes and corrupt flaky-detection data [S1][S5].
- **Quarantine with no owner or expiry**, or skipping instead of quarantining. Disabled tests are "rarely revisited" [S4][S5].
- **`sleep(n)` to wait for async work.** Poll with a timeout or use callbacks [S4].
- **Tests that hit real external services** (or a shared staging DB) in the default suite [S2][S3].
- **Reading `datetime.now()`, `Math.random()`, or `os.environ` directly in code under test**, with no seam to control it [S4].
- **Order-dependent tests**, shared module-level mutable state, or reliance on cleanup instead of fresh setup [S2][S4].
- **Coverage gaming:** assertion-free tests, chasing a 100% line target, sprinkling `pragma: no cover`, or measuring coverage with large end-to-end tests [S3].
- **Running CI without lockfile enforcement** (`pip install -r` with loose pins, or `npm install`), or using `--frozen` where `--locked` is meant [S12].
- **Unpinned third-party actions, write-all `GITHUB_TOKEN`, `pull_request_target` checking out PR code, or inline `${{ github.event.* }}` in `run:`** [S13].
- **No timeouts.** A hung test burns the 6-hour job limit, or stalls an agent's tool call [S9][S15].
- **SessionStart hooks that reinstall everything on every resume, or start servers synchronously** [S15].
- **Requiring every matrix leg as a separate required check.** Renames then silently block merges or bypass gates; use an aggregate job.
- **Secrets in cloud environment variables, committed `.env` files, or test snapshots** [S15][S13].

## 6. Sources

- [S1] Google Testing Blog, "Flaky Tests at Google and How We Mitigate Them" (2016): https://testing.googleblog.com/2016/05/flaky-tests-at-google-and-how-we.html
- [S2] Google Testing Blog, "Test Flakiness – One of the main challenges of automated testing" (2020): https://testing.googleblog.com/2020/12/test-flakiness-one-of-main-challenges.html
- [S3] *Software Engineering at Google*, Ch. 11 "Testing Overview": https://abseil.io/resources/swe-book/html/ch11.html
- [S4] Martin Fowler, "Eradicating Non-Determinism in Tests": https://www.martinfowler.com/articles/nonDeterminism.html
- [S5] Trunk, "What we learned from analyzing 20.2 million CI jobs" Part 2: https://www.trunk.io/blog/what-we-learned-from-analyzing-20-2-million-ci-jobs-in-trunk-flaky-tests-part-2
- [S6] pytest-randomly README: https://github.com/pytest-dev/pytest-randomly (read via mirror https://github.com/thbde/pytest-randomly)
- [S7] Vitest docs, sequence config: https://vitest.dev/config/sequence ; Improving performance / sharding: https://v4.vitest.dev/guide/improving-performance
- [S8] pytest-socket README: https://github.com/miketheman/pytest-socket
- [S9] pydevtools handbook, "Essential pytest plugins": https://pydevtools.com/handbook/explanation/essential-pytest-plugins/
- [S10] diff-cover (PyPI): https://pypi.org/project/diff-cover/
- [S11] coverage.py configuration reference: https://coverage.readthedocs.io/en/7.13.5/config.html
- [S12] uv docs, Locking and syncing: https://docs.astral.sh/uv/concepts/projects/sync/
- [S13] GitHub Docs, Secure use reference for Actions: https://docs.github.com/en/enterprise-server@3.15/actions/reference/security/secure-use
- [S14] GitHub Docs, Control the concurrency of workflows and jobs: https://docs.github.com/en/actions/how-tos/writing-workflows/choosing-when-your-workflow-runs/control-the-concurrency-of-workflows-and-jobs
- [S15] Claude Code docs, Configure cloud environments: https://code.claude.com/docs/en/cloud-environments ; Use Claude Code in the cloud: https://code.claude.com/docs/en/claude-code-on-the-web
- [S16] Claude Code docs, Best practices: https://code.claude.com/docs/en/best-practices
- [S17] Claude Code docs, Development containers: https://code.claude.com/docs/en/devcontainer
- [S18] Testcontainers for Python guide: https://testcontainers.com/guides/getting-started-with-testcontainers-for-python/
- [S19] Buildkite Test Engine, Flaky test management: https://buildkite.com/docs/test-engine/flaky-test-management
- [S20] time-machine docs: https://time-machine.readthedocs.io/en/stable/usage.html
- [S21] pytest-xdist distribution modes: https://pytest-xdist.readthedocs.io/en/stable/distribution.html
- Also referenced: Jest CLI https://jestjs.io/docs/cli ; pre-commit https://pre-commit.com/ ; alls-green https://github.com/marketplace/actions/alls-green ; uv GitHub integration https://docs.astral.sh/uv/guides/integration/github/

## Follow-up on leads (from 01-responsible-automation-blog.md §5(c))

The Responsible Automation posts could not be fetched; the blog researcher has only their titles. So the ideas below are attributed to the post *titles* and backed by primary sources found elsewhere. During this round WebFetch was rate-limited and curl to playwright.dev and readthedocs was refused by the egress proxy. Playwright and pytest-dependency details therefore come from search results plus long-stable documentation; verify the exact flag names before shipping them in the kit.

**1. Periodic automation that detects, rather than retries.** This follows the title "How to Stamp Out Intermittent Testing Issues With Periodic Automation". An intermittent failure may be a product bug (a race or a leak), and Google's taxonomy places many flakes in the app itself [S2]. A retry in the PR gate erases that signal. A *scheduled* job that runs the same tests many times turns it into data.
- Tools for the repeated run:
  - Python: `pytest-repeat` (`--count=N`) or `pytest-flakefinder` (`--flake-finder --flake-runs=N`) [F1].
  - Vitest: `--sequence.seed` variation.
  - Playwright: `--repeat-each=N`.
- Run it from GitHub Actions `on: schedule` (cron) or `workflow_dispatch`, outside the PR gate. Use random order with logged seeds, then feed the JUnit results to a flaky-detection store.
- Meta's Probabilistic Flakiness Score models a test's chance of failing in a "good" state from ordinary CI results with a Bayesian model. Owners get a ticket when the score trends up, and persistently flaky tests are excluded from change-based testing [F2].
- The flakiness floor differs by framework: well below 1% for unit tests, and up to 10% for some end-to-end frameworks [F2]. Set thresholds per suite type, not globally.

**2. Self-healing and auto-retry: "Should Test Automation 'Just Handle It'?"** The practitioner consensus in 2025–26 writing is that self-healing locators and silent retries cut maintenance cost but can *mask regressions*. A renamed button that "heals" may be a real UX break [F3]. Rules:
- Every heal or retry must be *reported*. Playwright labels a test that fails and then passes on retry as **flaky**, not passed [F4], and the gate should treat flaky as a defect signal.
- Never auto-commit healed locators. Make them a reviewable diff.
- Where the runner supports it (Playwright `--fail-on-flaky-tests` in recent versions), use it on main-branch or nightly runs [F4].

**3. Testability seams enable speed, isolation and parallelism.** This follows "My Automated Test Script Takes 45 Minutes…" and "Parallelizing test automation? Read this first." A test that can *start from any state* via injected data can run in seconds and in parallel; one that must walk through UI prerequisites can't. Primary-source support: Fowler prefers rebuilding state fresh over relying on cleanup [S4], and SWE@G's hermetic rule says a test sets up its own environment [S3]. In practice:
- Seed through APIs, factories or database fixtures, not the UI.
- Reuse authenticated state (Playwright `storageState` setup projects) instead of logging in per test [F5].
- Give each worker its own data namespace, such as a tenant or schema per xdist worker (`worker_id` fixture) [S21].
- Ask product teams for test-only seams (endpoints, feature flags, clock injection) and file a ticket when one is missing. A missing seam is a testability bug, not a reason to write a 45-minute sequential script.

**4. Tagging slow and assist suites out of the PR gate.** This follows "Production Deploy with Every Check-In? You Gotta Go TWO Low!" and the blog's "automation assist" theme. Keep the PR gate to fast, deterministic tests. Tag everything else and run it on a schedule or post-merge:
- pytest: `@pytest.mark.slow` / `integration`, deselected with `-m "not slow"`. pytest's docs show a `--runslow` opt-in pattern in `conftest.py` [F6].
- Playwright: `--grep @slow` / `--grep-invert @slow`.
- Declare markers with `--strict-markers` (P8) so tags can't be misspelled.
- Assist scripts (data generators, crawlers, visual diffs that need human judgment) never gate merges; they produce reports.
- Rule for agents: the default `make test` must equal the PR gate. Slower tiers get separate, documented commands.

**5. Collapse cascading failures to a root cause in reports.** One broken prerequisite (login, DB connection, a missing fixture) should produce one actionable failure, not 300 red tests.
- *Fail at the prerequisite.* Use fixtures with clear errors. Session-scoped health checks fail fast with `pytest.exit()`. Use `--maxfail=N` / `-x` for local loops.
- *Skip dependents explicitly.* `pytest-dependency` (`@pytest.mark.dependency(depends=[...])`) skips tests whose prerequisite failed. In Playwright serial mode, later tests in the group are skipped after a failure [F4][F7]. Use these sparingly, because explicit dependencies reduce isolation.
- *Group by signature in reporting.* Allure "categories" classify failures by message or trace regex [F8]. Develocity failure analytics groups failures that share a stack trace [F9]. A kit script can bucket JUnit failures by normalized exception plus top frame and print the buckets first, which gives agents a short, clear failure output.

**6. Hard waits: "Automation, Hard Waits, and The Six Million Dollar Man" and "Waiting for Elements to Disappear".**
- Playwright's API docs discourage `page.waitForTimeout()`, saying tests that wait for time are inherently flaky. They recommend auto-waiting locator actions and web-first assertions such as `expect(locator).toBeHidden()` instead [F10].
- This matches Fowler's "never use bare sleeps" [S4].
- Kit candidate: a lint or PreToolUse hook that flags new `sleep(`, `time.sleep`, `waitForTimeout`, and `setTimeout`-in-tests in diffs. Allow an exception only when it carries a justification comment.

**New guideline candidates:** P18 run a scheduled repeat-run job for flake detection; P19 report healed or retried tests as flaky, never as passed; P20 keep `make test` equal to the PR gate and put slow/assist suites behind tags; P21 group failures by root-cause signature in CI output; P22 add a hard-wait lint.

**Follow-up sources**
- [F1] pytest-flakefinder: https://github.com/nipunn1313/pytest-flakefinder ; pytest-repeat: https://pypi.org/project/pytest-repeat/
- [F2] Meta Engineering, "Probabilistic flakiness: How do you test your tests?" (2020): https://engineering.fb.com/2020/12/10/developer-tools/probabilistic-flakiness/
- [F3] T-Plan, "Self-healing test automation: benefits, pitfalls and how to avoid masked regressions": https://www.t-plan.com/guides/self-healing-test-automation-guide/ ; BugBug, "Self-healing test automation: hype & reality": https://bugbug.io/blog/test-automation/self-healing-test-automation/
- [F4] Playwright docs, Test retries: https://playwright.dev/docs/test-retries
- [F5] Playwright docs, Authentication (setup projects, storageState): https://playwright.dev/docs/auth
- [F6] pytest docs, How to mark test functions: https://docs.pytest.org/en/stable/how-to/mark.html ; pytest examples, "Control skipping of tests according to command line option": https://docs.pytest.org/en/stable/example/simple.html
- [F7] pytest-dependency: https://pytest-dependency.readthedocs.io/
- [F8] Allure Report, Categories: https://allurereport.org/docs/categories/
- [F9] Gradle Develocity, Failure Analytics: https://gradle.com/develocity/product/failure-analytics/
- [F10] Playwright API, `page.waitForTimeout` (discouraged): https://playwright.dev/docs/api/class-page ; Checkly, "Why you should never use page.waitForTimeout()": https://www.checklyhq.com/blog/never-use-page-waitfortimeout
