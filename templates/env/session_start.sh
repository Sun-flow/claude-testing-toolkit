#!/usr/bin/env bash
# Testing kit SessionStart hook: make a cloud session ready to test.
# Runs on startup/resume. Idempotent and fast when nothing changed.
# Local sessions: does nothing (set TESTING_KIT_SESSION_START=1 to run it locally too).
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || [ "${TESTING_KIT_SESSION_START:-}" = "1" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" || exit 0
cfg=.claude/testing-kit.json
py=$(command -v python3 || command -v python)

# 1. Project dependencies, skipped when the lockfiles are unchanged.
stamp=.claude/testing-kit/.state/deps.sha256
mkdir -p "$(dirname "$stamp")"
lockfiles=$(ls uv.lock poetry.lock requirements*.txt pyproject.toml package-lock.json pnpm-lock.yaml yarn.lock go.sum Cargo.lock 2>/dev/null)
if [ -n "$lockfiles" ] && ! sha256sum --check --status "$stamp" 2>/dev/null; then
  setup=$("$py" -c "import json;print(json.load(open('$cfg'))['commands'].get('setup',''))" 2>/dev/null)
  if [ -n "$setup" ]; then
    if bash -c "$setup" >/tmp/testing-kit-setup.log 2>&1; then
      sha256sum $lockfiles > "$stamp"
    else
      echo "Testing kit: dependency setup failed (\`$setup\`); see /tmp/testing-kit-setup.log"
    fi
  fi
fi

# 2. Plugins the repo expects (cloud sessions don't have your local plugins).
if command -v claude >/dev/null 2>&1 && [ -f .claude/settings.json ]; then
  for p in $("$py" -c "import json;print(' '.join(k for k,v in json.load(open('.claude/settings.json')).get('enabledPlugins',{}).items() if v))" 2>/dev/null); do
    claude plugin install "$p" --scope project >/dev/null 2>&1 || echo "Testing kit: could not install plugin $p"
  done
fi

# 3. Tell Claude how to test (stdout becomes session context).
fast=$("$py" -c "import json;print(json.load(open('$cfg'))['commands'].get('fast',''))" 2>/dev/null)
[ -n "$fast" ] && echo "Testing kit: fast test tier is \`$fast\` (rules in .claude/rules/testing.md)."
exit 0
