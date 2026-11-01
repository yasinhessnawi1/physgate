"""R-PG-03, §2.4, §2.5 and §10: what the streams show, counts only.

Usage (from the checkout at ``R``)::

    python -I streams.py block --sheet <sources.json> --arm <A2|A1|B> --run <run dir>
        --scratch <the arm's scratch dir> [--out <file>]
    python -I streams.py author <stream.jsonl> [--stderr <file>] [--exit <code>]
    python -I streams.py limits <path>...
    python -I streams.py smoke --sheet <sources.json> --out <new dir> --root <new review root>

**The cut-read check** (``block``, after each block, §2.4 and §10). For each Read call on
``parts_sheet.json`` in a review's captured stream, the text the model received is classed by
R-PG-01b's rule (§5.5 there): ``cut`` if it returned fewer numbered lines than it asked for, or
asked for the end and the last row id is absent, or is the binary's token-limit error, or is an
"unchanged" stub with no earlier read of that range; ``whole``; ``part``; ``unchanged``; ``error``;
``no_result``. The sheet's numbered lines are counted from the sheet's own bytes (a Read numbers
the empty line after the last newline too: 1,225 for the 40,095-byte sheet), and its last row id
is the last key of its rows. Every review session of the arm's run is read: both logs, every try,
under each lane's root, and any session under a root no log names. Exit 3 if any read is cut: the
block is void (§11).

**An authoring session cut short** (``author``, §2.5): how a turn's stream ended.
``usage_limit`` if the stream or its error output names ``usage_limit_reached``; ``completed`` if
its last ``result`` line is no error, or ended at the session's turn bound (``error_max_turns``,
the session's own bound, not an outage); ``infrastructure`` otherwise: no ``result`` line (the
stream ended before the turn did), or an error result (an API, connection or binary error). A
refusal is never infrastructure: the model's refusal ends a turn with no error.

**Usage-limit facts** (``limits``): the files under the paths that name ``usage_limit_reached``,
and the 429 statuses in the JSON-lines streams; read through no symlink.

**The smoke** (``smoke``, before the first block, §2.4): one review session of the instrument's
own pilot design (its electrical revision, never a set of this experiment), carrying the
reviewers' sheet as its parts sheet, through R's electrical reviewer with R-PG-03's parameters,
the pinned binary and the credential in the environment. It passes if its stream shows at least
one whole read of the sheet and no cut read: exit 0; a cut read exits 3, no whole read 4, no stream
1. Its verdict is never read or recorded.

Counts only: no verdict, finding or row is read.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

SHEET_NAME = "parts_sheet.json"
STREAM = ("session", "stdout.jsonl")
_NUMBERED = re.compile(r"^(\d+)\t")
#: The pinned binary's (2.1.301) own texts for a Read it did not repeat (R-PG-01b's list).
UNCHANGED = (
    "File unchanged since last read. The content from the earlier Read tool_result in this "
    "conversation is still current",
    "Wasted call — file unchanged since your last Read. Refer to that earlier tool_result instead.",
    "<system-reminder>This file is already in your context",
)
#: The pinned binary's error for a Read whose text the service counts above the limit.
TOKEN_LIMIT = re.compile(r"File content \([\d,]+ tokens\) exceeds maximum allowed tokens \(")
CLASSES = ("whole", "part", "cut", "unchanged", "error", "no_result")
LIMIT_WORD = b"usage_limit_reached"
LIMIT_SUFFIXES = (".jsonl", ".json", ".err", ".txt")
STATUS_429 = re.compile(rb'"api_error_status": *429')


def sheet_shape(sheet: bytes) -> tuple[int, str]:
    """The numbered lines a whole Read of the sheet returns, and its last row id."""
    rows = json.loads(sheet)["rows"]
    if not rows:
        raise ValueError("a sheet with no row")
    return sheet.count(b"\n") + 1, list(rows)[-1]


@dataclass(frozen=True)
class SheetRead:
    """One Read call on the sheet: what it asked for and the text the model got back."""

    tool_use_id: str
    offset: int | None
    limit: int | None
    text: str | None
    is_error: bool = False
    path: str = ""


@dataclass
class Classed:
    """One read, classed against the sheet."""

    cls: str
    asked: int
    returned: int
    to_end: bool
    last_row: bool
    lines: frozenset[int] = field(default_factory=frozenset)


def _events(text: str) -> Iterable[dict[str, Any]]:
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def _content_text(content: Any) -> str:  # noqa: ANN401 - the stream's own content shape
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(b.get("text", ""))
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _int(value: Any) -> int | None:  # noqa: ANN401 - a tool input's own value
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _absolute(path: str, cwd: str) -> str:
    return os.path.normpath(path if os.path.isabs(path) or not cwd else os.path.join(cwd, path))


def sheet_reads(stream: str) -> list[SheetRead]:
    """Every Read call on the sheet in one stream, in order, each with the text returned for it."""
    asked: dict[str, tuple[int | None, int | None, str]] = {}
    order: list[str] = []
    got: dict[str, tuple[str, bool]] = {}
    cwd = ""
    for event in _events(stream):
        if event.get("type") == "system" and event.get("subtype") == "init":
            cwd = str(event.get("cwd") or "")
        message: dict[str, Any] = event["message"] if isinstance(event.get("message"), dict) else {}
        content: list[Any] = message["content"] if isinstance(message.get("content"), list) else []
        for block in content:
            if not isinstance(block, dict):
                continue
            if event.get("type") == "assistant" and block.get("type") == "tool_use":
                tool_input: dict[str, Any] = (
                    block["input"] if isinstance(block.get("input"), dict) else {}
                )
                path = str(tool_input.get("file_path", ""))
                if block.get("name") == "Read" and Path(path).name == SHEET_NAME:
                    tid = str(block.get("id"))
                    asked[tid] = (
                        _int(tool_input.get("offset")),
                        _int(tool_input.get("limit")),
                        _absolute(path, cwd),
                    )
                    order.append(tid)
            elif event.get("type") == "user" and block.get("type") == "tool_result":
                tid = str(block.get("tool_use_id"))
                if tid in asked and tid not in got:
                    got[tid] = (_content_text(block.get("content")), bool(block.get("is_error")))
    return [
        SheetRead(
            tid,
            asked[tid][0],
            asked[tid][1],
            got[tid][0] if tid in got else None,
            got[tid][1] if tid in got else False,
            asked[tid][2],
        )
        for tid in order
    ]


def returned_lines(text: str | None, first: int) -> frozenset[int]:
    """The numbered lines a text returned: consecutive numbers from ``first``, as given."""
    if not text:
        return frozenset()
    numbers = [int(m.group(1)) for line in text.split("\n") if (m := _NUMBERED.match(line))]
    found: list[int] = []
    expected = first
    for n in numbers:
        if n != expected:
            break
        found.append(n)
        expected += 1
    return frozenset(found)


def classify(
    read: SheetRead,
    total: int,
    last_row_id: str,
    earlier: Sequence[tuple[SheetRead, Classed]] = (),
) -> Classed:
    """R-PG-01b's class of one read of a sheet of ``total`` numbered lines."""
    start = read.offset if read.offset is not None and read.offset > 1 else 1
    end = total if read.limit is None else min(start + max(read.limit, 0) - 1, total)
    asked = max(0, end - start + 1)
    to_end = asked > 0 and end >= total
    if read.text is None:
        return Classed("no_result", asked, 0, to_end, False)
    if TOKEN_LIMIT.search(read.text):
        return Classed("cut", asked, 0, to_end, False)
    if read.text.startswith(UNCHANGED):
        wanted = frozenset(range(start, end + 1))
        held = any(
            e.path == read.path and c.cls in ("whole", "part") and wanted <= c.lines
            for e, c in earlier
        )
        return Classed("unchanged" if held else "cut", asked, 0, to_end, False)
    if read.is_error:
        return Classed("error", asked, 0, to_end, False)
    lines = returned_lines(read.text, start)
    returned = len(lines)
    last_row = f'"{last_row_id}"' in read.text
    if returned < asked or (to_end and not last_row):
        cls = "cut"
    elif start == 1 and to_end:
        cls = "whole"
    else:
        cls = "part"
    return Classed(cls, asked, returned, to_end, last_row, lines)


def session_reads_text(text: str, total: int, last_row_id: str) -> dict[str, Any]:
    """One stream's reads of the sheet, classed, with their counts."""
    done: list[tuple[SheetRead, Classed]] = []
    for read in sheet_reads(text):
        done.append((read, classify(read, total, last_row_id, done)))
    reads = [c for _, c in done]
    covered: frozenset[int] = frozenset().union(*(c.lines for c in reads)) if reads else frozenset()
    return {
        "missing": False,
        "reads": len(reads),
        **{cls: sum(c.cls == cls for c in reads) for cls in CLASSES},
        "covered_every_line": covered >= frozenset(range(1, total + 1)),
    }


def session_reads_in(root: Path, sid: str | None, total: int, last_row_id: str) -> dict[str, Any]:
    """One session's reads under a review root; ``missing`` if its stream is not there."""
    if not sid or not common.SESSION_ID.fullmatch(sid):
        return {"missing": True}
    data = common.read_inside(root, root / sid / STREAM[0] / STREAM[1])
    if data is None:
        return {"missing": True}
    return session_reads_text(data.decode(errors="replace"), total, last_row_id)


def _sessions(run: Path) -> dict[str, list[str | None]]:
    """Every review session a run's two logs name, by side: one per try."""
    found: dict[str, list[str | None]] = {}
    for side, log in (
        ("injected", run / "events.jsonl"),
        ("twin", run / "controls" / "events.jsonl"),
    ):
        ids: list[str | None] = []
        for line in common.read_log(log)[0]:
            if line.get("kind") == "review_ran":
                ids.append((line.get("result") or {}).get("session_id"))
            elif line.get("kind") == "review_unavailable":
                ids.append(line.get("session_id"))
        found[side] = ids
    return found


def block_counts(run: Path, scratch: Path, arm: str, sheet: bytes) -> dict[str, Any]:
    """§2.4's stream check for one arm of a block, per side; ``cut`` is the total of cut reads."""
    total, last = sheet_shape(sheet)
    logged = _sessions(run)
    roots = common.lane_roots(scratch)
    where: dict[str, Path] = {}
    refused = 0
    for root in roots:
        ids, links = common.session_dirs(root)
        refused += links
        for sid in ids:
            where.setdefault(sid, root)
    named = {sid for ids_ in logged.values() for sid in ids_ if sid}
    groups: dict[str, list[str | None]] = {
        **logged,
        "not_in_a_log": [s for s in sorted(where) if s not in named],
    }
    out: dict[str, Any] = {
        "arm": arm,
        "numbered_lines": total,
        "last_row_id": last,
        "sheet_sha256": common.sha256_bytes(sheet),
        "lane_roots": len(roots),
        "symlinks_refused": refused,
        "sides": {},
    }
    sides: dict[str, Any] = out["sides"]
    for side, named_ids in groups.items():
        rows = [
            session_reads_in(where[sid], sid, total, last) if sid in where else {"missing": True}
            for sid in named_ids
        ]
        present = [r for r in rows if not r["missing"]]
        sides[side] = {
            "reviews": len(rows),
            "stream_missing_unknown": len(rows) - len(present),
            "read_the_sheet": sum(r["reads"] > 0 for r in present),
            "never_read_it": sum(r["reads"] == 0 for r in present),
            "read_calls": sum(r["reads"] for r in present),
            **{cls: sum(r[cls] for r in present) for cls in CLASSES},
            "covered_every_line": sum(r["covered_every_line"] for r in present),
        }
    out["cut"] = sum(s["cut"] for s in out["sides"].values())
    return out


# ---------------------------------------------------------------- authoring streams


def author_end(stream: str, stderr: str = "", exit_code: int | None = None) -> dict[str, Any]:
    """How one authoring turn's stream ended: completed, usage_limit or infrastructure."""
    if "usage_limit_reached" in stream or "usage_limit_reached" in stderr:
        return {"ended": "usage_limit", "result_line": None}
    result: dict[str, Any] | None = None
    for event in _events(stream):
        if event.get("type") == "result":
            result = event
    if result is None:
        return {"ended": "infrastructure", "result_line": False, "exit": exit_code}
    subtype = result.get("subtype")
    if result.get("is_error") is False or subtype == "error_max_turns":
        return {"ended": "completed", "result_line": True, "subtype": subtype, "exit": exit_code}
    return {
        "ended": "infrastructure",
        "result_line": True,
        "subtype": subtype,
        "api_error_status": result.get("api_error_status"),
        "exit": exit_code,
    }


# ---------------------------------------------------------------- usage-limit facts


def limit_counts(paths: Iterable[Path]) -> dict[str, int]:
    """Files under ``paths`` that name a usage limit, and the 429 statuses in their streams."""
    files = statuses = 0
    for root in paths:
        root = Path(root)
        if not os.path.lexists(root):
            continue
        if not stat.S_ISDIR(os.lstat(root).st_mode):
            data = common.read_own(root)
            files += bool(data and LIMIT_WORD in data)
            continue
        for parts, mode in common.walk_inside(root):
            if not stat.S_ISREG(mode) or Path(parts[-1]).suffix not in LIMIT_SUFFIXES:
                continue
            data = common.read_inside(root, root.joinpath(*parts))
            if data is None:
                msg = f"{'/'.join(parts)} could not be read: a usage limit is not ruled out"
                raise common.FailClosedError(msg)
            files += LIMIT_WORD in data
            if parts[-1].endswith(".jsonl"):
                statuses += len(STATUS_429.findall(data))
    return {"usage_limit_files": files, "status_429s": statuses}


# ---------------------------------------------------------------- the smoke


def smoke(out: Path, root: Path, sheet: bytes) -> tuple[int, dict[str, Any]]:
    """One smoke review of the pilot design carrying ``sheet``: its reads, tokens and times."""
    for extra in ("tests", "tests/unit/evaluation"):
        path = str(common.REPO / extra)
        if path not in sys.path:
            sys.path.insert(0, path)
    import pilot_corpus
    from instrument_corpus import LABEL

    from physgate.evaluation.inject.corpus import Base, Patch
    from physgate.evaluation.inject.materialise import materialise, require_blind
    from physgate.evaluation.inject.runner import InstrumentParams, review_id
    from physgate.orchestrator import cli as orchestrator_cli
    from physgate.orchestrator.credentials import credential_for
    from physgate.orchestrator.decompose import binary_version
    from physgate.orchestrator.exceptions import ReviewUnavailableError
    from physgate.orchestrator.install import prepare_install
    from physgate.orchestrator.invocation import claude_binary
    from physgate.orchestrator.protocols import Artefact
    from physgate.orchestrator.trajectory import seal
    from physgate.reviewers.claude import ReviewerSetup, claude_reviewers
    from physgate.reviewers.places import require_review_root

    params = InstrumentParams.model_validate_json((common.HERE / "params_a.json").read_bytes())
    review_root = require_review_root(root)
    if review_root.exists():
        raise SystemExit("the smoke's review root exists: a smoke is never resumed")
    review_root.mkdir(parents=True)
    out.mkdir(parents=True)
    binary = claude_binary()
    version = binary_version(binary)
    install = out / "install"
    prepare_install(install, orchestrator_cli._project_root())
    library = orchestrator_cli._library_root()
    if library is None:
        raise SystemExit("no source checkout holds the rubrics")
    setup = ReviewerSetup(
        run_id="smoke-1",
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
    reviewer = claude_reviewers(setup)["electrical"]
    artefact = next(a for a in pilot_corpus.ARTEFACTS if a["id"] == "e1")
    base = Base(label=LABEL, nodes=tuple(pilot_corpus.BASE_NODES))
    patch = Patch(nodes=tuple(artefact["injected"]["nodes"]))
    subtask = review_id(0, "smoke-1")
    made = materialise(base, patch, review_root / "review" / subtask, sheet)
    require_blind(made, (str(artefact["id"]), str(artefact["description"])))
    sealed = seal(made.trajectory.read_bytes())
    attempt = Artefact(
        subtask_id=subtask,
        attempt=1,
        assigned_role="electrical",
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
    started = common.utc_now()
    try:
        session_id: str | None = reviewer.review(attempt).session_id
        ended_as = "verdict"
    except ReviewUnavailableError as exc:
        session_id, ended_as = exc.session_id, "review_unavailable"
    total, last = sheet_shape(sheet)
    reads = session_reads_in(review_root, session_id, total, last)
    data = common.read_inside(review_root, review_root / str(session_id) / STREAM[0] / STREAM[1])
    tokens = common.result_tokens(data.decode(errors="replace") if data else None)
    found = {
        "session_id": session_id,
        "ended_as": ended_as,
        "started_utc": started,
        "ended_utc": common.utc_now(),
        "binary_version": version,
        "sheet_sha256": common.sha256_bytes(sheet),
        "reads": reads,
        "tokens": tokens,
    }
    if reads.get("missing"):
        code, found["smoke"] = 1, "no stream: an infrastructure failure of the smoke"
    elif reads["cut"]:
        code, found["smoke"] = 3, "a cut read: the first block does not start"
    elif reads["whole"]:
        code, found["smoke"] = 0, "passed"
    else:
        code, found["smoke"] = 4, "no whole read of the sheet"
    (out / "smoke.json").write_text(json.dumps(found, indent=1, sort_keys=True) + "\n")
    return code, found


def main(argv: list[str] | None = None) -> int:
    """One subcommand; counts only."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("block")
    b.add_argument("--sheet", type=Path, required=True)
    b.add_argument("--arm", choices=common.ARMS, required=True)
    b.add_argument("--run", type=Path, required=True)
    b.add_argument("--scratch", type=Path, required=True)
    b.add_argument("--out", type=Path)
    a = sub.add_parser("author")
    a.add_argument("stream", type=Path)
    a.add_argument("--stderr", type=Path)
    a.add_argument("--exit", type=int)
    li = sub.add_parser("limits")
    li.add_argument("paths", type=Path, nargs="+")
    s = sub.add_parser("smoke")
    s.add_argument("--sheet", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.cmd == "block":
            found = block_counts(
                args.run.resolve(), args.scratch.resolve(), args.arm, args.sheet.read_bytes()
            )
            text = json.dumps(found, sort_keys=True)
            if args.out is not None:
                args.out.write_text(text + "\n")
            print(text)
            return 3 if found["cut"] else 0
        if args.cmd == "author":
            data = common.read_own(args.stream)
            err = common.read_own(args.stderr) if args.stderr is not None else None
            found = author_end(
                data.decode(errors="replace") if data else "",
                err.decode(errors="replace") if err else "",
                args.exit,
            )
            print(json.dumps(found, sort_keys=True))
            return 0
        if args.cmd == "limits":
            found = limit_counts(p.resolve() for p in args.paths)
            print(json.dumps(found, sort_keys=True))
            return 1 if found["usage_limit_files"] else 0
        code, found = smoke(args.out.resolve(), args.root.expanduser(), args.sheet.read_bytes())
        brief = {k: found[k] for k in ("smoke", "ended_as", "started_utc", "ended_utc", "tokens")}
        print(json.dumps({**brief, "reads": found["reads"]}, sort_keys=True))
        return code
    except common.FailClosedError as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
