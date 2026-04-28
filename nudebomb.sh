#!/usr/bin/env bash
# Run nudebomb in development
set -euo pipefail
uv run ./nudebomb.py "$@"
