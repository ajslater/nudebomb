#!/bin/bash
# Run nudebomb in development
set -euo pipefail
poetry run ./run.py "$@"
