# 06 — Claude ecosystem packages for testing: install, activate, invoke

Researched 2026-11-12. Primary sources: code.claude.com docs (raw `.md` pages), `anthropics/claude-plugins-official` `marketplace.json` (316 plugins at time of reading), and the upstream READMEs of each package. Items marked **[unverified]** were not confirmed against the primary source.

---

## 1) Key findings

1. **One marketplace covers almost everything the user already uses.** `claude-plugins-official` (added automatically on the first interactive session) now lists `superpowers`, `ralph-loop`, `context7`, `playwright`, `chrome-devtools-mcp`, `pr-review-toolkit`, `code-review`, `security-guidance`, `hookify`, `claude-md-management`, `claude-code-setup`, the `*-lsp` language-server plugins, plus vendor quality gates (`sonarqube`, `semgrep`, `coderabbit`). A team can enable the whole starter set from one committed `enabledPlugins` block.
2. **Rules are advisory and hooks are enforced.** The memory docs say CLAUDE.md and rules "are treated as context, not enforced configuration. To block an action regardless of Claude's judgment, use a PreToolUse hook." The test-integrity rule should be backed by a PreToolUse hook (protect tests) and a Stop hook (tests must pass).
3. **Hooks have grown.** There are now 30+ events and five handler types (`command`, `http`, `mcp_tool`, `prompt`, `agent`). There is an `if:` permission-pattern filter per handler, and `onFailure: "block"` (v2.1.295+) for fail-closed policy hooks. Exit 1 does **not** block; only exit 2 or JSON `decision`/`permissionDecision` does.
4. **Stop hooks have built-in loop protection.** The input has `stop_hook_active` and `last_assistant_message`, and there is a cap of 8 consecutive continuations (`CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`). The new built-in `/goal <condition>` command is a session-scoped, model-evaluated Stop hook. It is a lighter alternative to Ralph Loop for "keep going until tests pass".
5. **Commands were merged into skills.** `.claude/commands/x.md` and `.claude/skills/x/SKILL.md` both create `/x`. Skills add `allowed-tools`, `disable-model-invocation`, `context: fork`, `paths:` globs, and `` !`cmd` `` injection, so a `/run-tests` skill can pre-inject `git diff` and run forked.
6. **`.claude/rules/*.md` with `paths:` frontmatter is the right place for test conventions.** A rule with `paths: ["**/*.test.ts", "tests/**"]` loads only when Claude touches test files. User-level `~/.claude/rules/` also exists.
7. **CI:** `anthropics/claude-code-action@v1` takes `prompt` (which can be `/skill` or `/plugin:skill`), `claude_args`, `settings`, `plugin_marketplaces` and `plugins`. Headless `claude -p` should use `--bare` in CI for reproducibility; it skips all local hooks, plugins and CLAUDE.md unless you pass them back in with flags.
8. **Browser testing:** Microsoft now recommends **Playwright CLI + skills** (`@playwright/cli`) over Playwright MCP for coding agents, because the CLI uses fewer tokens. Playwright ≥1.56 ships **Test Agents** (planner/generator/healer) that install as Claude subagents via `npx playwright init-agents --loop=claude`.
9. **Mutation and coverage are thin in the ecosystem.** No Anthropic plugin does mutation testing. `wdm0006/mutmut-mcp` (Python, mutmut 3.x) is the most credible MCP server found. For JS/Java, call Stryker or PIT from a skill or hook rather than looking for an MCP server.
10. **Cloud caveat:** cloud sessions and project threads do **not** load locally installed plugins or a repo's `.claude/settings.json` hooks/permissions (with exceptions). The environment level needs SessionStart/setup-script or managed settings.

---

## 2) Mechanism reference (exact current syntax)

### 2.1 Memory and rules
| Scope | Path |
|---|---|
| Managed | Linux `/etc/claude-code/CLAUDE.md`; macOS `/Library/Application Support/ClaudeCode/CLAUDE.md`; Windows `C:\Program Files\ClaudeCode\CLAUDE.md` |
| User | `~/.claude/CLAUDE.md`, plus `~/.claude/rules/*.md` (loaded before project rules) |
| Project | `./CLAUDE.md` or `./.claude/CLAUDE.md`, plus `.claude/rules/**/*.md` (recursive) |
| Local | `./CLAUDE.local.md` (gitignore it yourself) |

- All files are concatenated, not overridden. Files in subdirectories load on demand.
- Imports use `@path/to/file.md` (relative to the importing file) or `@~/.claude/x.md`. The maximum depth is **4 hops**. External imports show an approval dialog the first time.
- Path-scoped rule:
  ```markdown
  ---
  paths:
    - "**/*.{test,spec}.{ts,tsx,js}"
    - "tests/**"
  ---
  # Test rules
  - Never weaken or delete an assertion to make a test pass.
  ```
- `/memory` lists the loaded files. `/init` bootstraps a CLAUDE.md. Keep each file under about 200 lines. Auto memory lives in `~/.claude/projects/<project>/memory/MEMORY.md` (the first 200 lines or 25KB load).

### 2.2 Settings scopes and permissions
- **Precedence (highest first):** managed → `--settings` CLI → `.claude/settings.local.json` → `.claude/settings.json` → `~/.claude/settings.json`. Arrays such as `permissions.allow` **merge** across scopes.
- **Managed:** `managed-settings.json` in a system directory, MDM, or server-managed settings from the claude.ai console. Only server-managed settings reach cloud sessions.
- **Trust:** project `permissions.allow`, `extraKnownMarketplaces` and most `env` values wait for workspace trust. `deny` and `ask` apply immediately.
- **Example:**
```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "allow": ["Bash(npm run test *)", "Bash(pytest *)"],
    "ask":   ["Edit(/tests/**)"],
    "deny":  ["Read(./.env)", "Read(./.env.*)", "Edit(/tests/fixtures/golden/**)"]
  }
}
```
- Read/Edit rules use gitignore syntax:
  - `/path` is relative to the settings source (the primary working dir for project settings).
  - `//abs` is an absolute path, and `~/` is home.
  - A bare name matches at any depth.
  - `Bash(cmd *)`: the space before `*` matters.
- **Caveat:** an `Edit(...)` deny does not stop `Bash(sed -i ...)`. Use a hook to protect tests (2.3).

### 2.3 Hooks
**Where hooks live:** `hooks` key in any settings file, a plugin's `hooks/hooks.json`, or skill/subagent frontmatter. View them with `/hooks` (read-only).

**Shape:** `event → [ { matcher, hooks: [ {type, command, args?, if?, timeout?, onFailure?, async?} ] } ]`.

**Matchers:**
- `"*"`, `""` or omitted matches everything.
- A value made only of letters, digits, `_`, `-`, `|` and `,` is an exact name or a list (`Edit|Write`).
- Anything else is an unanchored JS regex (`mcp__playwright__.*`).
- `UserPromptSubmit` and `Stop` ignore matchers.
- SessionStart matchers are `startup|resume|clear|compact|fork`.
- SubagentStop matches on the agent type.

**Events most relevant to testing:**
- `SessionStart`: stdout becomes context; can write `CLAUDE_ENV_FILE`.
- `UserPromptSubmit`
- `PreToolUse`: can block.
- `PostToolUse`: cannot block; exit 2 shows stderr to Claude.
- `PostToolBatch`
- `Stop` and `SubagentStop`: can block.
- `TaskCompleted`: can block.
- `PreCompact`
- `SessionEnd`

**Input (stdin JSON):**
- `session_id`, `cwd`, `permission_mode` and `hook_event_name` on every event.
- Tool events add `tool_name` and `tool_input`. Edit and Write carry `tool_input.file_path`.
- Stop adds `stop_hook_active`, `last_assistant_message` and `background_tasks`.

**Exit codes:**
- `0`: JSON on stdout is parsed if it is a single object.
- `2`: blocks; stderr is the reason.
- Anything else: non-blocking error.

**JSON output:**
- PreToolUse: `{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny|allow|ask|defer","permissionDecisionReason":"..."}}`
- Stop and PostToolUse: `{"decision":"block","reason":"..."}`
- Non-error nudge: `hookSpecificOutput.additionalContext` (capped at 10k chars).
- Global: `{"continue":false,"stopReason":"..."}`

**Placeholders:** `${CLAUDE_PROJECT_DIR}` and `${CLAUDE_PLUGIN_ROOT}`. Prefer exec form (`command` + `args`).

**Example A: block modifications to existing test files** (new test files are allowed; the override is a marker file the human creates). Save as `.claude/hooks/protect-tests.sh` and `chmod +x` it:
```bash
#!/usr/bin/env bash
# PreToolUse guard: Claude may ADD tests but not rewrite existing ones.
input=$(cat)
f=$(jq -r '.tool_input.file_path // .tool_input.notebook_path // empty' <<<"$input")
[ -z "$f" ] && exit 0
proj="${CLAUDE_PROJECT_DIR:-$(jq -r .cwd <<<"$input")}"
[ -f "$proj/.claude/allow-test-edits" ] && exit 0          # human opt-in
if [[ "$f" =~ (^|/)(tests?|__tests__|spec)/ || "$f" =~ \.(test|spec)\.[jt]sx?$ || "$f" =~ (^|/)test_[^/]+\.py$ || "$f" =~ _test\.(py|go)$ ]]; then
  if [ -e "$f" ]; then
    echo "Blocked: $f is an existing test. Fix the code under test, not the test. If the test itself is wrong, explain why and ask the user to create .claude/allow-test-edits." >&2
    exit 2
  fi
fi
exit 0
```
```json
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [ { "type": "command",
                     "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/protect-tests.sh",
                     "onFailure": "block", "timeout": 10 } ] }
    ]
  }
}
```
(`MultiEdit` is kept in the matcher for older versions; the current tools reference documents Edit, Write and NotebookEdit **[MultiEdit status unverified]**. `onFailure` needs v2.1.295 or later; older versions ignore it.)

**Example B: run tests on Stop and refuse to finish while they fail.** Save as `.claude/hooks/tests-on-stop.sh`:
```bash
#!/usr/bin/env bash
input=$(cat)
# Loop guard: if we already forced one continuation, let Claude stop (the 8-cap also applies)
[ "$(jq -r '.stop_hook_active' <<<"$input")" = "true" ] && exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
# Skip when nothing changed since HEAD
git diff --quiet HEAD -- 2>/dev/null && [ -z "$(git ls-files --others --exclude-standard)" ] && exit 0
out=$(${TEST_CMD:-npm test --silent} 2>&1); rc=$?
if [ $rc -ne 0 ]; then
  jq -n --arg r "Test suite failed (exit $rc). Fix the code, do not weaken tests. Last output:
$(tail -n 60 <<<"$out")" '{decision:"block", reason:$r}'
fi
exit 0
```
```json
{ "hooks": { "Stop": [ { "hooks": [ { "type": "command",
  "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/tests-on-stop.sh", "timeout": 600 } ] } ] } }
```
Variant: a fast PostToolUse hook on `Edit|Write` that runs only the related test file and exits 2, which feeds the failure back to Claude without blocking.

### 2.4 Skills (and slash commands)
**Locations:**
- Personal: `~/.claude/skills/<name>/SKILL.md`
- Project: `.claude/skills/<name>/SKILL.md`
- Plugin: `<plugin>/skills/<name>/SKILL.md`, invoked as `/plugin:name`
- Enterprise: the managed directory

On a name clash, enterprise beats personal, which beats project. `.claude/commands/<name>.md` still works and is equivalent.

**Frontmatter (all optional):**
- `name`, `description`, `when_to_use`
- `argument-hint`, `arguments`
- `disable-model-invocation: true`: manual `/name` only
- `user-invocable: false`: Claude only
- `allowed-tools`, `disallowed-tools`
- `model`, `effort`
- `context: fork` with `agent: <subagent>` and `background`
- `hooks`
- `paths`: globs that gate auto-loading
- `shell`

**Body:** `$ARGUMENTS`, `$0`/`$1`, `${CLAUDE_SKILL_DIR}`, and `` !`git diff HEAD` `` for pre-injected shell output.

Example for the user's kit:
```yaml
---
name: run-tests
description: Run the project's test suite (or tests related to the current diff) and report failures with root-cause hypotheses. Use before claiming work is done.
argument-hint: "[path-or-pattern]"
allowed-tools: Bash(npm test *), Bash(pytest *), Read, Grep
context: fork
---
Changed files: !`git diff --name-only HEAD`
Run tests for $ARGUMENTS (default: tests related to the changed files, then the full suite)...
```

### 2.5 Subagents
**Locations:** `.claude/agents/*.md` (project), `~/.claude/agents/*.md` (user), a plugin's `agents/`, or `--agents '{json}'`.

**Frontmatter:**
- Required: `name`, `description`
- `tools` / `disallowedTools`
- `model`: `sonnet|opus|haiku|inherit|<id>`
- `permissionMode`, `maxTurns`
- `skills`: preloaded
- `mcpServers`, `hooks`, `memory`
- `isolation: worktree`
- `effort`, `background`

**Invocation:** automatic, via the description ("use proactively"); `@agent-<name>`; or `claude --agent <name>`. A good fit is a read-only **test-reviewer** agent (`tools: Read, Grep, Glob, Bash(npm test *)`) that audits new tests for tautologies and mocks-of-the-SUT.

### 2.6 Plugins and marketplaces
**In a session:**
- `/plugin` opens Discover, Installed and Marketplaces.
- `/plugin marketplace add owner/repo[#ref]`. Git URLs, `./local-dir` and `https://…/marketplace.json` also work.
- `/plugin install <name>@<marketplace>` opens details; you then pick the user, project or local scope.
- `/reload-plugins`

**From the shell:**
- `claude plugin install <name>@<mkt> [--scope user|project|local]`
- `claude plugin marketplace add anthropics/claude-plugins-official` (needed on fresh CI or containers)
- `claude plugin list`, `enable`, `disable`, `uninstall`, `update`
- `claude plugin details <name>` shows the per-turn token cost.

**Settings:**
```json
{
  "extraKnownMarketplaces": {
    "my-kit": { "source": { "source": "github", "repo": "me/testing-kit" } }
  },
  "enabledPlugins": {
    "superpowers@claude-plugins-official": true,
    "pr-review-toolkit@claude-plugins-official": true,
    "testing-kit@my-kit": true
  }
}
```
- Committing `enabledPlugins` does not download the plugin. Each collaborator runs `claude plugin install … --scope project` once, or accepts the trust prompt.
- The exact `extraKnownMarketplaces` `source` object shape **[unverified in this pass; check the settings reference]**.
- Plugin layout: `.claude-plugin/plugin.json` (only `name` is required) plus `skills/`, `commands/`, `agents/`, `hooks/hooks.json`, `.mcp.json` and `.lsp.json` at the plugin root.
- A marketplace is `.claude-plugin/marketplace.json`: `{"name","owner":{"name"},"plugins":[{"name","source":"./plugins/x","description"}]}`.
- Auto-update is on by default only for official marketplaces.

### 2.7 MCP servers
- **Commands:**
  - `claude mcp add --transport http <name> <url> [--header "Authorization: Bearer …"]`
  - `claude mcp add [--scope local|project|user] [--env K=V] <name> -- <cmd> [args…]`
  - `claude mcp add-json <name> '<json>'`
  - `claude mcp list|get|remove`, and `/mcp` in a session.
- **Scopes:**
  - local (the default): stored in `~/.claude.json`, applies to this project.
  - project: `.mcp.json` at the repo root, committed, and needs per-user approval.
  - user: stored in `~/.claude.json`.
- **`.mcp.json` format:** `{"mcpServers":{"name":{"type":"http","url":"…"}}}` or `{"command":"npx","args":[…]}`. It supports `${VAR}` and `${VAR:-default}`.
- **Headless runs:** `claude -p` loads project `.mcp.json` servers without asking. Use `--strict-mcp-config` and `--mcp-config` in CI.

### 2.8 Headless and CI
**`claude -p`:**
- `claude -p "Run the test suite and fix failures" --allowedTools "Bash(npm test *),Read,Edit"`
- Useful flags: `--output-format text|json|stream-json`, `--json-schema '<schema>'` (result in `.structured_output`), `--permission-mode acceptEdits|auto|dontAsk`, `--permission-prompts none`, `--max-turns`, `--append-system-prompt`, `--continue/--resume <id>`.
- `--bare` skips CLAUDE.md, hooks, plugins and MCP. Re-add them with `--settings`, `--mcp-config`, `--plugin-dir`, `--agents` and `--append-system-prompt-file`. It requires `ANTHROPIC_API_KEY`.
- Exit codes: 0 on success, non-zero on failure.
- The `system/init` event lists `plugin_errors` and `mcp_server_errors`, so CI can fail when the kit didn't load.

**GitHub Action:** `uses: anthropics/claude-code-action@v1`.
- Inputs: `anthropic_api_key` or `claude_code_oauth_token`, `prompt` (text, `/skill`, or `/plugin:skill`), `claude_args` (e.g. `--max-turns 10 --allowedTools "Bash(npm test *)"`), `settings` (JSON or path), `plugin_marketplaces` (newline-separated git URLs) and `plugins` (`name@marketplace`).
- With no `prompt` it runs in interactive mode, triggered by `@claude`. With `prompt` it runs in automation mode.
- Quick setup: `/install-github-app`.
- Official example: `plugins: "code-review@claude-code-plugins"` with `prompt: "/code-review:code-review --comment owner/repo/pull/N"`.

---

## 3) Package catalogue

| Package | Testing value | Install (verified) | Invoke | Maintainer / maturity |
|---|---|---|---|---|
| **superpowers** | TDD red-green-refactor, systematic debugging, verification-before-completion, code review, worktree with clean test baseline | `/plugin install superpowers@claude-plugins-official` (or `/plugin marketplace add obra/superpowers-marketplace` → `superpowers@superpowers-marketplace`) | Auto-triggered skills; e.g. `/superpowers:test-driven-development` | Jesse Vincent / Prime Radiant; MIT; v7.0.2; very active, multi-harness |
| **ralph-loop** | Stop-hook loop: repeats the prompt until a completion promise (e.g. "all tests green") | `/plugin install ralph-loop@claude-plugins-official` | `/ralph-loop "<prompt>" --completion-promise "DONE" --max-iterations N`; `/cancel-ralph` | Anthropic |
| **/goal** (built-in) | Model-judged "continue until condition" | none | `/goal all tests pass and lint is clean`; `/goal clear` | Anthropic, built-in |
| **pr-review-toolkit** | 6 agents incl. **pr-test-analyzer** (behavioural coverage, critical gaps), silent-failure-hunter, type-design-analyzer, code-reviewer, code-simplifier, comment-analyzer | `/plugin install pr-review-toolkit@claude-plugins-official` | Natural language ("Review test coverage for this PR") → agent | Anthropic |
| **code-review** | 4 parallel review agents, confidence ≥80 filter; CI-ready | `/plugin install code-review@claude-plugins-official` | `/code-review [--comment]` (namespaced `/code-review:code-review`) | Anthropic |
| **security-guidance** | Edit-time pattern warnings, LLM diff review on Stop, agentic review on `git commit` | `/plugin install security-guidance@claude-plugins-official` | Automatic hooks; needs Python 3.8+, CC ≥2.1.144 | Anthropic, v2.0.19 |
| **hookify** | Write hook rules as markdown (`.claude/hookify.*.local.md`, `action: block`) | `/plugin install hookify@claude-plugins-official` | `/hookify <behaviour>`, `/hookify:list`, `/hookify:configure` | Anthropic |
| **feature-dev**, **code-simplifier**, **claude-md-management**, **claude-code-setup**, **skill-creator**, **plugin-dev** | Workflow / meta (CLAUDE.md audits, automation recommendations, skill evals) | `…@claude-plugins-official` | Skills / agents | Anthropic |
| **\*-lsp** (typescript-lsp, pyright-lsp, gopls-lsp, rust-analyzer-lsp, jdtls-lsp …) | Type errors and diagnostics right after edits; catches breakage before tests run | `/plugin install pyright-lsp@claude-plugins-official` (needs language server binary) | Automatic | Anthropic |
| **playwright** (MCP) | E2E browser driving; `--caps=testing` adds `browser_verify_*` and `browser_generate_locator` | Plugin: `/plugin install playwright@claude-plugins-official`; or `claude mcp add playwright npx @playwright/mcp@latest` | Tools `mcp__playwright__browser_*` | Microsoft; mature |
| **Playwright CLI + skills** | Token-cheaper browser automation for coding agents (Microsoft's recommendation over MCP) | `npm i -g @playwright/cli@latest && playwright-cli install --skills` | Skill auto-loads / `playwright-cli …` via Bash | Microsoft |
| **Playwright Test Agents** | planner → Markdown test plan; generator → `.spec.ts`; healer → runs and repairs failing tests | `npx playwright init-agents --loop=claude` (Playwright ≥1.56; re-run on upgrade) | Subagents (generated into `.claude/agents/` **[path unverified]**) | Microsoft |
| **chrome-devtools-mcp** | Console and network inspection, perf traces/LCP, memory leaks, a11y; Puppeteer automation | `/plugin install chrome-devtools-mcp@claude-plugins-official`, or `/plugin marketplace add ChromeDevTools/chrome-devtools-mcp` → `chrome-devtools-mcp@chrome-devtools-plugins`, or `claude mcp add chrome-devtools --scope user npx chrome-devtools-mcp@latest` | MCP tools + skills (`chrome-devtools`, `a11y-debugging`, `memory-leak-debugging`, …) | Google Chrome team |
| **webapp-testing** skill | Python Playwright scripts + `scripts/with_server.py` server lifecycle | `/plugin marketplace add anthropics/skills` → `/plugin install example-skills@anthropic-agent-skills` (or copy `skills/webapp-testing` into `.claude/skills/`) | Auto by description | Anthropic (example quality) |
| **context7** | Current, version-specific framework/test-library docs (fewer hallucinated APIs, e.g. Vitest, pytest fixtures) | `/plugin install context7@claude-plugins-official`, or `claude mcp add --transport http context7 https://mcp.context7.com/mcp` | Tools `resolve-library-id`, `query-docs`; optional `CONTEXT7_API_KEY` | Upstash |
| **mutmut-mcp** | Python mutation testing: run, list survivors, rank by materiality, rerun mutants | `claude mcp add mutmut -- uvx --from git+https://github.com/wdm0006/mutmut-mcp mutmut-mcp` (command derived from its README JSON) | MCP tools | Community (single maintainer); self-tests with mutation CI |
| **sonarqube** / **semgrep** / **coderabbit** | Static quality/security gates in the loop (sonarqube uses PostToolUse hooks) | `…@claude-plugins-official` | Hooks / MCP / skills | Vendors; need accounts/tokens |
| **wshobson/agents** (`claude-code-workflows`) | `unit-testing`, `tdd-workflows`, `debugging-toolkit`, `api-testing-observability`, `performance-testing-review` | `/plugin marketplace add wshobson/agents` → `/plugin install unit-testing@claude-code-workflows` | Agents / commands | Community, 94 plugins; quality varies **[content not reviewed]** |

### Per-package notes
- **Superpowers.**
  - The `test-driven-development` skill "deletes code written before tests" and includes a testing anti-patterns reference.
  - `verification-before-completion` is the soft-gate counterpart to the Stop hook.
  - `using-git-worktrees` verifies a clean test baseline before work starts.
  - It is complementary to, not a replacement for, the enforcing hooks.
  - Opt out of the brainstorming companion telemetry with `SUPERPOWERS_DISABLE_TELEMETRY=1`.
  - Related plugins in its marketplace: `superpowers-chrome`, `superpowers-lab`, `episodic-memory`.
- **Ralph Loop.**
  - Implemented as a plugin Stop hook (`hooks/stop-hook.sh`) with state in `.claude/ralph-loop.local.md`. It is session-scoped by `session_id`.
  - Always pass `--max-iterations`; the default is unlimited.
  - Make the completion promise require evidence (test output), or it can be gamed.
  - Combining it with your own Stop test hook means two Stop hooks fire. Both must agree before Claude stops, which is fine, but watch the 8-continuation cap.
- **pr-review-toolkit vs code-review.**
  - Use `pr-test-analyzer` locally to judge test quality.
  - Use `code-review` in CI (the GitHub Action example uses the demo-marketplace copy `code-review@claude-code-plugins`; the official copy is the same plugin).
- **Playwright MCP vs CLI.**
  - The MCP server is better for exploratory and self-healing loops with persistent browser state.
  - The CLI is better inside large-codebase sessions.
  - Run parallel clients with `--isolated`. Use `--headless` in CI.
- **LSP plugins.** They need the language server binary installed (e.g. `pyright`, `typescript-language-server`) **[per-plugin prerequisites unverified]**.

---

## 4) Recommended starter set per level

**User level (`~/.claude/`), personal and portable:**
- `~/.claude/CLAUDE.md`: a 10–20 line testing creed that `@imports` `~/.claude/rules/testing.md` (no `paths:`, so it always loads).
- Plugins, user scope: `superpowers`, `context7`, `ralph-loop`, `pr-review-toolkit`, plus the `*-lsp` plugin for each language you use.
- Skill: `~/.claude/skills/run-tests/` (generic auto-detect of the runner). Agent: `~/.claude/agents/test-reviewer.md` (read-only).
- Settings: `permissions.allow` for the common test commands. No blocking hooks here; enforcement belongs to the project.

**Project level (committed in the repo; the kit's main payload):**
- `CLAUDE.md` holds the exact test, lint and coverage commands. `.claude/rules/testing.md` has `paths:` for test globs (conventions, no assertion weakening, no mocking of the unit under test).
- `.claude/settings.json`:
  - `hooks`: protect-tests (PreToolUse), related tests on PostToolUse (fast), and tests-on-stop (Stop).
  - `permissions`: allow test commands; deny editing golden fixtures and snapshots.
  - `enabledPlugins` plus `extraKnownMarketplaces` for the toolkit repo. Add `pr-review-toolkit`, and `playwright` or `chrome-devtools-mcp` for web apps.
- `.claude/skills/run-tests`, `/write-tests`, and `/mutation-check` (calls Stryker, mutmut or PIT via Bash, or mutmut-mcp).
- `.mcp.json` only for servers that every contributor needs, with `${VAR}` for secrets.
- `CLAUDE.local.md` and `.claude/settings.local.json` stay gitignored for personal overrides.

**Environment level (CI, cloud, managed):**
- CI: `claude --bare -p "/run-tests" --settings .claude/settings.json --mcp-config .mcp.json --permission-mode dontAsk --allowedTools "Bash(npm test *),Read,Edit" --output-format json`, then gate on the exit code and `plugin_errors`/`mcp_server_errors`.
- The GitHub Action uses `plugin_marketplaces` + `plugins` to load the kit, `prompt: "/testing-kit:run-tests"`, and `claude_args: --max-turns …`.
- Cloud or container setup script: `claude plugin marketplace add anthropics/claude-plugins-official && claude plugin install superpowers@claude-plugins-official --scope project`. Alternatively, a SessionStart hook that installs skills and returns `{"hookSpecificOutput":{"hookEventName":"SessionStart","reloadSkills":true}}`.
- Org: managed settings with the protect-tests hook and `onFailure: "block"`, plus `allowManagedPermissionRulesOnly` if needed, and a managed `CLAUDE.md` for non-negotiable test rules.

---

## 5) Caveats
- **Version drift.** The docs reference CLI versions up to v2.1.3xx. `onFailure`, `/goal`, `--permission-prompts`, `reloadSkills` and the `if:` handler field are recent, so pin a minimum Claude Code version in the kit README.
- **Hooks run arbitrary shell with user credentials.** In `-p` mode, project hooks and `.mcp.json` run **without** a trust prompt. Review third-party plugins, which can ship hooks.
- **Stop hooks that run full suites can be slow and expensive.** Scope them to changed files, set `timeout`, and respect `stop_hook_active`.
- **Test protection can be bypassed via Bash** (`sed`, `cat >`). Add a Bash PreToolUse check for redirects into test paths if you need strictness, and treat the hook as a speed bump, not a sandbox.
- **Plugin context cost.** Each enabled plugin adds tokens to every turn; check with `claude plugin details`. Superpowers and many MCP tool schemas are not free.
- **Cloud sessions don't load locally installed plugins** or the repo's settings hooks in project threads. Use environment setup or managed settings.
- **Community marketplaces** (`wshobson/agents`, Superpowers marketplace) have auto-update **off** by default. Anthropic does not review third-party marketplaces.
- **Unverified items:** the exact generated paths of `playwright init-agents --loop=claude`; the `extraKnownMarketplaces` source object shape; MultiEdit's current status; the contents of community testing plugins.

---

## 6) Sources
- Hooks reference: https://code.claude.com/docs/en/hooks (Stop input/decision control, exit codes, matchers)
- Memory and rules: https://code.claude.com/docs/en/memory
- Settings: https://code.claude.com/docs/en/settings · Permissions: https://code.claude.com/docs/en/permissions
- Skills: https://code.claude.com/docs/en/skills · Subagents: https://code.claude.com/docs/en/sub-agents
- Plugins: https://code.claude.com/docs/en/discover-plugins · https://code.claude.com/docs/en/plugins/anthropic-marketplaces · https://code.claude.com/docs/en/plugins/manifest-reference · https://code.claude.com/docs/en/plugins/create-marketplace
- MCP: https://code.claude.com/docs/en/mcp · Headless: https://code.claude.com/docs/en/headless · /goal: https://code.claude.com/docs/en/goal
- GitHub Action: https://code.claude.com/docs/en/github-actions · https://github.com/anthropics/claude-code-action
- Official marketplace catalog: https://github.com/anthropics/claude-plugins-official (`.claude-plugin/marketplace.json`; plugin READMEs for ralph-loop, pr-review-toolkit, code-review, security-guidance, hookify, context7, playwright `.mcp.json`)
- Superpowers: https://github.com/obra/superpowers · https://github.com/obra/superpowers-marketplace
- anthropics/skills (webapp-testing): https://github.com/anthropics/skills/tree/main/skills/webapp-testing
- Playwright MCP: https://github.com/microsoft/playwright-mcp · Playwright CLI: https://github.com/microsoft/playwright-cli · Test Agents: https://playwright.dev/docs/test-agents (source `docs/src/test-agents-js.md`)
- Chrome DevTools MCP: https://github.com/ChromeDevTools/chrome-devtools-mcp
- mutmut-mcp: https://github.com/wdm0006/mutmut-mcp
- wshobson/agents: https://github.com/wshobson/agents
- Community Stop-hook write-ups (context only): https://codingwithroby.substack.com/p/the-stop-hook-that-wont-let-claude · https://claudefa.st/blog/tools/hooks/stop-hook-task-enforcement

---

## Follow-up on leads (from 01-responsible-automation-blog §5(e))

### F1. Independent "spec-only" test-writer subagent (no access to `src/`)
What the docs allow (sub-agents.md):
- **`tools` / `disallowedTools`** work at whole-tool level only. `Read(src/**)` in `disallowedTools` removes **all** of Read.
- **`permissions.deny`** rules apply to the whole session (main thread and every subagent), so they can't wall off `src/` for one agent only.
- What does work per agent is a **`hooks:` block in the agent's frontmatter**: a PreToolUse hook scoped to that subagent. Plugin-shipped agents ignore `hooks`, `mcpServers` and `permissionMode`, so ship this agent as a file in `.claude/agents/`, not inside a plugin.
- Alternative: a project-level PreToolUse hook that branches on `agent_type`. The hook input carries `agent_type`, equal to the agent's `name`, inside subagents.
- **Different model:** `model: opus|sonnet|haiku|<full id>` (or `inherit`).
- **Keep implementation-flavoured memory out:** `omitClaudeMd: true`.
- **Isolate the writes:** `isolation: worktree`.
- **Ticket oracle:** an inline `mcpServers:` entry (needs folder trust).
```markdown
---
name: spec-test-writer
description: Writes tests from the ticket/spec ONLY, never from the implementation. Use when new behaviour needs independent tests.
tools: Read, Grep, Glob, Write, Edit, Bash
model: opus            # differ from the implementer's model
omitClaudeMd: true
hooks:
  PreToolUse:
    - matcher: "Read|Grep|Glob|Edit|Write|Bash"
      hooks:
        - type: command
          command: "${CLAUDE_PROJECT_DIR}/.claude/hooks/no-src-access.sh"
---
Derive expected behaviour from the ticket, docs/specs/ and public interface stubs in docs/api/.
List assumptions first. Never infer expected values by running the code.
```
`no-src-access.sh` checks `.tool_input.file_path // .path // .pattern // .command` against `(^|/)(src|lib|app)/` and exits 2. It must also block Grep/Glob calls with **no `path`**, because they default to the cwd and would search `src/`. Bash is the weakest point (`cat src/x`, `python -c`), so either drop Bash from `tools` and let the parent run the tests, or limit it to the test runner.

Residual leaks the hook cannot stop:
- the parent's delegation prompt (instruct the parent to pass only the ticket ID and spec paths);
- stack traces from test runs;
- the interface stubs the agent needs in order to compile.

### F2. Assumptions check
- **Skill** `.claude/skills/assumptions/SKILL.md`: pulls the ticket via MCP and writes `## Assumptions` (each line: claim, source, how verified, status) to `.claude/assumptions/<ticket>.md`. Preload it into the test-writer with `skills: [assumptions]`.
- **Gate** (verified syntax): a PreToolUse hook with `"matcher": "Bash", "if": "Bash(gh pr create *)"`. The script exits 2 unless `tool_input.command` contains `Assumptions` or the assumptions file exists for the branch.
- **Softer gate:** a Stop hook that returns `hookSpecificOutput.additionalContext` ("test files changed but no assumptions list"). This continues the turn without showing a hook error.

### F3. Run-report hook (tested / not tested / anomalies)
- PostToolUse on `Bash`. The script matches `tool_input.command` against the runner regex (`pytest|vitest|jest|npm (run )?test|go test|mvn .*test|gradle.*test`). The `if:` field takes only one pattern, so do the matching in the script.
- Make runners emit JUnit XML in a fixed place (`pytest --junitxml=.reports/junit.xml`, `vitest --reporter=junit --outputFile=.reports/junit.xml`, `jest-junit`). The hook parses it and returns:
```json
{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"RUN REPORT: 212 run, 209 passed, 0 failed | NOT TESTED: 3 skipped (test_payments_refund: 'flaky'), 1 xfail | ANOMALIES: 0 tests collected in tests/e2e; test_sync took 31s (p95 2s); 2 tests passed on retry"}}
```
- `additionalContext` is capped at 10k characters and appears next to the tool result. Use exit 2 with stderr only when Claude must react, for example when zero tests were collected. Keep the summary in factual phrasing, because imperative text can trip prompt-injection defences (hooks doc).

### F4. Guard hooks: hard sleeps, blanket retries, copied expectations
- **Sleeps and retries:** PreToolUse on `Edit|Write`, applied to test paths only, scanning `tool_input.new_string // tool_input.content`.
  - Sleep patterns to deny: `time\.sleep\(|Thread\.sleep\(|\bsleep [0-9]|waitForTimeout\(|cy\.wait\([0-9]|setTimeout\(.*resolve`.
  - Retry patterns to deny: `retries\s*[:=]\s*[1-9]|jest\.retryTimes|@pytest\.mark\.flaky|--reruns|@Retry|\.retry\(`.
  - Return exit 2 with a hint to use condition-based waits (Superpowers' systematic-debugging includes "condition-based-waiting").
  - Pair it with a `Bash` PreToolUse check that blocks `--reruns`, `--retries` and `--repeat-each` on test commands.
- **No-code alternative:** hookify rules (`event: file`, `conditions: [{field: new_text, operator: regex_match, pattern: …}]`, `action: block`).
- **"Expected value copied from a run"** can't be detected reliably by regex. Treat it as a review concern: pr-review-toolkit's `pr-test-analyzer`, or a custom reviewer prompt. A heuristic hook can warn when a test edit follows, within the same turn, a Bash run whose output contains the newly asserted literal. Implementing that needs transcript parsing **[not built/tested]**.

### F5. Ticket systems as the oracle source (MCP)
| System | Install (verified from vendor/official config) |
|---|---|
| Jira / Confluence | `/plugin install atlassian@claude-plugins-official`, or `claude mcp add --transport http atlassian https://mcp.atlassian.com/v2/mcp`, then `/mcp` to OAuth (v2 is now recommended over v1) |
| Linear | `/plugin install linear@claude-plugins-official`, or `claude mcp add --transport http linear https://mcp.linear.app/mcp` |
| GitHub Issues | `/plugin install github@claude-plugins-official` (http `https://api.githubcopilot.com/mcp/`, header `Authorization: Bearer ${GITHUB_PERSONAL_ACCESS_TOKEN}`) |
| GitLab | `/plugin install gitlab@claude-plugins-official` (http `https://gitlab.com/api/v4/mcp`) |
| Azure DevOps | Microsoft recommends the remote server `https://mcp.dev.azure.com/{organization}` (preview), e.g. `claude mcp add --transport http ado https://mcp.dev.azure.com/<org>`; the local `microsoft/azure-devops-mcp` (npx, stdio) remains supported. Claude-specific steps are in its docs/GETTINGSTARTED.md **[CLI line inferred, not copied]** |
| Rally | No official MCP found **[unverified]** |

To give only the test-writer the ticket tools, use `disallowedTools: mcp__atlassian` on other agents, or inline `mcpServers` on the test-writer. Ticket text is untrusted input, so treat it as data in prompts.

### F6. Previously unverified items, now resolved
1. **`npx playwright init-agents --loop=claude`** (source `packages/playwright/src/agents/generateAgents.ts`) writes `.claude/agents/<agent>.md` for the planner, generator and healer. It also writes `.mcp.json` with server `playwright-test`: `npx playwright run-test-mcp-server`. Note that this overwrites `.mcp.json`. Optional `.claude/prompts/`. Plans go to `specs/`, tests to `tests/`, and the seed is `tests/seed.spec.ts`.
2. **`extraKnownMarketplaces` shape is confirmed:** `{"acme-tools": {"source": {"source": "github", "repo": "acme-corp/plugins"}}}`. Other source types are listed under "Allowed source types" in settings-reference.
3. **MultiEdit:** it is absent from the current tools reference and from the hooks doc. Matching `Edit|Write|NotebookEdit` is enough; keeping `MultiEdit` in the matcher is harmless for older versions.
4. **Community testing plugins** (`wshobson/agents`, MIT): `unit-testing` v1.2.2 is essentially a persona agent (`unit-testing-test-automator`, `model: sonnet`). `tdd-workflows` v1.3.2 ships a `/tdd-cycle` command with strict ordered red-green-refactor steps. They are useful as prompt references, but none of them adds enforcement.

Sources added: code.claude.com/docs/en/sub-agents · /tools-reference · /settings-reference; github.com/microsoft/playwright (generateAgents.ts, docs/src/test-agents-js.md); github.com/atlassian/atlassian-mcp-server; github.com/microsoft/azure-devops-mcp; claude-plugins-official `external_plugins/{linear,github,gitlab}/.mcp.json`; github.com/wshobson/agents.
