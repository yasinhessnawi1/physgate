"""The deterministic orchestrator: the loop every measured run happens inside.

Python decides what runs next and whether to merge. A model is called once per
run, at decomposition, and never to schedule, dispatch, merge or reconcile
(ARCH-001). The loop's position lives in the run-event log on disk, never only
in memory, so a killed orchestrator resumes from the file. ``README.md`` in this
directory says what the package owns and what it deliberately does not.
"""
