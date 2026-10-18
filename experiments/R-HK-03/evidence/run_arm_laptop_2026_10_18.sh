#!/bin/zsh
# Runs one README arm command from the run checkout; stdout/stderr and exit code kept beside the log.
set -u
ARM=$1; LOG=$2
export PHYSGATE_CLAUDE_BIN=~/pinned/claude-2.1.301-macos
export RHK03_SCRATCH=~/physgate-scratch/r-hk-03-run
cd /Users/yasinhessnawi/dev/physgate-r-hk-03-run || exit 99
if pgrep -f '^[^ ]*[Pp]ython[^ ]* .*kill_cycles\.py' >/dev/null; then echo "kill_cycles running; not started" > "$RHK03_SCRATCH/$LOG.notstarted"; exit 98; fi
A=experiments/R-HK-01/attempts.jsonl
R=tests/integration/hooks/bypass_corpus_runner.py
date -u +%FT%TZ > "$RHK03_SCRATCH/$LOG.started"
uv run python $R $A $ARM "$RHK03_SCRATCH/$LOG" > "$RHK03_SCRATCH/$LOG.stdout" 2> "$RHK03_SCRATCH/$LOG.stderr"
rc=$?
echo $rc > "$RHK03_SCRATCH/$LOG.exit"
date -u +%FT%TZ > "$RHK03_SCRATCH/$LOG.ended"
exit $rc
