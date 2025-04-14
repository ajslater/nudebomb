#!/bin/bash
# Run nudebomb in development
set -euo pipefail
uv run ./nudebomb.py "$@"
