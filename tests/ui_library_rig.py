"""A curated library for the operator UI's tests, holding every state a library file can be in.

Built at run time in a temporary folder, never from the checkout's own library, whose bytes
other work changes. What it holds:

- ``control/standards.md``, written by the second of two promotion lines for it. The first
  line in log order carries the *later* timestamp, so a reader that chose the promotion by time
  would pick the wrong one;
- ``control/skill.md``, edited after its promotion, so it differs from every promotion;
- ``electrical/standards.md``, named only by a line that recorded no digest;
- ``cross/standards.md``, never promoted. One line names it, but under an absolute
  destination outside this library, which names no file here;
- ``sizing/standards.md``, a role that is not a domain, written by its promotion. Again the
  matching line carries the earlier time;
- two bounds tables, never promoted: ``electrical`` with one range, ``cross`` with one envelope;
- ``laws/laws.toml``, a folder holding none of the three library files, never listed;
- the reviewers' tree: a rubric and a staged rubric draft, both carrying a marker no response
  may ever contain, and two rubric promotion lines, each with a canary;
- a log line of a kind no reader knows (``law``), kept as written;
- four staged candidates: standards for control (replaces the file), a skill for control
  (adds to it), a skill for control staged as a replacement, and an antipattern for firmware,
  whose folder does not exist (promotion would create it).

Every planted string is built here at run time, so no test source carries one.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from pathlib import Path

from physgate.knowledge.staging import Candidate

#: The staged candidates, by what each does.
STANDARDS_CANDIDATE = "cand-standards-control"
SKILL_CANDIDATE = "cand-skill-control"
REPLACING_CANDIDATE = "cand-skill-replaces"
ANTIPATTERN_CANDIDATE = "cand-antipattern-firmware"
#: The rubric draft, staged in the reviewers' tree: never listed, never served.
RUBRIC_DRAFT = "cand-rubric-control"

CONTROL_STANDARDS = b"# Control standards\n\nA loop is closed before it is tuned.\n"
CONTROL_STANDARDS_BEFORE = b"# Control standards\n\nAn older rule.\n"
CONTROL_SKILL_PROMOTED = b"# Control skill\n\nA pattern, as promoted.\n"
CONTROL_SKILL_NOW = b"# Control skill\n\nA pattern, edited after its promotion.\n"
ELECTRICAL_STANDARDS = b"# Electrical standards\n\nA rule promoted before digests were kept.\n"
CROSS_STANDARDS = b"# Cross-domain standards\n\nNever promoted.\n"
SIZING_STANDARDS = b"# Sizing standards\n\nA sizing rule.\n"
SIZING_STANDARDS_BEFORE = b"# Sizing standards\n\nAn older sizing rule.\n"

ELECTRICAL_BOUNDS = """[meta]
domain = "electrical"
curated_by = "a test fixture"

[[range]]
quantity = "sample_rate"
low = 0.78
high = 32000
unit = "Hz"
class = "a sensor's output data rate, as a fixture states it, with a class text long enough \
to wrap on a narrow screen"
source = "A fixture source, read on the date below."
retrieved = 2026-10-19
confirmed = 2026-10-19
note = "Fixture range."
"""

CROSS_BOUNDS = """[meta]
domain = "cross"
curated_by = "a test fixture"

[[envelope]]
kind = "voltage"
low = 0
high = 60
unit = "V"
class = "every voltage on the fixture's class of machine"
source = "A fixture source for the envelope."
retrieved = 2026-10-20
confirmed = 2026-10-20
note = "Fixture envelope."
"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Library:
    """The fixture library and what a test needs to know about it."""

    #: The ``knowledge`` folder itself.
    root: Path
    #: The canaries the rubric promotion lines carry.
    canaries: tuple[str, ...]
    #: Bytes inside the reviewers' tree, which no response may contain.
    reviewer_marker: bytes


def _candidate(
    kind: str, domain: str, candidate_id: str, content: str, *, replaces: bool = False
) -> str:
    record = Candidate.model_validate(
        {
            "kind": kind,
            "domain": domain,
            "content": content,
            "episode_id": "episode-7",
            "candidate_id": candidate_id,
            "written": "2026-11-01T10:00:00Z",
            "replaces": replaces,
        }
    )
    return record.model_dump_json(indent=2) + "\n"


def _line(kind: str, domain: str, destination: str, promoted: str, **extra: object) -> str:
    record: dict[str, object] = {
        "candidate_id": secrets.token_hex(16),
        "kind": kind,
        "domain": domain,
        "episode_id": "episode-1",
        "destination": destination,
        "promoted_by": "Yasin Hessnawi",
        "promoted": promoted,
        **extra,
    }
    return json.dumps(record, sort_keys=True) + "\n"


def build_library(parent: Path) -> Library:
    """Build the fixture library as ``parent/knowledge`` and return it."""
    root = parent / "knowledge"
    files = {
        "control/standards.md": CONTROL_STANDARDS,
        "control/skill.md": CONTROL_SKILL_NOW,
        "electrical/standards.md": ELECTRICAL_STANDARDS,
        "electrical/bounds.toml": ELECTRICAL_BOUNDS.encode(),
        "cross/standards.md": CROSS_STANDARDS,
        "cross/bounds.toml": CROSS_BOUNDS.encode(),
        "sizing/standards.md": SIZING_STANDARDS,
        "laws/laws.toml": b"# not a library file\n",
    }
    marker = ("REVIEWER-ONLY-" + "MARKER-" + secrets.token_hex(4)).encode()
    files["reviewers/control/rubric.md"] = b"# rubric\n\n" + marker + b"\n"
    files[f"reviewers/staging/rubric/{RUBRIC_DRAFT}.json"] = _candidate(
        "rubric", "control", RUBRIC_DRAFT, "draft " + marker.decode()
    ).encode()
    staged = {
        f"staging/standards/{STANDARDS_CANDIDATE}.json": _candidate(
            "standards", "control", STANDARDS_CANDIDATE, "# Control standards\n\nA new rule.\n"
        ),
        f"staging/skill/{SKILL_CANDIDATE}.json": _candidate(
            "skill", "control", SKILL_CANDIDATE, "A pattern found in an episode.\n"
        ),
        f"staging/skill/{REPLACING_CANDIDATE}.json": _candidate(
            "skill",
            "control",
            REPLACING_CANDIDATE,
            "# Control skill\n\nCorrected whole.\n",
            replaces=True,
        ),
        f"staging/antipattern/{ANTIPATTERN_CANDIDATE}.json": _candidate(
            "antipattern", "firmware", ANTIPATTERN_CANDIDATE, "Never poll in an interrupt.\n"
        ),
    }
    files.update({name: text.encode() for name, text in staged.items()})
    canaries = (secrets.token_hex(16), secrets.token_hex(16))
    rubric = "knowledge/reviewers/control/rubric.md"
    log = [
        # Two lines for one file: the first carries the later time and the older bytes.
        _line(
            "standards",
            "control",
            "knowledge/control/standards.md",
            "2026-10-22T05:58:48Z",
            sha256=_sha(CONTROL_STANDARDS_BEFORE),
        ),
        _line(
            "standards",
            "control",
            "knowledge/control/standards.md",
            "2026-10-21T15:07:08Z",
            sha256=_sha(CONTROL_STANDARDS),
        ),
        _line(
            "skill",
            "control",
            "knowledge/control/skill.md",
            "2026-10-21T16:00:00Z",
            sha256=_sha(CONTROL_SKILL_PROMOTED),
        ),
        # Promoted before digests were recorded.
        _line(
            "standards", "electrical", "knowledge/electrical/standards.md", "2026-09-30T19:41:31Z"
        ),
        _line(
            "rubric",
            "control",
            rubric,
            "2026-10-08T12:00:00Z",
            sha256=_sha(b"rubric v1"),
            canary=canaries[0],
        ),
        _line(
            "standards",
            "sizing",
            "knowledge/sizing/standards.md",
            "2026-10-16T23:02:05Z",
            sha256=_sha(SIZING_STANDARDS_BEFORE),
        ),
        _line(
            "standards",
            "sizing",
            "knowledge/sizing/standards.md",
            "2026-10-16T13:29:06Z",
            sha256=_sha(SIZING_STANDARDS),
        ),
        _line(
            "rubric",
            "control",
            rubric,
            "2026-10-09T12:00:00Z",
            sha256=_sha(b"rubric v2"),
            canary=canaries[1],
        ),
        # A kind no reader knows yet, kept as written.
        _line(
            "law", "laws", "knowledge/laws/laws.toml", "2026-11-01T09:00:00Z", sha256=_sha(b"law")
        ),
        # The cross standards' bytes, but under a destination outside this library.
        _line(
            "standards",
            "cross",
            "/elsewhere/knowledge/cross/standards.md",
            "2026-10-01T09:00:00Z",
            sha256=_sha(CROSS_STANDARDS),
        ),
    ]
    for name, data in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (root / "promotions.jsonl").write_text("".join(log))
    return Library(root=root, canaries=canaries, reviewer_marker=marker)
