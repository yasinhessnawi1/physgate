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

#: The scripted matrix of the ablation switches: its own gate and its own CI job, since its
#: rows drive the real loop on real git and would leave the tests job little headroom. The
#: tests gate leaves out exactly this file, so the two gates together run every test once.
MATRIX=tests/unit/orchestrator/test_every_combination_of_the_ablation_switches_runs_or_is_refused_before_it_starts.py

gate_tests() {
  echo "== tests =="
  local rc=0
  uv run pytest -q -n auto --dist loadgroup --ignore="$MATRIX" || rc=$?
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

gate_matrix() {
  echo "== ablation matrix =="
  local rc=0
  [ -f "$MATRIX" ] || fail "ablation matrix — $MATRIX is not there"
  uv run pytest -q -n auto "$MATRIX" || rc=$?
  if [ "$rc" -eq 5 ]; then
    fail "ablation matrix — nothing ran"
  fi
  [ "$rc" -eq 0 ] || fail "ablation matrix"
}

gate_scoring() {
  # The evaluation's scorers, in an environment of their own: their numerical libraries
  # must never reach the harness's environment, where pint would pick numpy up and the
  # physics gate's unit handling would change (pyproject.toml, the evaluation group).
  echo "== scoring tests (evaluation environment) =="
  local rc=0 targets=(tests/scoring)
  # CI runs the scoring tests in shards of whole files: PHYSGATE_SCORING_SHARD=INDEX/COUNT
  # names one (scripts/scoring_shard.py deals the files and proves the deal complete). Unset,
  # every file runs, as always.
  if [ -n "${PHYSGATE_SCORING_SHARD:-}" ]; then
    uv run python scripts/scoring_shard.py VERIFY "${PHYSGATE_SCORING_SHARD#*/}" || fail "scoring shards"
    targets=($(uv run python scripts/scoring_shard.py FILES "${PHYSGATE_SCORING_SHARD%/*}" "${PHYSGATE_SCORING_SHARD#*/}")) \
      || fail "scoring shard"
  fi
  UV_PROJECT_ENVIRONMENT=.venv-evaluation uv run --frozen --group evaluation \
    pytest -q -n auto "${targets[@]}" || rc=$?
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

# No argument runs every gate, in this order, as always. CI names one gate or a few per job
# (tests, matrix, scoring, types, lint, ui, ui-unit, ui-browser), so the gates run in parallel jobs
# with the same bodies as here.
gates=("$@")
[ "${#gates[@]}" -gt 0 ] || gates=(tests matrix scoring types lint ui)
for gate in "${gates[@]}"; do
  case "$gate" in
    tests) gate_tests ;;
    matrix) gate_matrix ;;
    scoring) gate_scoring ;;
    types) gate_types ;;
    lint) gate_lint ;;
    ui) gate_ui ;;
    ui-unit) ./scripts/check-ui.sh unit || fail "ui (see above)" ;;
    ui-browser) ./scripts/check-ui.sh browser || fail "ui (see above)" ;;
    *) fail "unknown gate '$gate'" ;;
  esac
done

echo
echo "All gates passed."
