#!/usr/bin/env bash
#
# Tests, then types, then lint. Stops at the first failure and names it.
#
# This is shell rather than Python on purpose. A Python entry point would have
# to live inside the very environment whose health it reports, so it could not
# run in the one case that matters most: when that environment is broken. If it
# outgrows this size, it becomes Python and the type checker's scope grows with
# it in the same change.
#
# CI runs this file and nothing else, so that "green locally" and "green in CI"
# cannot come apart.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

fail() {
  echo
  echo "FAILED: $1"
  exit 1
}

gate_tests() {
  echo "== tests =="
  local rc=0
  uv run pytest -q || rc=$?
  # Exit code 5 is "nothing ran". It cannot tell an empty collection apart from
  # every test having been deselected by the marker filter, so this does not
  # claim to know which it was. Both are failures: a suite that sees nothing
  # reports green while proving nothing, which is how a pipeline runs zero
  # tests for weeks without anyone noticing.
  if [ "$rc" -eq 5 ]; then
    fail "tests — nothing ran (collected nothing, or the marker filter deselected everything)"
  fi
  [ "$rc" -eq 0 ] || fail "tests"
}

gate_types() {
  echo "== types =="
  uv run mypy --strict src tests || fail "types"
}

gate_lint() {
  echo "== lint and format =="
  uv run ruff check . || fail "lint"
  uv run ruff format --check . || fail "format"
}

gate_tests
gate_types
gate_lint

echo
echo "All gates passed."
