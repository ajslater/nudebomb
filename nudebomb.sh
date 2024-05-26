#!/bin/bash
# Run nudebomb in development
set -euo pipefail
poetry run ./nudebomb.py "$@"
