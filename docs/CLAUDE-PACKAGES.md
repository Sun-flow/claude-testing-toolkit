# Claude Packages for Testing: Install, Activate, Call

> **Version** 0.2 (after review round 1) · **Date** 2026-11-12 · Evidence: [R6] (`research/06-claude-packages.md`, including its follow-up section).
> Install commands were checked against each package's source on 2026-11-12. Items marked **[unverified]** were not. Pin a minimum Claude Code version in the kit README: several features below (`onFailure`, `/goal`, the `if:` hook field) are recent.

## How the pieces fit

| Mechanism | What it is | Where | Activated by |
|---|---|---|---|
| Memory / rules | Text Claude reads | `~/.claude/CLAUDE.md`, `./CLAUDE.md`, `.claude/rules/*.md` (with `paths:` globs) | Always (or when a matching file is touched) |
| Hooks | Scripts that run on events and can block | `hooks` in any `settings.json`, plugin `hooks/hooks.json`, agent/skill frontmatter | Automatically on the event |
| Skills (= slash commands) | Instructions + optional tool limits, `/name` | `~/.claude/skills/`, `.claude/skills/`, plugins | `/name`, or automatically by description |
| Subagents | Separate context, own tools/model/hooks | `~/.claude/agents/`, `.claude/agents/` | Automatically by description, `@agent-name`, or `claude --agent name` |
| Plugins | Bundles of the above + MCP | Marketplaces | `/plugin install name@marketplace`, or `enabledPlugins` in settings |
| MCP servers | External tools (browser, tickets, mutation) | `claude mcp add`, `.mcp.json` | Tools appear as `mcp__<server>__<tool>`, or `mcp__plugin_<plugin>_<server>__<tool>` when a plugin bundles the server |

**First-time setup on any machine:** `claude plugin marketplace add anthropics/claude-plugins-official` (added automatically in the first interactive session, needed explicitly in CI and fresh containers).

---

## When to use what (testing)

| Task | Low tier | Medium / high tier |
|---|---|---|
| Write tests for a change | `superpowers:test-driven-development` (your current route) or `/write-tests` | `/write-tests`, which delegates the tests to the `spec-test-writer` agent |
| Run tests and report | `/run-tests` | `/run-tests` |
| Check the tests can fail | — | `/mutation-check` |
| Review test changes | `@agent-test-reviewer` | `/test-review` (multi-agent) |
| Keep going until green | `/goal all tests pass` (stops on a `BLOCKED:` report) | Ralph Loop with `--max-iterations`, and a completion promise that requires test output |
| Library docs | Context7 | Context7 |

Use one route per task. The kit's hooks apply whichever route you pick.

## By repo type

| Repo | Install | Add |
|---|---|---|
| Static website | kit `minimal` | Playwright CLI + skills (Tier 3) for a smoke and accessibility pass |
| Game | kit `minimal` | Hypothesis `/hypothesis` for property tests of the logic core |
| Python bot / automation | kit `standard` | `pyright-lsp`; mutmut-mcp if you want mutation runs as tools |
| Library or service other code depends on | kit `strict --ci` | `pr-review-toolkit`; Schemathesis if it has an OpenAPI schema |
| LLM / agent code | kit `standard --ci` | Tier 5 eval libraries; promptfoo red-team on a schedule |

## Tier 1: recommended for every repo

| Package | What it gives testing | Install | Call it |
|---|---|---|---|
| **This kit** (`testing-kit`) | Integrity hooks, CI gates, spec-only test writer, reviewer, `/write-tests`, `/run-tests`, `/mutation-check`, `/test-review` | `python kit/install.py --project .` (see `kit/README.md`; hooks and agents must be repo files, so it isn't a plugin) | Hooks fire automatically; skills by `/name` |
| **Language-server plugin** (`pyright-lsp`, `typescript-lsp`, `gopls-lsp`, `rust-analyzer-lsp`, …) | Type errors right after an edit, before tests run | `/plugin install pyright-lsp@claude-plugins-official` (needs the server binary installed **[prerequisites unverified per plugin]**) | Automatic |

You already use **Superpowers** (TDD, systematic debugging, verification-before-completion), **Ralph Loop** and **Context7**; keep them. They are advice and loops; the kit's hooks and CI are the enforcement.

## Tier 2: by situation

| Package | Use when | Install | Call it |
|---|---|---|---|
| **pr-review-toolkit** | A second opinion on test coverage (`pr-test-analyzer`) and silent failures | `/plugin install pr-review-toolkit@claude-plugins-official` | Ask: "Review test coverage for this PR" |
| **ralph-loop** | Long autonomous "until green" work with a verifiable finish line | `/plugin install ralph-loop@claude-plugins-official` | `/ralph-loop "<task>" --completion-promise "DONE" --max-iterations 10` (always set the cap); `/cancel-ralph` |
| **`/goal`** (built-in) | Lighter "keep going until tests pass" for one session | none | `/goal all tests pass and lint is clean`; `/goal clear` |
| **`/code-review`** (built-in) | General multi-agent code review | none (the `code-review` plugin's own command is `/code-review:code-review`) | `/code-review` |
| **hookify** | Writing simple block/warn rules without code | `/plugin install hookify@claude-plugins-official` | `/hookify <behaviour>`, `/hookify:list` |
| **security-guidance** | Security warnings on edit and review on commit | `/plugin install security-guidance@claude-plugins-official` | Automatic hooks |
| **Hypothesis `/hypothesis` command** | Agent-written property-based tests, from the Hypothesis team | Copy the command file from the Hypothesis repo into `.claude/commands/` (or `~/.claude/commands/`) | `/hypothesis` |
| **TDD Guard / Probity** (community) | Hook-enforced test-first: blocks implementation without a failing test | See its README **[install line not re-verified]**. Overlaps the kit's hooks: pick one for test-first enforcement | Automatic hooks |
| **mutmut-mcp** (community) | Python mutation testing as tools: run, list survivors, rank | `claude mcp add mutmut -- uvx --from git+https://github.com/wdm0006/mutmut-mcp mutmut-mcp` **[derived from its README]** | MCP tools; `/mutation-check` works without it |

## Tier 3: web and UI testing

| Package | Use when | Install | Call it |
|---|---|---|---|
| **Playwright CLI + skills** | Browser automation inside coding sessions (Microsoft's recommendation over MCP: fewer tokens) | `npm i -g @playwright/cli@latest && playwright-cli install --skills` | Skill auto-loads; `playwright-cli …` |
| **Playwright Test Agents** | Planner → plan in `specs/`, generator → `tests/*.spec.ts`, healer → repairs failing tests | `npx playwright init-agents --loop=claude` (Playwright ≥ 1.56). **Warning:** writes `.claude/agents/*.md` and **overwrites `.mcp.json`**; back it up first | Subagents by name |
| **playwright** (MCP plugin) | Exploratory, stateful browser sessions | `/plugin install playwright@claude-plugins-official` | `mcp__plugin_playwright_playwright__browser_*` |
| **chrome-devtools-mcp** | Console/network inspection, performance traces, accessibility | `/plugin install chrome-devtools-mcp@claude-plugins-official` | MCP tools + skills |
| **webapp-testing** skill | Python Playwright scripts with a server lifecycle helper | `/plugin marketplace add anthropics/skills` → `/plugin install example-skills@anthropic-agent-skills` | Automatic by description |

Healed locators from the healer agent are a reviewable diff, never an auto-commit (guidelines TG-18, [R4 P19]).

## Tier 4: requirements as the oracle (ticket MCPs)

Use these with the `spec-test-writer` agent so tests come from the ticket, not the code. Ticket text is untrusted input: treat it as data.

| System | Install |
|---|---|
| Jira / Confluence | `/plugin install atlassian@claude-plugins-official`, then `/mcp` to sign in |
| Linear | `/plugin install linear@claude-plugins-official` |
| GitHub Issues | `/plugin install github@claude-plugins-official` (needs `GITHUB_PERSONAL_ACCESS_TOKEN`) |
| GitLab | `/plugin install gitlab@claude-plugins-official` |
| Azure DevOps | `claude mcp add --transport http ado https://mcp.dev.azure.com/<org>` (add `--scope project` to share it) |
| Rally | none found |

## Tier 5: non-Claude eval libraries (for LLM / agent code)

| Tool | For | Install |
|---|---|---|
| Pydantic AI `TestModel` / `FunctionModel` | Fake models in unit tests; `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` blocks real calls | part of `pydantic-ai` |
| vcrpy / pytest-recording | Record/replay of provider traffic | `pip install pytest-recording` |
| promptfoo | Prompt/agent evals, red-teaming, CI caching | `npx promptfoo@latest init` |
| Inspect (UK AISI) | Sandboxed agent evals, epochs, clustered stderr | `pip install inspect-ai` |
| DeepEval | pytest-style LLM metrics | `pip install deepeval` |

Details and more options: [R2 §4].

---

## Activating in a project

Commit this in `.claude/settings.json` (the kit installer merges it for you):

```json
{
  "enabledPlugins": {
    "superpowers@claude-plugins-official": true,
    "pr-review-toolkit@claude-plugins-official": true,
    "context7@claude-plugins-official": true
  }
}
```

Committing `enabledPlugins` doesn't download anything. Each person runs `claude plugin install <name>@claude-plugins-official --scope project` once (or accepts the prompt). Cloud sessions and project threads don't use your local plugins: enable plugins on your claude.ai account or in Project settings.

If this repo is later published as a plugin marketplace, it needs a `.claude-plugin/marketplace.json` first; then:

```json
{ "extraKnownMarketplaces": { "claude-testing-toolkit": { "source": { "source": "github", "repo": "Sun-flow/claude-testing-toolkit" } } } }
```

**Limit:** agents shipped inside a plugin ignore `hooks`, `mcpServers` and `permissionMode` in their frontmatter [R6 follow-up F1]. So the `spec-test-writer` agent and the integrity hooks must be installed as repo files, not only as a plugin. That is why the kit has an installer.

## In CI

```yaml
- uses: anthropics/claude-code-action@v1   # pin to a SHA in real repos
  with:
    anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
    plugin_marketplaces: "https://github.com/anthropics/claude-plugins-official.git"
    plugins: "pr-review-toolkit@claude-plugins-official"
    prompt: "/test-review origin/main"
    claude_args: "--max-turns 15"
```

Or headless in the checkout: `claude -p "/run-tests" --output-format stream-json --verbose`. Don't use `--bare` for kit tasks: it skips hooks (even with `--settings`) and skill discovery. To fail when a plugin or MCP server didn't load, read the first `system/init` event in the stream [R6 §2.8; round1-MECHANICS MECH-4, MECH-11].

## Cautions

- Every enabled plugin adds tokens to every turn. Check with `claude plugin details <name>`.
- Hooks and `.mcp.json` run arbitrary commands with your credentials, and in `-p` mode they run without a trust prompt. Review third-party plugins before enabling them.
- Community marketplaces (e.g. `wshobson/agents`) don't auto-update and aren't reviewed by Anthropic. Their testing plugins are prompts only and enforce nothing.
- Two Stop hooks (Ralph Loop + the kit's test hook) both have to agree before Claude stops. That's fine, but Claude Code stops forcing continuations after 8 in a row.
