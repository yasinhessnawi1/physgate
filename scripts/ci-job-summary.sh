#!/usr/bin/env bash
#
# CI only: a job's test count and wall time, written to the job summary so the duration of
# every run is on record. Usage: ci-job-summary.sh LABEL START_EPOCH LOGFILE...
# The count lines are the runners' own final summaries, copied verbatim from the logs.

set -uo pipefail

label=$1
start=$2
shift 2
now=$(date +%s)
out=${GITHUB_STEP_SUMMARY:-/dev/stdout}
{
  echo "### $label"
  echo
  echo "- wall time: $((now - start)) s ($(((now - start) / 60)) min $(((now - start) % 60)) s)"
  for log in "$@"; do
    [ -f "$log" ] || { echo "- no log: $log"; continue; }
    sed 's/\x1b\[[0-9;]*m//g' "$log" \
      | grep -E '^(=+ )?[0-9]+ (passed|failed)|^ *Tests +[0-9]+|^ +[0-9]+ passed \(' \
      | sed 's/^/- count: /' | tail -n 3
  done
} >> "$out"
exit 0
