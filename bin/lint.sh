#!/usr/bin/env bash
# Lint checks
set -euxo pipefail

uv run --group lint mbake validate Makefile cfg/*.mk

# Javascript, JSON, Markdown, YAML #####
bun run lint

bin/lint-darwin.sh

uv run --group lint bin/roman.py -i .prettierignore .
