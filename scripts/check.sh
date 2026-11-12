#!/usr/bin/env bash
#
# Tests, then types, then lint, then the operator UI's gates. Stops at the first failure
# and names it.
#
# The tests run in parallel, one worker per CPU this process may use. Locally the UI's gates
# run only when something changed since the merge base can reach them (scripts/affected.py
# says what and why); CI runs them always, and PHYSGATE_CHECK_UI=always runs them here.
# scripts/check-fast.sh is a quicker loop over the changed files for use between runs of this
# one, never in place of it.
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
  uv run pytest -q -n auto --dist loadgroup || rc=$?
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

gate_scoring() {
  # The evaluation's scorers, in an environment of their own: their numerical libraries
  # must never reach the harness's environment, where pint would pick numpy up and the
  # physics gate's unit handling would change (pyproject.toml, the evaluation group).
  echo "== scoring tests (evaluation environment) =="
  local rc=0
  UV_PROJECT_ENVIRONMENT=.venv-evaluation uv run --frozen --group evaluation \
    pytest -q -n auto tests/scoring || rc=$?
  if [ "$rc" -eq 5 ]; then
    fail "scoring tests — nothing ran"
  fi
  [ "$rc" -eq 0 ] || fail "scoring tests"
}

gate_types() {
  echo "== types =="
  uv run mypy --strict src tests scripts || fail "types"
}

gate_lint() {
  echo "== lint and format =="
  uv run ruff check . || fail "lint"
  uv run ruff format --check . || fail "format"
}

gate_ui() {
  # The operator UI's own gates, first-red, in a script of their own. Skipped locally only on
  # a definite no: the question's own failure runs them, like a yes.
  if [ -z "${CI:-}" ] && [ "${PHYSGATE_CHECK_UI:-}" != "always" ]; then
    local rc=0 why
    why=$(uv run python scripts/affected.py ui) || rc=$?
    if [ "$rc" -eq 3 ]; then
      echo "== ui: skipped, $why (CI always runs it; PHYSGATE_CHECK_UI=always runs it here) =="
      return 0
    fi
    echo "== ui: runs, ${why:-the change could not be placed} =="
  fi
  ./scripts/check-ui.sh || fail "ui (see above)"
}

gate_tests
gate_scoring
gate_types
gate_lint
gate_ui

echo
echo "All gates passed."
