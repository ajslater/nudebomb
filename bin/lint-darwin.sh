#!/usr/bin/env bash
# Lint shell scripts when the tools are installed
set -euxo pipefail

for tool in shellcheck shellharden shfmt; do
  if ! command -v "$tool" >/dev/null; then
    echo "$tool not installed; skipping shell lint"
    exit 0
  fi
done

bin/lint-sh.sh
