#!/usr/bin/env bash
# Lint checks for ci
set -euxo pipefail

if ! command -v actionlint >/dev/null; then
  echo "actionlint not installed; skipping workflow lint"
  exit 0
fi

if [ -f .github/workflows/ci.yml ]; then
  actionlint .github/workflows/ci.yml
fi
