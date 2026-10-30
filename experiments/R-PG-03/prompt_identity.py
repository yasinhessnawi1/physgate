"""R-PG-03, CRITERIA.md §3.3: the prompt identity check, before launch, with no session.

Usage::

    prompt_identity.py corpus --into <new dir>                       at R, once
    prompt_identity.py build --arm <A2|A1|B> --corpus <dir> --root <new review root> --out <file>
    prompt_identity.py compare --new <record> --old <record>

``corpus`` writes the instrument's own four-role test design (``pilot_corpus``: one revision for
each role) with the code at ``R``, once; every tree is then fed exactly those bytes. ``build`` runs
under whichever checkout's code imports as ``physgate`` (``R``, ``R_K``, or through ``uv run
--project`` the kept round's tree ``gr2-r1-run-tree`` or the noise run's ``eae78c0``), and for each
role makes the one review packet that role's revision is given, as the instrument and the reviewer
make it, under one fixed path and one fixed session id: the materialised worktree and its account,
held to ``require_blind``, and the reviewer's ``read/`` directory and ``packet.json``, built by the
reviewer's own ``build_packet`` with the role's rubric (``--generalist``'s for B) and held by
``check_parts``. If that tree's loader refuses a field the complete sheet adds (``given``,
``note``), the record says so, and both trees are then fed the copy with its sheet in the older form
(``--older-sheet``).

``compare`` holds two records of the same arm, the run tree's and the practice tree's (A2 at ``R``
against ``gr2-r1-run-tree``; A1 and B at ``R_K`` against ``eae78c0``), file by file. The packets
**must differ only in the account's sheet sentence**: every file is compared after each tree's own
sentences naming the sheet are set aside, with every digest, size and part boundary that follows
from them; any other difference, the rubric included, is printed by path and fails the check. The
sentence differences are printed apart. Counts and paths only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

FIXED_SESSION = "00000000-0000-4000-8000-000000000000"
SHEET = "parts_sheet.json"
SEED = 0
_PART = re.compile(r"^(transcript|files)-[0-9]{2,}-of-[0-9]{2,}\.md$")
_LISTED = re.compile(r"^- (.+) \(([0-9]+) bytes\)$")
PLACEHOLDER = "<the sentence naming the sheet>\n"
#: The sentence a tree with no named sentences writes inline (the practice cycle's trees), as
#: ``materialise`` there spells it, byte for byte.
INLINE_SENTENCE = (
    "The parts sheet the design's numbers come from is `parts_sheet.json` in the "
    "worktree, given with the design: each row by its id, with its number, its unit "
    "and the address it was read from. A source written as `derived: [R1.03] * "
    "[R5.02]` is arithmetic over the rows it names.\n"
)


def _sentences() -> list[str]:
    """Every sentence this tree's account may name the sheet in, longest first."""
    from physgate.evaluation.inject import materialise as m

    names = ("ACCOUNT_SHEET_REMARKS", "ACCOUNT_SHEET_GIVEN", "ACCOUNT_SHEET")
    found = [s for s in (getattr(m, n, None) for n in names) if isinstance(s, str)]
    if not found:
        # The practice cycle's trees write the sentence inline; it is the one ACCOUNT_SHEET keeps.
        found = [INLINE_SENTENCE]
    return sorted(set(found), key=len, reverse=True)


def _files(root: Path, skip_git: bool = False) -> dict[str, bytes]:
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if skip_git and ".git" in rel.parts:
            continue
        if p.is_file():
            out[rel.as_posix()] = p.read_bytes()
    return out


def _set_aside(text: str, sentences: list[str]) -> tuple[str, int]:
    held = 0
    for s in sentences:
        held += text.count(s)
        text = text.replace(s, PLACEHOLDER)
    return text, held


def _listing(text: str) -> str:
    """The file listing with the sheet's size and the account parts' lines set aside."""
    out = []
    for line in text.splitlines():
        m = _LISTED.match(line)
        if m and Path(m.group(1)).name == SHEET:
            out.append(f"- {m.group(1)} (<the sheet's size>)")
        elif m and _PART.match(Path(m.group(1)).name):
            continue
        else:
            out.append(line)
    return "\n".join(out)


def _packet_record(packet: dict[str, Any]) -> dict[str, Any]:
    """``packet.json`` with the seals, digests and part lists the sentence moves set aside."""
    keep: dict[str, Any] = json.loads(json.dumps(packet))
    for key in ("trajectory_seal", "transcript_sha256", "transcript_parts", "files_parts"):
        keep.pop(key, None)
    keep.pop("session_seals", None)
    art = keep.get("artefact") or {}
    for key in ("trajectory_sha256", "trajectory_length"):
        art.pop(key, None)
    keep["required_reading"] = [
        p for p in keep.get("required_reading", []) if not _PART.match(Path(p).name)
    ]
    return keep


def snapshot(made: Any, review: Path, sentences: list[str]) -> dict[str, Any]:  # noqa: ANN401
    """Every file of one packet, exact and with the sheet's sentence set aside, by its sha256."""
    worktree = _files(made.worktree, skip_git=True)
    shown = _files(review / "read")
    account = made.trajectory.read_bytes()
    packet = json.loads((review / "packet.json").read_bytes())
    order = [p["name"] for p in packet.get("transcript_parts", [])]
    transcript = b"".join(shown[n] for n in order).decode()
    listing = b"".join(shown[p["name"]] for p in packet.get("files_parts", [])).decode()
    norm_account, in_account = _set_aside(account.decode(), sentences)
    norm_transcript, in_transcript = _set_aside(transcript, sentences)
    exact = {
        **{f"worktree/{k}": common.sha256_bytes(v) for k, v in worktree.items()},
        **{f"read/{k}": common.sha256_bytes(v) for k, v in shown.items()},
        "account": common.sha256_bytes(account),
        "packet.json": common.sha256_bytes((review / "packet.json").read_bytes()),
        "commits": common.sha256_bytes(f"{made.base_commit} {made.commit}".encode()),
    }
    normalised = {
        **{f"worktree/{k}": common.sha256_bytes(v) for k, v in worktree.items()},
        **{
            f"read/{k}": common.sha256_bytes(v)
            for k, v in shown.items()
            if not _PART.match(Path(k).name)
        },
        "account": common.sha256_bytes(norm_account.encode()),
        "transcript": common.sha256_bytes(norm_transcript.encode()),
        "listing": common.sha256_bytes(_listing(listing).encode()),
        "packet.json": common.sha256_bytes(
            json.dumps(_packet_record(packet), sort_keys=True).encode()
        ),
        "commits": common.sha256_bytes(f"{made.base_commit} {made.commit}".encode()),
    }
    sentence = [s for s in sentences if s in account.decode()]
    return {
        "exact": exact,
        "normalised": normalised,
        "sentence_in_account": in_account,
        "sentence_in_transcript": in_transcript,
        "sentence_sha256": [common.sha256_bytes(s.encode()) for s in sentence],
        "rubric_sha256": packet.get("rubric_sha256"),
    }


def write_test_corpus(into: Path) -> dict[str, Any]:
    """The instrument's own four-role test design, written by this tree's test code, once."""
    for extra in ("tests", "tests/unit/evaluation"):
        path = str(common.REPO / extra)
        if path not in sys.path:
            sys.path.insert(0, path)
    import pilot_corpus

    from physgate.evaluation.inject.corpus import load_corpus

    if into.exists():
        raise SystemExit(f"{into} exists: the corpus is written once")
    pilot_corpus.write_pilot_corpus(into)
    corpus = load_corpus(into)
    return {
        "artefacts": len(corpus.artefacts),
        "roles": sorted({a.assigned_role for a in corpus.artefacts}),
        "manifest_sha256": corpus.manifest_sha256,
    }


def older_sheet(corpus: Path, into: Path) -> dict[str, Any]:
    """The same corpus with its sheet in the older form: the same rows, numbers only."""
    from physgate.evaluation.inject.corpus import load_corpus, manifest_for, write_manifest

    shutil.copytree(corpus, into)
    sheet = json.loads((into / "sources.json").read_text())
    keep = ("quantity", "value", "unit", "url")
    sheet["rows"] = {k: {f: r.get(f) for f in keep} for k, r in sheet["rows"].items()}
    sheet.pop("remarks", None)
    (into / "sources.json").write_text(json.dumps(sheet, indent=1))
    old = load_corpus(corpus)
    (into / "MANIFEST.json").unlink()
    write_manifest(
        into, manifest_for(into, label=old.manifest.label, author_model=old.manifest.author_model)
    )
    return {"manifest_sha256": load_corpus(into).manifest_sha256}


def build(arm: str, corpus_dir: Path, root: Path) -> dict[str, Any]:
    """One packet per role of the test design, at this tree's code, for one arm."""
    import physgate
    from physgate.evaluation.inject.corpus import load_corpus
    from physgate.evaluation.inject.materialise import materialise, require_blind
    from physgate.evaluation.inject.runner import review_id
    from physgate.knowledge.promote import KNOWLEDGE_ROOT
    from physgate.orchestrator.cli import _library_root
    from physgate.orchestrator.protocols import Artefact
    from physgate.orchestrator.trajectory import seal
    from physgate.reviewers.packet import Packet, build_packet, check_parts
    from physgate.reviewers.places import require_review_root, review_dir
    from physgate.reviewers.rubric import generalist_of, load_rubric

    root = require_review_root(root)
    if root.exists():
        raise SystemExit(f"{root} exists: every packet is built at a fixed path under a new root")
    library = _library_root()
    if library is None:
        raise SystemExit("no checkout holds the rubrics")
    try:
        corpus = load_corpus(corpus_dir.resolve())
    except Exception as exc:  # noqa: BLE001 - the older loader's refusal is the fact recorded
        return {"arm": arm, "refused_by_the_loader": f"{type(exc).__name__}: {exc}"}
    sentences = _sentences()
    packets: dict[str, Any] = {}
    try:
        for a in corpus.artefacts:
            rubric = load_rubric(library / KNOWLEDGE_ROOT, a.assigned_role)
            if common.ARM_KIND[arm] == "generalist":
                rubric = generalist_of(rubric)
            sid = review_id(SEED, a.id)
            place = root / "review" / sid
            made = materialise(corpus.base, a.injected, place, corpus.parts_sheet)
            require_blind(made, (a.id, a.description))
            sealed = seal(made.trajectory.read_bytes())
            artefact = Artefact(
                subtask_id=sid,
                attempt=1,
                assigned_role=a.assigned_role,
                attempt_commit=made.commit,
                worktree=str(made.worktree),
                graph_root=str(made.graph_root),
                trajectory=str(made.trajectory),
                trajectory_sha256=sealed.sha256,
                trajectory_length=sealed.length,
                trajectory_form="account",
                scopes=("subtask", "module"),
                base_revision=made.baseline,
                base_commit=made.base_commit,
                repository=str(made.worktree),
            )
            review = review_dir(root, FIXED_SESSION)
            build_packet(
                review,
                artefact,
                repo=made.worktree,
                base_commit=made.base_commit,
                rubric=rubric,
                library=library,
                spec=None,
            )
            packet = Packet.model_validate_json((review / "packet.json").read_bytes())
            check_parts(packet, repo=made.worktree, base_commit=made.base_commit)
            packets[a.assigned_role] = snapshot(made, review, sentences)
            shutil.rmtree(place)
            shutil.rmtree(review)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return {
        "arm": arm,
        "code": str(Path(physgate.__file__).resolve().parents[2]),
        "corpus_manifest_sha256": corpus.manifest_sha256,
        "roles": sorted(packets),
        "per_role": packets,
    }


def compare(new: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    """Two records of one arm: every difference but the sheet's sentence."""
    if new.get("arm") != old.get("arm"):
        return {"holds": False, "differences": ["the two records are of different arms"]}
    if "refused_by_the_loader" in new or "refused_by_the_loader" in old:
        return {
            "holds": False,
            "differences": ["a loader refused the corpus: feed both the older-form copy"],
        }
    differences: list[str] = []
    sentence: list[str] = []
    if new["corpus_manifest_sha256"] != old["corpus_manifest_sha256"]:
        differences.append("the two trees were fed different corpus bytes")
    roles = sorted(set(new["per_role"]) | set(old["per_role"]))
    for role in roles:
        a, b = new["per_role"].get(role), old["per_role"].get(role)
        if a is None or b is None:
            differences.append(f"{role}: built at one tree only")
            continue
        for path in sorted(set(a["normalised"]) | set(b["normalised"])):
            if a["normalised"].get(path) != b["normalised"].get(path):
                differences.append(f"{role}: {path}")
        if a["rubric_sha256"] != b["rubric_sha256"]:
            differences.append(f"{role}: the rubric")
        if a["sentence_in_account"] != 1 or b["sentence_in_account"] != 1:
            differences.append(f"{role}: the account does not name the sheet exactly once")
        mine = [x for x in differences if x.startswith(f"{role}: ")]
        for path in sorted(set(a["exact"]) | set(b["exact"])):
            if a["exact"].get(path) != b["exact"].get(path) and not mine:
                sentence.append(f"{role}: {path}")
    return {
        "arm": new["arm"],
        "roles": len(roles),
        "differences": differences,
        "exact_differences_explained_by_the_sentence": sentence,
        "sentence_sha256": {
            "new": sorted({d for r in new["per_role"].values() for d in r["sentence_sha256"]}),
            "old": sorted({d for r in old["per_role"].values() for d in r["sentence_sha256"]}),
        },
        "holds": not differences,
    }


def main(argv: list[str] | None = None) -> int:
    """Write the corpus, build a record, or compare two; counts and paths only."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("corpus")
    c.add_argument("--into", type=Path, required=True)
    c.add_argument("--older-sheet", type=Path)
    b = sub.add_parser("build")
    b.add_argument("--arm", choices=common.ARMS, required=True)
    b.add_argument("--corpus", type=Path, required=True)
    b.add_argument("--root", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    k = sub.add_parser("compare")
    k.add_argument("--new", type=Path, required=True)
    k.add_argument("--old", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.cmd == "corpus":
        found = write_test_corpus(args.into)
        if args.older_sheet is not None:
            found["older_sheet"] = older_sheet(args.into, args.older_sheet)
        print(json.dumps(found, sort_keys=True))
        return 0
    if args.cmd == "build":
        if args.out.exists():
            raise SystemExit(f"{args.out} exists; a record is never written over")
        found = build(args.arm, args.corpus, args.root.expanduser())
        args.out.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
        brief = {k: found.get(k) for k in ("arm", "roles", "code", "refused_by_the_loader")}
        print(json.dumps(brief, sort_keys=True))
        return 0 if "refused_by_the_loader" not in found else 5
    found = compare(json.loads(args.new.read_text()), json.loads(args.old.read_text()))
    print(json.dumps(found, sort_keys=True))
    return 0 if found["holds"] else 1


def digest_of(record: dict[str, Any]) -> str:
    """One record's exact digests, joined: a record's identity in the launch log."""
    joined = "".join(
        f"{role}:{path}:{d}"
        for role, r in sorted(record.get("per_role", {}).items())
        for path, d in sorted(r["exact"].items())
    )
    return hashlib.sha256(joined.encode()).hexdigest()


if __name__ == "__main__":
    sys.exit(main())
