"""R-PG-01b, CRITERIA.md §10 and L10: the smoke review that checks arm F's sheet is read whole.

Usage, in the run checkout, with the run account's credential in the environment
(``launch.sh`` exports it, never printed)::

    smoke.py l10 --out <new dir> --root <new review root> --sheet <arm F's sources.json>
    smoke.py session --out <new dir> --root <new review root> --sheet <sheet> [--fallback]

**One smoke** is one review session of the instrument's own four-role pilot design, never this
corpus: its electrical artefact (``e1``), materialised as the instrument materialises a revision,
carrying the given sheet as its parts sheet, held to the blindness check, and reviewed by the run
commit's electrical reviewer with R-PG-01's parameters, through the pinned binary and the
credential in the environment. Its verdict is never a result and is not recorded: only whether
one came, the session's reads of the sheet (classed by ``streams.py``), its tokens and its times.

**L10** (§10): a smoke passes if its stream shows at least one whole read of the sheet and no cut.

- A cut read in any smoke stops it at once: exit 3, the round does not start (§12).
- A smoke with no whole read is repeated, at most twice more.
- After three smokes with no whole read, one check session runs: the same binary, credential,
  settings, hooks and packet, with a one-line prompt that asks for the sheet in full, then stop
  (``--fallback``). A whole read passes L10; none stops it (exit 4, a deviation for the owner).
- A session that leaves no stream is an infrastructure failure of the check: exit 1.

It writes ``smoke.json`` into ``--out`` (every session's kind, session id, reads, tokens and
times) and prints counts, times and tokens only.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import streams as S  # noqa: E402

#: The pilot design's artefact the smoke reviews: the electrical one (§10).
ARTEFACT = "e1"
ROLE = "electrical"
#: §10's three smokes, at most, before the check session.
SMOKES = 3


def _pilot() -> tuple[Any, Any, dict[str, Any]]:
    """The pilot design's base and the electrical artefact's injected patch, from this checkout."""
    for extra in ("tests", "tests/unit/evaluation"):
        path = str(C.REPO / extra)
        if path not in sys.path:
            sys.path.insert(0, path)
    import pilot_corpus  # noqa: PLC0415 - the checkout's own test design
    from instrument_corpus import LABEL  # noqa: PLC0415

    from physgate.evaluation.inject.corpus import Base, Patch

    artefact = next(a for a in pilot_corpus.ARTEFACTS if a["id"] == ARTEFACT)
    base = Base(label=LABEL, nodes=tuple(pilot_corpus.BASE_NODES))
    patch = Patch(nodes=tuple(artefact["injected"]["nodes"]))
    return base, patch, artefact


def fallback_prompt(read_root: str) -> str:
    """§10's one-line prompt: read the sheet in full, then stop."""
    return f"Read {read_root}/worktree/{S.SHEET_NAME} in full with the Read tool, then stop."


@contextlib.contextmanager
def _prompt(fallback: bool) -> Iterator[None]:
    """The reviewer's own prompt, or, for the check session, §10's one line in its place."""
    if not fallback:
        yield
        return
    import physgate.reviewers.claude as claude  # noqa: PLC0415

    def one_line(role: str, packet: Any, kind: str = "paired", contract: str = "") -> str:  # noqa: ANN401, ARG001
        return fallback_prompt(packet.read_root)

    with mock.patch.object(claude, "review_prompt", one_line):
        yield


def _usage(stream: Path) -> dict[str, Any]:
    """The binary's own totals from the stream's result line, and its wall clock and cost."""
    result: dict[str, Any] = {}
    if stream.is_file():
        for line in stream.read_text(errors="replace").splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("type") == "result":
                result = event
    usage = result.get("usage") or {}
    kinds = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    tokens = {k: int(usage.get(k) or 0) for k in kinds}
    return {
        "result_line": bool(result),
        "tokens": tokens,
        "tokens_total": sum(tokens.values()),
        "turns": result.get("num_turns"),
        "duration_ms": result.get("duration_ms"),
        "binary_usd": result.get("total_cost_usd"),
    }


def utc() -> str:
    """The time now, UTC, to the second."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def session(
    out: Path, root: Path, sheet: bytes, *, fallback: bool, install: Path, label: str
) -> dict[str, Any]:
    """One smoke or check session; what its stream shows, with its tokens and times."""
    from physgate.evaluation.inject.materialise import materialise, require_blind
    from physgate.evaluation.inject.runner import InstrumentParams, review_id
    from physgate.orchestrator import cli as orchestrator_cli
    from physgate.orchestrator.credentials import credential_for
    from physgate.orchestrator.decompose import binary_version
    from physgate.orchestrator.exceptions import ReviewUnavailableError
    from physgate.orchestrator.install import prepare_install, require_current
    from physgate.orchestrator.invocation import claude_binary
    from physgate.orchestrator.protocols import Artefact
    from physgate.orchestrator.trajectory import seal
    from physgate.reviewers.claude import ReviewerSetup, claude_reviewers
    from physgate.reviewers.places import require_review_root

    params = InstrumentParams.model_validate_json(
        (C.REPO / "experiments" / "R-PG-01" / "params.json").read_bytes()
    )
    review_root = require_review_root(root)
    root.mkdir(parents=True, exist_ok=True)
    binary = claude_binary()
    version = binary_version(binary)
    project = orchestrator_cli._project_root()
    if install.exists():
        require_current(install, project)
    else:
        prepare_install(install, project)
    library = orchestrator_cli._library_root()
    if library is None:
        msg = "no source checkout holds the rubrics"
        raise SystemExit(msg)
    setup = ReviewerSetup(
        run_id=f"smoke-{label}",
        models=dict(params.reviewers),
        claude_version=version,
        bounds=params.bounds,
        effort=params.effort,
        max_output_tokens=params.max_output_tokens,
        token_ceiling=params.token_ceiling,
        review_root=review_root,
        repo=None,
        install_bin=install / "bin" / "physgate",
        binary=binary,
        base_url=os.environ.get("ANTHROPIC_BASE_URL"),
        credential=credential_for(params.auth, os.environ),
        library=library,
    )
    reviewer = claude_reviewers(setup)[ROLE]
    base, patch, artefact = _pilot()
    subtask = review_id(C.SEED, label)
    made = materialise(base, patch, review_root / "review" / subtask, sheet)
    require_blind(made, (str(artefact["id"]), str(artefact["description"])))
    sealed = seal(made.trajectory.read_bytes())
    attempt = Artefact(
        subtask_id=subtask,
        attempt=1,
        assigned_role=ROLE,
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
    started = utc()
    session_id: str | None
    ended_as: str
    try:
        with _prompt(fallback):
            result = reviewer.review(attempt)
        session_id, ended_as = result.session_id, "verdict"
    except ReviewUnavailableError as exc:
        session_id, ended_as = exc.session_id, f"review_unavailable:{exc.cause}"
    ended = utc()
    stream = review_root / str(session_id) / S.STREAM[0] / S.STREAM[1]
    reads = S.session_reads(stream, C.SHEET_LINES["F"]) if session_id else {"missing": True}
    found = {
        "kind": "check" if fallback else "smoke",
        "label": label,
        "session_id": session_id,
        "ended_as": ended_as.split(":")[0],
        "cause": ended_as.split(":")[1] if ":" in ended_as else None,
        "started_utc": started,
        "ended_utc": ended,
        "binary_version": version,
        "sheet_sha256": C.sha256_bytes(sheet),
        "reads": {k: v for k, v in reads.items() if k != "classes"},
        **_usage(stream),
    }
    (out / f"{label}.json").write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
    return found


def l10(out: Path, root: Path, sheet: bytes) -> tuple[int, dict[str, Any]]:
    """§10's L10 in full: its exit code and the record of every session it ran."""
    install = out / "install"
    sessions: list[dict[str, Any]] = []

    def record(outcome: str, code: int) -> tuple[int, dict[str, Any]]:
        smokes = [s for s in sessions if s["kind"] == "smoke"]
        found = {
            "l10": outcome,
            "exit": code,
            "sessions": sessions,
            "smoke_tokens_max": max((s["tokens_total"] for s in smokes), default=0),
            "tokens_all_sessions": sum(s["tokens_total"] for s in sessions),
            "first_started_utc": sessions[0]["started_utc"] if sessions else None,
            "last_ended_utc": sessions[-1]["ended_utc"] if sessions else None,
        }
        (out / "smoke.json").write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
        return code, found

    for n in range(1, SMOKES + 1):
        s = session(out, root / f"s{n}", sheet, fallback=False, install=install, label=f"smoke-{n}")
        sessions.append(s)
        if s["reads"].get("missing"):
            return record("no stream: an infrastructure failure of the check", 1)
        if s["reads"]["cut"]:
            return record("a cut read: the round does not start", 3)
        if s["reads"]["whole"]:
            return record("passed", 0)
    s = session(out, root / "c1", sheet, fallback=True, install=install, label="check-1")
    sessions.append(s)
    if s["reads"].get("missing"):
        return record("no stream: an infrastructure failure of the check", 1)
    if s["reads"]["cut"]:
        return record("a cut read: the round does not start", 3)
    if s["reads"]["whole"]:
        return record("passed on the check session", 0)
    return record("L10 cannot be applied: no whole read in three smokes and the check", 4)


def _brief(found: dict[str, Any]) -> dict[str, Any]:
    keep = ("kind", "label", "ended_as", "started_utc", "ended_utc", "tokens_total", "turns")
    return {**{k: found.get(k) for k in keep}, "reads": found.get("reads")}


def main(argv: list[str] | None = None) -> int:
    """Run L10 or one session; print counts, times and tokens only."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("cmd", choices=("l10", "session"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--sheet", type=Path, required=True)
    parser.add_argument("--fallback", action="store_true")
    args = parser.parse_args(argv)
    out = args.out.expanduser().resolve()
    out.mkdir(parents=True)  # new: a smoke's records are never written over
    sheet = args.sheet.read_bytes()
    if args.cmd == "session":
        found = session(
            out,
            args.root.expanduser().resolve(),
            sheet,
            fallback=args.fallback,
            install=out / "install",
            label="check-1" if args.fallback else "smoke-1",
        )
        print(json.dumps(_brief(found), sort_keys=True))
        return 0
    code, record = l10(out, args.root.expanduser().resolve(), sheet)
    print(
        json.dumps(
            {
                "l10": record["l10"],
                "sessions": [_brief(s) for s in record["sessions"]],
                "smoke_tokens_max": record["smoke_tokens_max"],
                "tokens_all_sessions": record["tokens_all_sessions"],
            },
            sort_keys=True,
        )
    )
    return code


if __name__ == "__main__":
    sys.exit(main())
