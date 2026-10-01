"""Every numbered rule in a promoted ``standards.md`` names its enforcement, or says it has none.

This project's own knowledge-loading spec promises this exact script: "a script lists unmarked
rules." A rule is a numbered ``## N. ...`` section; it is marked one of two
ways, by this project's own already-established convention (every promoted
file already uses one or the other, consistently): a line naming what enforces
it, starting ``**Enforced:``, or the literal ``**Judgement-only`` marker,
stating plainly that nothing does. A rule with neither is what ENGINEERING_STANDARDS
§10 and this spec's own risk table ("rules in standards files with no
enforcement home") exist to catch before it ships, not after a human happens
to notice on a close read.

This is deliberately a read of the file's own text, not a second copy of what
each rule claims to enforce: it cannot drift from the content the way a
hand-maintained list could, and it says nothing about whether a named
enforcement actually exists in code — only that *something* is named or the
absence is stated. A rule's accuracy is the content reviewer's job; this
module's job is only that no rule is silently left unmarked.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

#: A rule's own numbered heading, exactly as every promoted standards file writes it.
_SECTION = re.compile(r"^## \d+\. .+$", re.MULTILINE)

_ENFORCED = "**Enforced:"
_JUDGEMENT = "**Judgement-only"

#: Where the promoted library lives, relative to a worktree root — the same
#: convention :mod:`physgate.knowledge.loader` uses.
DEFAULT_ROOT = Path("knowledge")

STANDARDS_NAME = "standards.md"


def unmarked_rules(text: str) -> tuple[str, ...]:
    """Every rule heading in ``text`` whose own section names neither marker, in order.

    A section runs from its own heading to the next ``## N.`` heading, or the
    file's end. A file with no numbered heading at all returns an empty tuple,
    not every line — there is nothing here to mark.
    """
    headings = list(_SECTION.finditer(text))
    unmarked = []
    for index, heading in enumerate(headings):
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        body = text[start:end]
        if _ENFORCED not in body and _JUDGEMENT not in body:
            unmarked.append(heading.group(0).removeprefix("## ").strip())
    return tuple(unmarked)


def standards_files(root: Path = DEFAULT_ROOT) -> tuple[Path, ...]:
    """Every promoted ``standards.md`` under ``root``, sorted; empty if ``root`` has none yet."""
    if not root.is_dir():
        return ()
    return tuple(sorted(root.glob(f"*/{STANDARDS_NAME}")))


def report(root: Path = DEFAULT_ROOT) -> dict[Path, tuple[str, ...]]:
    """Every standards file under ``root`` with at least one unmarked rule, and which ones."""
    findings: dict[Path, tuple[str, ...]] = {}
    for path in standards_files(root):
        unmarked = unmarked_rules(path.read_text(encoding="utf-8"))
        if unmarked:
            findings[path] = unmarked
    return findings


def main(argv: list[str] | None = None) -> int:  # noqa: ARG001 - no arguments taken yet
    """List every unmarked rule across the promoted library; exit 1 if any are found."""
    findings = report()
    if not findings:
        print("No unmarked rules found.")
        return 0
    for path, headings in findings.items():
        print(f"{path}:")
        for heading in headings:
            print(f"  - {heading}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
