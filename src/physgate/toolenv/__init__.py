"""The tool environment a run's role sessions compute and build with, recorded byte for byte.

A role session's scripts import python-control, MuJoCo and their kind, and its builds run a
firmware toolchain. Those libraries and tools are code behind the numbers a run reports, so the
run measures the environment they come from and records it: the interpreter, every distribution
with its version, every native tool with its version, and one digest over every file
(:mod:`.manifest`). It is measured again before every session and refused on any difference, so a
session never runs on an environment other than the one the run recorded (:mod:`.record`).

What this package owns: the record, the measure, the comparison. What it does not own: building
the environment (a provisioning step outside every session), putting it on a session's path (the
dispatcher), or deciding what code may stand behind a sealed record (the series collector).
"""
