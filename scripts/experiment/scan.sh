# Sourced by an experiment's launch script; defines functions only.
#
# count_files_with PATTERN DIR...: how many files under the DIRs hold PATTERN as a fixed
# string, printed as a bare number. Zero files found is the clean case of a scan, and it
# must never end the script that asked: grep exits 1 when it finds nothing, and under
# `set -euo pipefail` a pipeline that grep starts then fails, which ended a launch script
# before it wrote its closing lines. The grep is therefore made to succeed on an empty
# result, while a grep error (status 2: a directory it cannot read) still fails.
count_files_with() {
  local pattern="$1"
  shift
  local found status
  found="$(grep -rlF -- "$pattern" "$@" 2>/dev/null)" && status=0 || status=$?
  if [ "$status" -gt 1 ]; then
    echo "count_files_with: grep failed with status $status" >&2
    return "$status"
  fi
  if [ -z "$found" ]; then
    echo 0
  else
    printf '%s\n' "$found" | wc -l | tr -d ' '
  fi
}
