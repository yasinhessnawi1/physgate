"""The injected-error instrument: known errors, run past a reviewer alone and then the gate.

Risk row 1 of the thesis asks how many physical errors the gate catches after a
paired reviewer has approved them. This package holds the apparatus for that
measurement and none of its numbers: a corpus format (a valid base design and,
per artefact, a clean patch and the same patch with one error injected), a
materialiser that turns one patch into a worktree a reviewer can read, and a
runner that reviews every artefact blind and first, gates each afterwards, and
writes one row per artefact. The count is the experiment's to read and report.
"""
