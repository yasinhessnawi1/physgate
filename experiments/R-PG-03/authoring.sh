#!/usr/bin/env bash
#
# R-PG-03, CRITERIA.md §2.2 and §2.5: the runner's fixed command sheet for the authoring.
#
#   experiments/R-PG-03/authoring.sh inputs            every fixed input and message, by sha256
#   experiments/R-PG-03/authoring.sh prove             the sandbox, on the scripted endpoint
#   experiments/R-PG-03/authoring.sh status            the state: counts only
#   experiments/R-PG-03/authoring.sh next              the one next step of the sheet
#   experiments/R-PG-03/authoring.sh limit-reset       the usage limit has reset: the cut turn resumes
#   experiments/R-PG-03/authoring.sh service-back      the owner says the service is back
#   experiments/R-PG-03/authoring.sh owner-resume      the owner's word: resume the turn once more
#   experiments/R-PG-03/authoring.sh owner-stop <batch>  the owner stops at that batch's cap
#
# The runner repeats `next` until it says done, waiting, or stopped for the owner, and does nothing
# else: every message a session receives is a fixed file of Appendix B, or a check script's printed
# facts inside Appendix B's template; every route, resume, replacement, restart and cap is the
# sheet's own (authoring.py). The runner reads only what `next` prints: counts, exit codes, audit
# summaries and the facts it forwards.
#
# Run it on the ARM virtual machine, as the run account, from the run checkout at R, after
# "Sheet filled" (the reviewers' sheet is copied to ~/runs/rpg03/sheet/sources.json), at least five
# hours after R-PG-01b's last session, and never while a block or an R-PG-01b round runs:
#
#   setsid nohup experiments/R-PG-03/authoring.sh next >> ~/runs/rpg03/authoring/runner.log 2>&1 < /dev/null &
#
# The credential (token.sh, R-PG-01b's discipline): `next` loads it into one unexported variable,
# gives it to the step's process alone, never prints it, and after each step scans everything the
# authoring wrote for it; the watcher (watch_limit.sh) stops the step at a usage limit. Each turn
# gets its line in the quota ledger.

set -euo pipefail

CHECKOUT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$CHECKOUT/experiments/R-PG-03"
RUNS="${RP3_RUNS:-$HOME/runs/rpg03}"
export RP3_RUNS="$RUNS"
ENV_FILE="$HOME/.config/physgate-run.env"
AUTH="$RUNS/authoring"
cd "$CHECKOUT"
py() { uv run --frozen python -I "$@"; }

case "${1:-}" in
  inputs) py "$HERE/authoring.py" inputs --out "$AUTH/inputs.json"; exit $? ;;
  status) py "$HERE/authoring.py" status; exit $? ;;
  limit-reset|service-back|owner-resume) py "$HERE/authoring.py" "$1"; exit $? ;;
  owner-stop) py "$HERE/authoring.py" owner-stop --batch "${2:?the batch}"; exit $? ;;
  prove)
    unset CLAUDE_CODE_OAUTH_TOKEN ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN
    N=1; while [ -e "$AUTH/proof-$N" ]; do N=$((N + 1)); done
    mkdir -p "$AUTH"
    py "$HERE/authoring.py" prove --out "$AUTH/proof-$N"; exit $? ;;
  next) ;;
  *) sed -n '4,13p' "$0" >&2; exit 2 ;;
esac

mkdir -p "$AUTH"
LOG="$AUTH/runner.log"
say() { echo "$*" | tee -a "$LOG"; }
unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN ANTHROPIC_BASE_URL CLAUDE_CODE_OAUTH_TOKEN
# shellcheck source=token.sh
source "$HERE/token.sh"
export DISABLE_AUTOUPDATER=1
rp3_load_token "$ENV_FILE" 2>> "$LOG" || { say "REFUSED: the run account's token (see the line above)"; exit 1; }
BEFORE="$(find "$AUTH" -name '*.outcome.json' 2>/dev/null | sort)"
STARTED="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
set +e
( rp3_exec_with_token setsid uv run --frozen python -I "$HERE/authoring.py" next ) > "$AUTH/next.out" 2>> "$LOG" &
STEP=$!
"$HERE/watch_limit.sh" "$AUTH/watcher.log" authoring "$STEP" "$AUTH" &
WATCHER=$!
wait "$STEP"; CODE=$?
wait "$WATCHER"
set -e
say "next $(date -u +%Y-%m-%dT%H:%M:%SZ) exit $CODE: $(tail -n 1 "$AUTH/next.out")"
# Each turn this step ran gets its ledger line: a resume as a resume, any other turn as its session's.
AFTER="$(find "$AUTH" -name '*.outcome.json' 2>/dev/null | sort)"
LABEL="$(python3 -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("account_label", "?"))' "$RUNS/owner/authoring.json" 2>/dev/null || echo "?")"
comm -13 <(printf '%s\n' "$BEFORE") <(printf '%s\n' "$AFTER") | while read -r outcome; do
  [ -n "$outcome" ] || continue
  stream="${outcome%.outcome.json}.stream.jsonl"
  session="$(basename "$(dirname "$(dirname "$outcome")")")"
  turn="$(basename "${outcome%.outcome.json}")"
  kind=authoring; case "$turn" in *-resume-*) kind=resume ;; esac
  py "$HERE/ledger.py" session --kind "$kind" --label "$session $turn" --stream "$stream" \
    --account "$LABEL" --window "authoring" --started "$STARTED" --ended "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$LOG"
done
# The credential never belongs in what the authoring wrote: counts only, never a match. The audits
# and the outcomes name the prefixes' counts in keys that do not spell them.
SCAN_OK=1
rp3_scan "$AUTH" >> "$LOG" || SCAN_OK=0
rp3_drop_token
[ "$SCAN_OK" = 1 ] || { say "REFUSED: the token's scan found a hit in what the authoring wrote"; exit 1; }
exit "$CODE"
