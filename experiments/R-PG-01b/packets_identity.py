"""R-PG-01b, CRITERIA.md L5, L6 and L7: every review packet of both arms, built with no session.

Usage::

    packets_identity.py build --arm I|F --corpus <dir> --root <new review root> --out <file>
    packets_identity.py compare --i <run commit, arm I> --f <run commit, arm F>
        --r-pg-01 <8bc03fc, arm I>

``build`` runs under whichever checkout's code imports as ``physgate`` (the run commit's, or, for
arm I, ``8bc03fc``'s through ``uv run --project``). For each artefact, in corpus order, and each
side (the injected patch, then the clean twin), it makes what one review is given, as R-PG-01's
instrument and reviewer make it, and runs no session:

- the materialised worktree and its account, with the corpus's parts sheet, at one fixed path per
  artefact and side (``<root>/review/<the instrument's id>``), whatever the arm and the code;
- the blindness check the instrument runs before a review (``require_blind``): L6 counts refusals;
- the reviewer's packet, its ``read/`` directory and ``packet.json``, built by the reviewer's own
  ``build_packet`` and held by its ``check_parts``, under one fixed session id.

For each it records two digests and removes what it built before the next is made at the same
place:

- **exact**: every file of the worktree (git's own directory aside) and of ``read/``, by path and
  bytes, the account, ``packet.json`` and both commit ids;
- **normalised** (L7): the same, with only what the sheet may change set aside: the sheet's bytes,
  the account's one sentence naming the sheet, the file listing's line for the sheet, the two
  commit ids, and every digest, size and part boundary that follows from them (the account's and
  the transcript's parts are joined before they are read; the listing's part lines are set aside).

``compare`` holds the records to L5 (arm I's 80 exact digests at the run commit equal those
``8bc03fc`` builds), L6 (arm F's 80 packets refused 0 times) and L7 (each of arm F's normalised
digests equals arm I's for the same artefact and side). It prints counts only and exits 1 unless
all three hold.
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
import common as C  # noqa: E402

#: The one session id every packet is built under (a generated id's form, §14 L7).
FIXED_SESSION = "00000000-0000-4000-8000-000000000000"
SHEET = "parts_sheet.json"
_PART = re.compile(r"^(transcript|files)-[0-9]{2,}-of-[0-9]{2,}\.md$")
_LISTED = re.compile(r"^- (.+) \(([0-9]+) bytes\)$")


def _sentences() -> tuple[str, ...]:
    """Every sentence the account may name the sheet in, at this code (one, two or three)."""
    from physgate.evaluation.inject import materialise as m

    names = ("ACCOUNT_SHEET", "ACCOUNT_SHEET_GIVEN", "ACCOUNT_SHEET_REMARKS")
    found = [getattr(m, n, None) for n in names]
    found = [s for s in found if isinstance(s, str)]
    if not found:
        # 8bc03fc writes R-PG-01's sentence inline; it is the one ACCOUNT_SHEET keeps.
        found = [
            "The parts sheet the design's numbers come from is `parts_sheet.json` in the "
            "worktree, given with the design: each row by its id, with its number, its unit "
            "and the address it was read from. A source written as `derived: [R1.03] * "
            "[R5.02]` is arithmetic over the rows it names.\n"
        ]
    return tuple(sorted(found, key=len, reverse=True))


def _account(text: str, sentences: tuple[str, ...]) -> tuple[str, int]:
    """The account with its sentence naming the sheet set aside; how many it held."""
    held = 0
    for s in sentences:
        held += text.count(s)
        text = text.replace(s, "<the sentence naming the sheet>\n")
    return text, held


def _files(root: Path, skip_git: bool = False) -> dict[str, bytes]:
    out = {}
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if skip_git and ".git" in rel.parts:
            continue
        if p.is_file():
            out[rel.as_posix()] = p.read_bytes()
    return out


def _digest(parts: dict[str, bytes]) -> str:
    h = hashlib.sha256()
    for name in sorted(parts):
        h.update(name.encode() + b"\0" + hashlib.sha256(parts[name]).hexdigest().encode() + b"\n")
    return h.hexdigest()


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


def _record(packet: dict[str, Any]) -> dict[str, Any]:
    """``packet.json`` with the commits, seals, digests and part lists the sheet moves set aside."""
    keep = json.loads(json.dumps(packet))
    for key in ("trajectory_seal", "transcript_sha256", "transcript_parts", "files_parts"):
        keep.pop(key, None)
    keep.pop("session_seals", None)
    art = keep.get("artefact") or {}
    for key in ("attempt_commit", "base_commit", "trajectory_sha256", "trajectory_length"):
        art.pop(key, None)
    keep["required_reading"] = [
        p for p in keep.get("required_reading", []) if not _PART.match(Path(p).name)
    ]
    return keep


def snapshot(made: Any, review: Path, sentences: tuple[str, ...]) -> dict[str, Any]:  # noqa: ANN401
    """The exact and normalised digests of one review's worktree, account and packet."""
    read = review / "read"
    worktree = _files(made.worktree, skip_git=True)
    shown = _files(read)
    account = made.trajectory.read_bytes()
    packet = (review / "packet.json").read_bytes()
    commits = f"{made.base_commit} {made.commit}".encode()
    exact = _digest(
        {
            **{f"worktree/{k}": v for k, v in worktree.items()},
            **{f"read/{k}": v for k, v in shown.items()},
            "account": account,
            "packet.json": packet,
            "commits": commits,
        }
    )
    record = json.loads(packet)
    order = [p["name"] for p in record.get("transcript_parts", [])]
    transcript = b"".join(shown[n] for n in order).decode()
    listing = b"".join(shown[p["name"]] for p in record.get("files_parts", [])).decode()
    norm_account, held = _account(account.decode(), sentences)
    norm_transcript, held_t = _account(transcript, sentences)
    others = {
        k: v for k, v in shown.items() if not _PART.match(Path(k).name) and Path(k).name != SHEET
    }
    normalised = _digest(
        {
            **{f"worktree/{k}": v for k, v in worktree.items() if Path(k).name != SHEET},
            **{f"read/{k}": v for k, v in others.items()},
            "account": norm_account.encode(),
            "transcript": norm_transcript.encode(),
            "listing": _listing(listing).encode(),
            "packet.json": json.dumps(_record(record), sort_keys=True).encode(),
        }
    )
    return {
        "exact": exact,
        "normalised": normalised,
        "files": len(worktree) + len(shown),
        "sentence_in_account": held,
        "sentence_in_transcript": held_t,
        "sheet_in_worktree": SHEET in worktree,
        "sheet_in_read": f"worktree/{SHEET}" in shown,
    }


def build(arm: str, corpus_dir: Path, root: Path) -> dict[str, Any]:
    """Every packet of one arm's corpus at this code: digests and blindness, each packet."""
    import physgate
    from physgate.evaluation.inject.corpus import load_corpus
    from physgate.evaluation.inject.exceptions import BlindnessError
    from physgate.evaluation.inject.materialise import materialise, require_blind
    from physgate.evaluation.inject.runner import control_id, review_id
    from physgate.knowledge.promote import KNOWLEDGE_ROOT
    from physgate.orchestrator.cli import _library_root
    from physgate.orchestrator.protocols import Artefact
    from physgate.orchestrator.trajectory import seal
    from physgate.reviewers.packet import build_packet, check_parts
    from physgate.reviewers.places import require_review_root, review_dir
    from physgate.reviewers.rubric import load_rubric

    root = require_review_root(root)
    if root.exists():
        msg = f"{root} exists: every packet is built at a fixed path under a new root"
        raise SystemExit(msg)
    library = _library_root()
    if library is None:
        raise SystemExit("no checkout holds the rubrics")
    corpus = load_corpus(corpus_dir.resolve())
    sentences = _sentences()
    rubrics = {r: load_rubric(library / KNOWLEDGE_ROOT, r) for r in C.RUBRIC_SHA256}
    packets: dict[str, Any] = {}
    refused = 0
    try:
        for a in corpus.artefacts:
            for side, sid, patch in (
                ("injected", review_id(C.SEED, a.id), a.injected),
                ("twin", control_id(C.SEED, a.id), a.clean),
            ):
                place = root / "review" / sid
                made = materialise(corpus.base, patch, place, corpus.parts_sheet)
                try:
                    require_blind(made, (a.id, a.description))
                    blind = True
                except BlindnessError:
                    blind, refused = False, refused + 1
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
                    rubric=rubrics[a.assigned_role],
                    library=library,
                    spec=None,
                )
                from physgate.reviewers.packet import Packet  # noqa: PLC0415

                packet = Packet.model_validate_json((review / "packet.json").read_bytes())
                check_parts(packet, repo=made.worktree, base_commit=made.base_commit)
                packets[f"{a.id}/{side}"] = {"blind": blind, **snapshot(made, review, sentences)}
                shutil.rmtree(place)
                shutil.rmtree(review)
    finally:
        shutil.rmtree(root, ignore_errors=True)
    exact_all = hashlib.sha256(
        "".join(packets[k]["exact"] for k in sorted(packets)).encode()
    ).hexdigest()
    return {
        "arm": arm,
        "code": str(Path(physgate.__file__).resolve().parents[2]),
        "corpus_manifest_sha256": corpus.manifest_sha256,
        "packets": len(packets),
        "blindness_refused": refused,
        "exact_all": exact_all,
        "per_packet": packets,
    }


def compare(i: dict[str, Any], f: dict[str, Any], r: dict[str, Any]) -> dict[str, Any]:
    """L5, L6 and L7 from three builds; counts only."""
    keys = sorted(i["per_packet"])
    l5 = sum(i["per_packet"][k]["exact"] == r["per_packet"].get(k, {}).get("exact") for k in keys)
    same_keys = sorted(f["per_packet"]) == keys == sorted(r["per_packet"])
    l7 = sum(
        f["per_packet"][k]["normalised"] == i["per_packet"][k]["normalised"]
        for k in keys
        if k in f["per_packet"]
    )
    differ_exact = sum(
        f["per_packet"][k]["exact"] != i["per_packet"][k]["exact"]
        for k in keys
        if k in f["per_packet"]
    )
    one_sentence = sum(
        p["sentence_in_account"] == 1 and p["sentence_in_transcript"] == 1
        for build_ in (i, f)
        for p in build_["per_packet"].values()
    )
    found = {
        "packets": len(keys),
        "same_artefacts_and_sides": same_keys,
        "L5_arm_I_identical_to_8bc03fc": l5,
        "L6_arm_F_refused": f["blindness_refused"],
        "L7_arm_F_differs_only_as_allowed": l7,
        "arm_F_exact_differs_from_arm_I": differ_exact,
        "accounts_naming_the_sheet_once": one_sentence,
        "arm_I_exact_all_run_commit": i["exact_all"],
        "arm_I_exact_all_8bc03fc": r["exact_all"],
        "manifests": [i["corpus_manifest_sha256"], f["corpus_manifest_sha256"]],
    }
    n = C.DENOMINATOR * 2
    found["holds"] = (
        same_keys
        and len(keys) == n
        and l5 == n
        and f["blindness_refused"] == 0
        and l7 == n
        and one_sentence == 2 * n
    )
    return found


def main(argv: list[str] | None = None) -> int:
    """Build or compare; print counts only."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--arm", choices=C.ARMS, required=True)
    b.add_argument("--corpus", type=Path, required=True)
    b.add_argument("--root", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("compare")
    c.add_argument("--i", type=Path, required=True)
    c.add_argument("--f", type=Path, required=True)
    c.add_argument("--r-pg-01", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.cmd == "build":
        if args.out.exists():
            raise SystemExit(f"{args.out} exists; a record is never written over")
        found = build(args.arm, args.corpus, args.root.expanduser())
        args.out.write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
        print(
            json.dumps(
                {k: found[k] for k in ("arm", "packets", "blindness_refused", "exact_all", "code")},
                sort_keys=True,
            )
        )
        return 0
    found = compare(*(json.loads(p.read_text()) for p in (args.i, args.f, args.r_pg_01)))
    print(json.dumps(found, sort_keys=True))
    return 0 if found["holds"] else 1


if __name__ == "__main__":
    sys.exit(main())
