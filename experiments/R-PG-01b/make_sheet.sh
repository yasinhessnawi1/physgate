#!/usr/bin/env bash
#
# R-PG-01b, CRITERIA.md §2.5 and §14: arm F's corpus, for the "sheet" commit.
#
#   experiments/R-PG-01b/make_sheet.sh
#
# Run from a clean checkout of master at the converter's commit (31b90aa) or later; it refuses
# anywhere else. It copies v1's authors' table to experiments/R-PG-01b/sheet/ with the one edit of
# §2.5 (row R6.05's note, "answered" read as "responded"), runs scripts/parts_sheet_sources.py on
# that copy in keep mode with v1's sheet and --prose drop, writes corpora/injected-errors/
# v1-fullsheet/ (v1's base, artefacts, README.md and unedited table byte for byte, the converted
# sheet, a new manifest), and holds every result to §2.5's measured table (fullsheet.py).
#
# It prints counts and digests only, including the edit's before-and-after digests. It writes
# nothing over: either output existing stops it before anything is written.

set -euo pipefail

CHECKOUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$CHECKOUT"
git merge-base --is-ancestor 31b90aa HEAD \
  || { echo "REFUSED: the converter runs on master at 31b90aa or later" >&2; exit 1; }
[ -z "$(git status --porcelain -- corpora experiments/R-PG-01b scripts src)" ] \
  || { echo "REFUSED: the checkout is not clean" >&2; exit 1; }
uv run --frozen python -I experiments/R-PG-01b/fullsheet.py make
