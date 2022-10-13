#!/bin/bash
set -euo pipefail
TEST_DIR=/tmp/test.nudebomb
mkdir -p "$TEST_DIR"
cp -a tests/test_files/test5.mkv "$TEST_DIR"
./run.sh "$@" "$TEST_DIR"
