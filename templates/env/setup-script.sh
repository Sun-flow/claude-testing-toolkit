#!/usr/bin/env bash
# Cloud environment setup script (paste into the environment's settings).
# Runs as root before Claude starts; cached when it finishes in about 5 minutes.
# System-level tools only. Project dependencies belong in the repo's SessionStart hook.
set -e
apt-get update -qq
apt-get install -y -qq --no-install-recommends jq >/dev/null
# Uncomment what your tests need:
# service postgresql start
# docker compose -f compose.test.yml pull
