#!/usr/bin/env bash
#
# The quick loop between full checks: the tests a change can reach, then types, then lint on
# the changed files, then the UI's quick gates if the UI changed. Stops at the first failure
# and names it.
#
# This replaces nothing. scripts/check.sh, every gate over everything, is still what must be
# green before a STOP report and before a pull request, and it is what CI runs. This loop
# selects by the import graph (scripts/affected.py), so a test that reaches a change some
# other way, through a subprocess or a file it reads, can be missed here and is caught there.
#
# "Changed" is everything that differs from the merge base with origin/master (or with
# PHYSGATE_CHECK_BASE): commits on the branch, uncommitted edits and untracked files.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

fail() {
  echo
  echo "FAILED: $1"
  echo "(fast loop; scripts/check.sh is still required before a STOP report or a PR)"
  exit 1
}

changed=$(uv run python scripts/affected.py changed) || fail "could not work out what changed"
if [ -z "$changed" ]; then
  echo "Nothing changed since the merge base; nothing to check."
  exit 0
fi
echo "== changed since the merge base =="
echo "$changed" | sed 's/^/  /'

echo "== tests =="
tests=$(uv run python scripts/affected.py tests) || fail "could not select the tests"
if [ -z "$tests" ]; then
  echo "  no test reaches the change"
else
  # The whole suite is selected as the word "tests"; a list is one file per line.
  # shellcheck disable=SC2086
  set -- $tests
  if [ "$tests" = tests ]; then echo "  the whole suite"; else echo "  $# test files"; fi
  rc=0
  uv run pytest -q -n auto --dist loadgroup "$@" || rc=$?
  [ "$rc" -eq 5 ] && fail "tests — nothing ran"
  [ "$rc" -eq 0 ] || fail "tests"
fi

echo "== types =="
# All of it, not only the changed files: the checker's cache makes the whole tree as quick as
# a part once it is warm (measured: a second run after a one-file change takes well under a
# second), and a change breaks the types of the files that import it as well as its own.
uv run mypy --strict src tests scripts || fail "types"

echo "== lint and format =="
python_changed=()
while IFS= read -r file; do
  case "$file" in
    *.py) [ -f "$file" ] && python_changed+=("$file") ;;
  esac
done <<< "$changed"
if [ "${#python_changed[@]}" -eq 0 ]; then
  echo "  no changed Python file"
else
  uv run ruff check "${python_changed[@]}" || fail "lint"
  uv run ruff format --check "${python_changed[@]}" || fail "format"
fi

ui_changed=()
while IFS= read -r file; do
  case "$file" in
    ui/*) [ -f "$file" ] && ui_changed+=("${file#ui/}") ;;
  esac
done <<< "$changed"
if [ "${#ui_changed[@]}" -gt 0 ]; then
  [ -d ui/node_modules ] || fail "ui — dependencies are not installed"
  cd ui
  echo "== ui: types =="
  pnpm run typecheck || fail "ui — types"
  echo "== ui: lint and format of the changed files =="
  lintable=()
  for file in "${ui_changed[@]}"; do
    case "$file" in *.ts | *.tsx | *.js | *.mjs) lintable+=("$file") ;; esac
  done
  if [ "${#lintable[@]}" -gt 0 ]; then
    pnpm exec eslint --max-warnings 0 "${lintable[@]}" || fail "ui — lint"
  fi
  pnpm exec prettier --check --ignore-unknown "${ui_changed[@]}" || fail "ui — format"
  echo "== ui: the unit tests related to the changed files =="
  pnpm exec vitest related --run --passWithNoTests "${ui_changed[@]}" || fail "ui — unit tests"
  echo "  (the build and the browser tests run in scripts/check.sh)"
fi

echo
echo "Fast loop passed. scripts/check.sh is still required before a STOP report or a PR."
