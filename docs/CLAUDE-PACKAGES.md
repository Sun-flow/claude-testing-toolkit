# Claude Packages for Testing: Install, Activate, Call

> **Version** 0.1 (draft for review) · **Date** 2026-11-12 · Evidence: [R6] (`research/06-claude-packages.md`, including its follow-up section).
> Install commands were checked against each package's source on 2026-11-12. Items marked **[unverified]** were not. Pin a minimum Claude Code version in the kit README: several features below (`onFailure`, `/goal`, the `if:` hook field) are recent.

## How the pieces fit

| Mechanism | What it is | Where | Activated by |
|---|---|---|---|
| Memory / rules | Text Claude reads | `~/.claude/CLAUDE.md`, `./CLAUDE.md`, `.claude/rules/*.md` (with `paths:` globs) | Always (or when a matching file is touched) |
| Hooks | Scripts that run on events and can block | `hooks` in any `settings.json`, plugin `hooks/hooks.json`, agent/skill frontmatter | Automatically on the event |
| Skills (= slash commands) | Instructions + optional tool limits, `/name` | `~/.claude/skills/`, `.claude/skills/`, plugins | `/name`, or automatically by description |
| Subagents | Separate context, own tools/model/hooks | `~/.claude/agents/`, `.claude/agents/` | Automatically by description, `@agent-name`, or `claude --agent name` |
| Plugins | Bundles of the above + MCP | Marketplaces | `/plugin install name@marketplace`, or `enabledPlugins` in settings |
| MCP servers | External tools (browser, tickets, mutation) | `claude mcp add`, `.mcp.json` | Tools appear as `mcp__server__tool` |

**First-time setup on any machine:** `claude plugin marketplace add anthropics/claude-plugins-official` (added automatically in the first interactive session, needed explicitly in CI and fresh containers).

---

## Tier 1: recommended for every repo

| Package | What it gives testing | Install | Call it |
|---|---|---|---|
| **This kit** (`testing-kit`) | Integrity hooks, spec-only test writer, reviewer, `/write-tests`, `/run-tests`, `/mutation-check`, `/test-review` | `python kit/install.py --project .` (files must live in the repo; see `kit/README.md`) | Hooks fire automatically; skills by `/name` |
| **superpowers** | TDD red-green-refactor skill (deletes code written before tests), systematic debugging, verification-before-completion, code review | `/plugin install superpowers@claude-plugins-official` | Auto-triggers; or `/superpowers:test-driven-development` |
| **pr-review-toolkit** | `pr-test-analyzer` agent (behavioural coverage, critical gaps), `silent-failure-hunter`, code reviewer | `/plugin install pr-review-toolkit@claude-plugins-official` | Ask: "Review test coverage for this PR" |
| **context7** | Current docs for test libraries (pytest fixtures, Vitest APIs), fewer hallucinated APIs | `/plugin install context7@claude-plugins-official` | Automatic; tools `resolve-library-id`, `query-docs` |
| **Language-server plugin** (`pyright-lsp`, `typescript-lsp`, `gopls-lsp`, `rust-analyzer-lsp`, …) | Type errors right after an edit, before tests run | `/plugin install pyright-lsp@claude-plugins-official` (needs the server binary installed) | Automatic |

## Tier 2: by situation

| Package | Use when | Install | Call it |
|---|---|---|---|
| **ralph-loop** | Long autonomous "until green" work with a verifiable finish line | `/plugin install ralph-loop@claude-plugins-official` | `/ralph-loop "<task>" --completion-promise "DONE" --max-iterations 10` (always set the cap); `/cancel-ralph` |
| **`/goal`** (built-in) | Lighter "keep going until tests pass" for one session | none | `/goal all tests pass and lint is clean`; `/goal clear` |
| **code-review** | Multi-agent review in CI or locally | `/plugin install code-review@claude-plugins-official` | `/code-review [--comment]` |
| **hookify** | Writing simple block/warn rules without code | `/plugin install hookify@claude-plugins-official` | `/hookify <behaviour>`, `/hookify:list` |
| **security-guidance** | Security warnings on edit and review on commit | `/plugin install security-guidance@claude-plugins-official` | Automatic hooks |
| **Hypothesis `/hypothesis` command** | Agent-written property-based tests, from the Hypothesis team | See the Hypothesis repo's Claude Code command instructions **[install path unverified]** | `/hypothesis` |
| **mutmut-mcp** (community) | Python mutation testing via tools: run, list survivors, rank | `claude mcp add mutmut -- uvx --from git+https://github.com/wdm0006/mutmut-mcp mutmut-mcp` | MCP tools; the kit's `/mutation-check` works without it |

## Tier 3: web and UI testing

| Package | Use when | Install | Call it |
|---|---|---|---|
| **Playwright CLI + skills** | Browser automation inside coding sessions (Microsoft's recommendation over MCP: fewer tokens) | `npm i -g @playwright/cli@latest && playwright-cli install --skills` | Skill auto-loads; `playwright-cli …` |
| **Playwright Test Agents** | Planner → plan in `specs/`, generator → `tests/*.spec.ts`, healer → repairs failing tests | `npx playwright init-agents --loop=claude` (Playwright ≥ 1.56). **Warning:** writes `.claude/agents/*.md` and **overwrites `.mcp.json`**; back it up first | Subagents by name |
| **playwright** (MCP plugin) | Exploratory, stateful browser sessions | `/plugin install playwright@claude-plugins-official` | `mcp__playwright__browser_*` |
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
| Azure DevOps | `claude mcp add --transport http ado https://mcp.dev.azure.com/<org>` **[CLI line inferred]** |
| Rally | none found |

## Tier 5: LLM / agent evals (not Claude packages, but what the kit's eval layer calls)

| Tool | For | Install |
|---|---|---|
| Pydantic AI `TestModel` / `FunctionModel` | Fake models in unit tests | part of `pydantic-ai` |
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

Committing `enabledPlugins` doesn't download anything. Each person runs `claude plugin install <name>@claude-plugins-official --scope project` once (or accepts the prompt). In cloud sessions, the kit's SessionStart script does it.

To ship the kit itself as a marketplace from `Sun-flow/claude-toolkit`:

```json
{ "extraKnownMarketplaces": { "sun-flow-toolkit": { "source": { "source": "github", "repo": "Sun-flow/claude-toolkit" } } } }
```

**Limit:** agents shipped inside a plugin ignore `hooks`, `mcpServers` and `permissionMode` in their frontmatter [R6 follow-up F1]. So the `spec-test-writer` agent and the integrity hooks must be installed as repo files, not only as a plugin. That is why the kit has an installer.

## In CI

```yaml
- uses: anthropics/claude-code-action@v1   # pin to a SHA in real repos
  with:
    anthropic_api_key: ${{ secrets.ANTHROPIC_API_KEY }}
    prompt: "/test-review"
    claude_args: "--max-turns 15 --settings .claude/settings.json"
```

Or headless: `claude --bare -p "/run-tests" --settings .claude/settings.json --output-format json`. `--bare` skips CLAUDE.md, hooks and plugins unless passed back in. Fail the job when the init event lists `plugin_errors` or `mcp_server_errors` [R6 §2.8].

## Cautions

- Every enabled plugin adds tokens to every turn. Check with `claude plugin details <name>`.
- Hooks and `.mcp.json` run arbitrary commands with your credentials, and in `-p` mode they run without a trust prompt. Review third-party plugins before enabling them.
- Community marketplaces (e.g. `wshobson/agents`) don't auto-update and aren't reviewed by Anthropic. Their testing plugins are prompts only and enforce nothing.
- Two Stop hooks (Ralph Loop + the kit's test hook) both have to agree before Claude stops. That's fine, but Claude Code stops forcing continuations after 8 in a row.
