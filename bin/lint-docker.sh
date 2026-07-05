#!/usr/bin/env bash
# Lint checks for docker
set -euxo pipefail

for tool in hadolint dockerfmt; do
  if ! command -v "$tool" >/dev/null; then
    echo "$tool not installed; skipping docker lint"
    exit 0
  fi
done

mapfile -t dockerfiles < <(find . -type f -name '*Dockerfile' -print -quit)
if [ ${#dockerfiles[@]} -gt 0 ]; then
  hadolint "${dockerfiles[@]}"
  dockerfmt --check "${dockerfiles[@]}"
fi
