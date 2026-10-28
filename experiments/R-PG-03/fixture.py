"""R-PG-03's tests only: invented sets, real runs with scripted stand-in reviewers, invented logs.

Nothing here is read by a script of the run, and nothing here is a set of the experiment. The set
is the instrument's own four-role test design (``pilot_corpus``: one revision per role, a control
unit error, an electrical magnitude error, a firmware propagation error and a mechanical unit
error, each with a clean twin the gate passes), carrying the edited authors' table as its
``parts_sheet.md``, as every corpus of this experiment does. The set named for block ``s`` is the
same design with every error of the instrument's ``standard`` class (and so with no edge), since
that corpus holds that class alone. The runs are real ``run_instrument`` runs whose reviews are
scripted per item and arm: each review line carries its arm's rubric digest for its role, and
nothing is called.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
for _p in (HERE, REPO / "tests", REPO / "tests" / "unit" / "evaluation"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import common  # noqa: E402
import pilot_corpus  # noqa: E402
from instrument_corpus import LABEL, SOURCE_ROWS, write_corpus  # noqa: E402

from physgate.evaluation.inject.corpus import (  # noqa: E402
    load_corpus,
    manifest_for,
    write_manifest,
)
from physgate.evaluation.inject.runner import control_id, review_id, run_instrument  # noqa: E402
from physgate.orchestrator.exceptions import ReviewUnavailableError  # noqa: E402
from physgate.orchestrator.protocols import (  # noqa: E402
    Artefact,
    ItemVerdict,
    MessageUsage,
    ReviewResult,
    SpecDefect,
    Usage,
)

#: The token's variable and prefix, spelt in parts so that no line reads as a credential; and an
#: obvious dummy of the token's shape, never a credential.
TOKEN_NAME = "CLAUDE_CODE_OAUTH" + "_TOKEN"
TOKEN_PREFIX = "sk-ant-" + "oat01-"
DUMMY_TOKEN = TOKEN_PREFIX + "DUMMY-not-a-credential-" + "0" * 10
#: The test design's items: id, role, class.
ITEMS = {
    "c1": ("control", "unit"),
    "e1": ("electrical", "magnitude"),
    "f1": ("firmware", "propagation"),
    "k1": ("mechanical", "unit"),
}
SECTION2 = "domain_standards"
SECTION1 = "acceptance_criteria"


def refuses(
    kind: type[Exception] | tuple[type[Exception], ...], pattern: str, call: Callable[[], object]
) -> None:
    """The call is refused with ``kind`` and a message ``pattern`` finds.

    Another message, or no refusal, fails on an assertion; any other exception is not caught.
    """
    try:
        call()
    except kind as exc:
        assert re.search(pattern, str(exc)), f"{type(exc).__name__}: {exc}"
        return
    raise AssertionError(f"not refused ({kind}: {pattern})")


def holds(call: Callable[[], Any], *refusals: type[Exception]) -> Any:  # noqa: ANN401
    """The call returns: one of ``refusals`` fails on an assertion; any other is not caught."""
    try:
        return call()
    except refusals as exc:
        raise AssertionError(f"refused: {type(exc).__name__}: {exc}") from exc


def token_line(value: str, before: str = "", between: str = "=") -> str:
    """An env file's line for the token: ``before``, the name, ``between``, ``value``."""
    return f"{before}{TOKEN_NAME}{between}{value}"


def edited_table() -> bytes:
    """The edited authors' table, as every corpus and packet of this experiment carries it."""
    import sheet_check

    table, _ = sheet_check.table_facts(REPO)
    return table


def as_standard(artefact: Mapping[str, Any]) -> dict[str, Any]:
    """One of the test design's artefacts as one of the ``standard`` class, which names no edge."""
    return {**artefact, "error_class": "standard", "edge": None}


def write_set(root: Path, label: str = LABEL, standard: bool = False) -> Path:
    """The four-role test design, with the edited authors' table as its ``parts_sheet.md``.

    With ``standard``, every artefact is of the ``standard`` class, as block ``s``'s corpus is.
    """
    if standard:
        write_corpus(
            root,
            artefacts=tuple(as_standard(a) for a in pilot_corpus.ARTEFACTS),
            base_nodes=pilot_corpus.BASE_NODES,
            author=pilot_corpus.AUTHOR,
            rows=dict(SOURCE_ROWS),
            sheet_indent=1,
        )
    else:
        pilot_corpus.write_pilot_corpus(root)
    author = json.loads((root / "MANIFEST.json").read_text())["author_model"]
    (root / "MANIFEST.json").unlink()
    (root / common.TABLE_NAME).write_bytes(edited_table())
    write_manifest(root, manifest_for(root, label=label, author_model=author))
    load_corpus(root)
    return root


def write_sets(base: Path, names: list[str]) -> Path:
    """One test set under each corpus name, in one sets directory; block ``s``'s is ``standard``."""
    for name in names:
        standard = name == common.BLOCK_CORPUS["s"]
        write_set(base / name, label=f"a test set named {name}", standard=standard)
    return base


# ---------------------------------------------------------------- scripted reviewers

#: One review's script: ("pass",), ("fail", [(item, section, evidence)], failing item),
#: ("blocked",) or ("unavailable", cause).
Script = tuple[Any, ...]


def _usage(n: int) -> tuple[MessageUsage, ...]:
    return (
        MessageUsage(
            message_id=f"msg-{n}",
            usage=Usage(
                input_tokens=10,
                output_tokens=20,
                cache_read_input_tokens=30,
                cache_creation_input_tokens=40,
            ),
        ),
    )


def session_of(n: int) -> str:
    """A session id of the instrument's form, made from a number."""
    return f"00000000-0000-4000-8000-{n:012d}"


@dataclass
class Scripted:
    """A stand-in reviewer of one arm answering each item from its script, by the item's run id."""

    scripts: Mapping[str, Script]
    arm: str
    role: str
    model: str = common.REVIEWER_MODEL
    seen: list[str] = field(default_factory=list)
    counter: list[int] = field(default_factory=lambda: [0])

    def review(self, artefact: Artefact) -> ReviewResult:
        """The item's scripted review, carrying the arm's rubric digest for the role."""
        self.counter[0] += 1
        n = self.counter[0] + 1000 * common.ARMS.index(self.arm)
        self.seen.append(artefact.subtask_id)
        script = self.scripts.get(artefact.subtask_id, ("pass",))
        digest = common.RUBRIC_SHA256[self.arm][self.role]
        if script[0] == "unavailable":
            raise ReviewUnavailableError(
                "scripted",
                cause=script[1],
                session_id=session_of(n),
                reviewer_model=self.model,
                usage=_usage(10_000 + n),
            )
        if script[0] == "blocked":
            return ReviewResult(
                verdict="blocked",
                finding="no load is given for the safety check",
                reviewer_model=self.model,
                session_id=session_of(n),
                usage=_usage(n),
                spec_defects=(SpecDefect(finding="no load is given", blocking=True),),
                rubric_sha256=digest,
            )
        if script[0] == "pass":
            return ReviewResult(
                verdict="pass",
                finding="every item is met",
                reviewer_model=self.model,
                session_id=session_of(n),
                usage=_usage(n),
                rubric_sha256=digest,
            )
        _, items, failing = script
        return ReviewResult(
            verdict="fail",
            finding="a rejecting item is unmet in the revision",
            reviewer_model=self.model,
            session_id=session_of(n),
            usage=_usage(n),
            failing_item=failing,
            items=tuple(
                ItemVerdict(item=i, section=s, result="unmet", evidence=e) for i, s, e in items
            ),
            rubric_sha256=digest,
        )


def scripts_for(seed: int, by_item: Mapping[str, tuple[Script, Script]]) -> dict[str, Script]:
    """Each item's (injected, twin) scripts under the run ids the seed gives them."""
    out: dict[str, Script] = {}
    for aid, (injected, twin) in by_item.items():
        out[review_id(seed, aid)] = injected
        out[control_id(seed, aid)] = twin
    return out


def real_run(
    set_dir: Path,
    into: Path,
    seed: int,
    arm: str,
    by_item: Mapping[str, tuple[Script, Script]],
    lanes: int | None = None,
) -> Path:
    """A real instrument run of one arm over ``set_dir``, its reviews scripted; the run dir."""
    corpus = load_corpus(set_dir)
    lanes = common.LANES[arm] if lanes is None else lanes
    scripts = scripts_for(seed, by_item)
    counter = [0]

    def reviewers() -> dict[str, Scripted]:
        return {r: Scripted(scripts, arm, r, counter=counter) for r in pilot_corpus.ROLES}

    run_instrument(
        corpus,
        reviewers(),
        run_dir=into / "run",
        scratch=into / "scratch",
        run_id=f"fixture-{seed}-{arm}",
        seed=seed,
        review_clean_twins=True,
        lanes=lanes,
        lane_reviewers=[reviewers() for _ in range(lanes)] if lanes > 1 else None,
        reviewer_kind=common.ARM_KIND[arm],  # type: ignore[arg-type]
        progress=lambda _line: None,
    )
    return into / "run"


def fail(*items: tuple[str, str, str], failing: str | None = None) -> Script:
    """A failing review's script: its unmet items, and its failing item (the first if not named)."""
    return ("fail", list(items), failing or items[0][0])


def write_blocks(
    records: Path, attempts: list[dict[str, Any]], not_run: dict[str, str] | None = None
) -> Path:
    """A block record of the launch's form."""
    records.mkdir(parents=True, exist_ok=True)
    path = records / "blocks.json"
    path.write_text(json.dumps({"attempts": attempts, "not_run": not_run or {}}, indent=1))
    return path


def attempt(block: str, runs: dict[str, Path], valid: bool = True, cut: int = 0) -> dict[str, Any]:
    """One attempt of a block, as the launch records it."""
    return {
        "block": block,
        "attempt": 1,
        "started_utc": "2026-11-05T08:00:00Z",
        "ended_utc": "2026-11-05T10:00:00Z",
        "runs": {arm: str(path) for arm, path in runs.items()},
        "scratch": {arm: str(path.parent / "scratch") for arm, path in runs.items()},
        "valid": valid,
        "stream_check": {"cut": cut},
    }


def copy_run(src: Path, dst: Path) -> Path:
    """A run directory copied whole."""
    shutil.copytree(src, dst)
    return dst


# ---------------------------------------------------------------- invented streams


def read_call(
    tid: str, path: str, offset: int | None = None, limit: int | None = None
) -> dict[str, Any]:
    """An assistant event: one Read call."""
    tool_input: dict[str, Any] = {"file_path": path}
    if offset is not None:
        tool_input["offset"] = offset
    if limit is not None:
        tool_input["limit"] = limit
    return {
        "type": "assistant",
        "message": {
            "model": common.REVIEWER_MODEL,
            "content": [{"type": "tool_use", "id": tid, "name": "Read", "input": tool_input}],
        },
    }


def tool_result(tid: str, text: str, is_error: bool = False) -> dict[str, Any]:
    """A user event: one tool result."""
    return {
        "type": "user",
        "message": {
            "content": [
                {"type": "tool_result", "tool_use_id": tid, "content": text, "is_error": is_error}
            ]
        },
    }


def numbered(sheet: bytes, first: int = 1, last: int | None = None) -> str:
    """A sheet's lines as the Read tool numbers them, from ``first`` to ``last``."""
    lines = sheet.decode().split("\n")
    last = len(lines) if last is None else last
    return "\n".join(f"{n}\t{lines[n - 1]}" for n in range(first, last + 1))


def stream(*events: dict[str, Any], result: dict[str, Any] | None = None) -> str:
    """A stream of events, with a ``result`` line at its end unless ``result`` is empty."""
    lines = [json.dumps({"type": "system", "subtype": "init", "cwd": "/w"})]
    lines += [json.dumps(e) for e in events]
    if result is None:
        result = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "session_id": "s",
            "usage": {
                "input_tokens": 1,
                "output_tokens": 2,
                "cache_read_input_tokens": 3,
                "cache_creation_input_tokens": 4,
            },
        }
    if result:
        lines.append(json.dumps(result))
    return "\n".join(lines) + "\n"
