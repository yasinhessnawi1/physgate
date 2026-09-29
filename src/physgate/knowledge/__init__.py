"""Knowledge loading: standards and skill files a role reads, and their staging.

``knowledge/`` at the repository root holds the curated content — one standards
file and one skill file per role's domain, plus ``knowledge/cross/standards.md``,
which every role reads regardless of its own domain (ARCH-051). This package
supplies what reads it: the always-loaded and required-reading sets per role
(:mod:`physgate.knowledge.loader`, ARCH-020, ARCH-023), a measurement of a
candidate set against the hook layer's own token ceiling (:mod:`physgate.knowledge.ceiling`,
ARCH-023), a place for a subtask's outcome to leave a candidate skill or
antipattern (:mod:`physgate.knowledge.staging`, ARCH-100), and the human-run
promotion step that is the library's only writer (``promote.py``, ARCH-100).

This package does not enforce anything itself — it names files and measures
them. ``physgate.hooks.reading`` and ``physgate.hooks.token_ceiling`` are what
refuse a session that has not read them or is over its ceiling.
"""

from __future__ import annotations
