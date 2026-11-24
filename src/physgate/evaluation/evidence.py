"""The Evidence screen's read routes over the runs' records, registered beside the UI's own.

The routes live on the evaluation's side, and the command's composition root registers them in
the UI's served table: no module of the UI imports the evaluation, and the dependency runs from
the evaluation to the product. Each is a ``read`` route like the UI's own, so the request guard
holds every open it makes to the roots and refuses any write, connection or process; the same
sweeps walk them. Every file a route reads is first made real and held to the allowlist, then
handed to the reader the command line uses for that record.

**No number is born here and none in the browser.** Every figure a route answers is a reader's
answer over a run's records, sent with where it came from: the run's root position and directory
name, its run id and seed, the manifest id held to the digest its log's first line names
(``manifest_id_of``), and its kind. A run's kind is read from its record alone: ``reportable``,
``ablation``, or ``development`` when it is neither. A screen never makes a headline of an
ablation run's or a development run's number, and never adds counts across kinds. The one sum
made here is the spend's per role, sent as a view beside every row it adds.

**Nothing of a protected tier.** No answer carries the held-out tier's roots, canaries or
digests (``HELD_OUT_FIELDS``): not as a setting and not as a pin. A comparison is refused across
another held-out tier, and says only that it was.

**A run that cannot be read is a row, never a refused list.** Its configuration was rewritten
after the run started (its first line names another), its log holds a line this package could
not have written, or a file it reads is refused by the allowlist: its row holds the reader's
sentence, the record it came from and the reader's own reason, and nothing else. A route over
one or two runs refuses instead, with the same sentence: 403 for a file the allowlist refuses,
422 for a record that cannot be read. Every refusal names the run by its place, never by a path
on disk.

**What the fence does not admit, handed in.** A run's settings are sent as the comparison
classes them: the settings it reports beside its numbers, and the pins it is refused across.
Those lists, the comparison itself and the gate's catch count are handed in by the composition
root when it registers the routes (:class:`Census`, :func:`routes`). This module imports nothing
of the comparison's or the catch count's: it runs inside the UI's server, whose import fence
admits neither module. So the classing and the counting here are theirs by construction, never
a copy that could drift from them.

The routes:

- ``GET /api/evidence/runs``: one row per run the roots hold, with its kind, the settings a
  comparison reports beside its numbers, as recorded, and the pins it is refused across less the
  held-out tier's digest.
- ``GET /api/evidence/spend/{root}/{name}/{date}``: the run's cost line at that date's sheet, as
  the product's cost route serves it, and its priced calls grouped: each session's call with its
  subtask and attempt under the role its subtask was planned for, each role's sum a view;
  decomposition, review, routing and left-over sessions apart.
- ``GET /api/evidence/compare/{a_root}/{a_name}/{b_root}/{b_name}``: the comparison's side by
  side for the two runs, or its refusal naming every drifted setting by path and no value.
- ``GET /api/evidence/catches``: the catch count per kind of run, over that kind's runs alone,
  each kind with the runs it counted; the runs not read named apart.
- ``GET /api/evidence/gaps``: each role's gap trend as a person published it from the trend's
  one reader at a terminal, found under the role's name at the top of a root: no publication,
  the weeks as published with the time they were read, or a refusal in a sentence (the reader
  refused the trend, the file is not one its writer could have written, a link out of the
  roots, or a publication in more than one root). The server never runs the reader: its head
  and register lie beneath the role's withheld root, which no root may reach.
- ``GET /api/evidence/tiers``: each role's current tier version as a person published it from
  ``tiers status`` at a terminal, found under the role's name at the top of a root, as the gap
  trend is: no publication; the version id, the three tiers' task counts, the blind check's
  counts and source, the exposure word, the version's state, whether it was measured and when it
  was read; or a refusal in a fixed sentence. The record is closed and the answer copies its
  named fields alone, so nothing else a file held is ever served. The server never reads the
  store.
"""

from __future__ import annotations

import errno
import os
import stat
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from physgate.evaluation.observe.calls import run_calls, stream_seals
from physgate.evaluation.observe.cost import CallCost, CostLine, load_price_sheet, price_events
from physgate.evaluation.observe.exceptions import CompareRefusedError, ObserveError
from physgate.evaluation.observe.manifest import manifest_id_of
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.events import Event, SessionEnded, SubtaskPlanned, read_events
from physgate.orchestrator.exceptions import OrchestratorError
from physgate.orchestrator.gate_events import GateEvent, gate_events
from physgate.orchestrator.run_config import RunConfig, load_run_config
from physgate.ui.exceptions import GuardRefusedError, PathRefusedError
from physgate.ui.readers import HELD_OUT_FIELDS, run_dir_of
from physgate.ui.routes import Context, Response, Route, json_response, run_directories

#: How the run's files are named in its directory.
RUN_CONFIG = "run.json"
EVENTS = "events.jsonl"
#: What a refusal names as its record when a price sheet or a session's stream refused it.
PRICES = "prices"
STREAMS = "sessions"

#: A run's kind, read from its record: the two kinds it may name, and neither.
Kind = Literal["reportable", "ablation", "development"]
#: The kinds in the order a screen shows them: never an ablation first.
KINDS: tuple[Kind, ...] = ("reportable", "development", "ablation")


@dataclass(frozen=True)
class TrendCensus:
    """The published gap trend's own names, bound and parser, handed in by the root.

    ``roles``: the roles a trend is published for, in order; ``name``: the name a role's
    publication is found under at the top of a root; ``most``: the most of it read; ``parse``:
    its own parser, given the bytes and the role; ``refused``: what that parser refuses with.
    """

    roles: tuple[str, ...]
    name: Callable[[str], str]
    most: int
    parse: Callable[[bytes, str], BaseModel]
    refused: type[Exception]


@dataclass(frozen=True)
class TiersCensus:
    """The published tier status's own names, bound, parser and sentences, handed in by the root.

    ``roles``: the roles a status is published for, in order; ``name``: the name a role's
    publication is found under at the top of a root; ``most``: the most of it read; ``parse``:
    its own parser, given the bytes and the role; ``refused``: what that parser refuses with;
    ``said``: the fixed sentence for a role published as refused, by its word.
    """

    roles: tuple[str, ...]
    name: Callable[[str], str]
    most: int
    parse: Callable[[bytes, str], BaseModel]
    refused: type[Exception]
    said: Callable[[str], str]


@dataclass(frozen=True)
class Census:
    """What the comparison classes and how it compares, and the catch count, handed in.

    ``drift``: the settings two runs are refused across, by path; ``reported``: the settings it
    reports beside the numbers; ``compare``: the comparison itself; ``catches``: the gate's catch
    count over a set of gate events; ``trend``: the published gap trend's names and parser;
    ``tiers``: the published tier status's. The fence admits none of their modules, so the root
    hands them in at registration.
    """

    drift: tuple[str, ...]
    reported: tuple[str, ...]
    compare: Callable[[Path, Path], BaseModel]
    catches: Callable[[list[GateEvent]], Sequence[BaseModel]]
    trend: TrendCensus
    tiers: TiersCensus

    @property
    def flags(self) -> tuple[str, ...]:
        """The reported settings a row sends as the record holds them, less the held-out tier."""
        return tuple(field for field in self.reported if field not in HELD_OUT_FIELDS)

    @property
    def pins(self) -> tuple[str, ...]:
        """The pins a row sends, less the held-out tier's digest, which names the tier's bytes."""
        return tuple(path for path in self.drift if path not in HELD_OUT_FIELDS)


#: The parts of a reader's refusal a row may carry beside its sentence: where in the record it
#: failed and why. Every other part (a path on disk, a digest) is left out.
REFUSAL_CONTEXT = ("offset", "reason")


class RunRefusedError(ObserveError):
    """A run's records cannot be read as asked: named by its place and record, never a path."""


def kind_of(config: RunConfig) -> Kind:
    """The run's kind as its record names it: reportable, ablation, or neither."""
    if config.reportable:
        return "reportable"
    if config.ablation:
        return "ablation"
    return "development"


def _at(recorded: Mapping[str, Any], path: str) -> object:
    """The value of a recorded configuration at a dotted ``path``."""
    value: Any = recorded
    for part in path.split("."):
        value = value[part]
    return value


#: What a reader refuses a record with.
Refusal = OrchestratorError | ObserveError | PathRefusedError


def _place(position: int, name: str, record: str, exc: Refusal | None = None) -> dict[str, str]:
    """A refusal's context: the run's place, the record, and the reader's own place and reason."""
    context: Mapping[str, str] = {} if exc is None else getattr(exc, "context", {})
    kept = {key: str(context[key]) for key in REFUSAL_CONTEXT if key in context}
    return {"root": str(position), "name": name, "record": record, **kept}


def _refused(
    position: int, name: str, record: str, exc: Refusal
) -> PathRefusedError | RunRefusedError:
    """The same refusal named by place: a file refused by the allowlist stays one (a 403)."""
    if isinstance(exc, PathRefusedError):
        return PathRefusedError(str(exc), **_place(position, name, record, exc))
    return RunRefusedError(str(exc), **_place(position, name, record, exc))


def refusal(exc: PathRefusedError | RunRefusedError) -> dict[str, str]:
    """A refusal as a row holds it: the sentence, the record, its place in it and the reason."""
    kept = ("record", *REFUSAL_CONTEXT)
    return {"error": str(exc), **{key: exc.context[key] for key in kept if key in exc.context}}


@dataclass(frozen=True)
class _Run:
    """A run's records, read through the allowlist and held to its log's first line."""

    position: int
    name: str
    path: Path
    config: RunConfig
    log: list[Event]
    manifest_id: str


def _read(context: Context, position: int, name: str, run_dir: Path) -> _Run:
    """The run's configuration and log, and the manifest id its first line names.

    Raises:
        PathRefusedError: the allowlist refuses a file the run reads; named by place.
        RunRefusedError: a record cannot be read, or the log's first line names another
            configuration; named by place.
    """
    record = RUN_CONFIG
    try:
        config = load_run_config(context.allowlist.resolve(run_dir / RUN_CONFIG))
        record = EVENTS
        log = read_events(context.allowlist.resolve(run_dir / EVENTS))
        record = RUN_CONFIG
        manifest_id = manifest_id_of(run_dir, log)
    except (OrchestratorError, ObserveError, PathRefusedError) as exc:
        raise _refused(position, name, record, exc) from None
    except FileNotFoundError:
        msg = "the run directory holds no event log"
        raise RunRefusedError(msg, **_place(position, name, EVENTS)) from None
    return _Run(position, name, run_dir, config, log, manifest_id)


def _named(context: Context, root: str, name: str) -> _Run:
    """The run a request names by its root's position and name, read (404 if it is not there)."""
    run_dir = run_dir_of(context, {"root": root, "name": name})
    return _read(context, int(root), name, run_dir)


def _source(run: _Run) -> dict[str, object]:
    """Where a figure came from: the run's place, id, manifest id, kind and harness commit."""
    return {
        "root": run.position,
        "name": run.name,
        "run_id": run.config.run_id,
        "manifest_id": run.manifest_id,
        "kind": kind_of(run.config),
        "harness_commit": run.config.harness.commit,
        "harness_clean": run.config.harness.clean,
    }


def _run_row(
    census: Census, context: Context, position: int, name: str, run_dir: Path
) -> dict[str, object]:
    """One run's row: what it recorded and the manifest id its first line names, or why not."""
    row: dict[str, object] = {"root": position, "name": name}
    try:
        run = _read(context, position, name, run_dir)
    except (PathRefusedError, RunRefusedError) as exc:
        return row | refusal(exc)
    recorded = run.config.model_dump(mode="json")
    return row | {
        "run_id": run.config.run_id,
        "seed": run.config.seed,
        "manifest_id": run.manifest_id,
        "kind": kind_of(run.config),
        "flags": {field: recorded[field] for field in census.flags},
        "pins": {path: _at(recorded, path) for path in census.pins},
    }


@dataclass(frozen=True)
class Runs:
    """``GET /api/evidence/runs``: every run the roots hold, one row each, or why it is unread."""

    census: Census

    def __call__(self, context: Context, params: Mapping[str, str]) -> Response:
        """One row per run: its kind, settings and pins as the comparison classes them."""
        rows = [
            _run_row(self.census, context, position, name, run_dir)
            for position, name, run_dir in run_directories(context.allowlist)
        ]
        return json_response({"runs": rows})


# -- the spend -------------------------------------------------------------------------------

#: What a role's sum is, said beside it: the rows it adds are sent with it.
VIEW = "a view: each session's priced call, summed by the role its subtask was planned for"
#: The groups apart from the roles, by the attribution's kind; a session the log records no end
#: for (a left-over one, read at a resume) names no subtask and so no role.
APART: Mapping[str, str] = {
    "decomposition": "decomposition",
    "reviewer": "review",
    "routing": "routing",
}
LEFT_OVER = "left_over"


def _line(run: _Run, context: Context, date: str) -> CostLine:
    """The run's cost line at the sheet of ``date``, as the product's cost route prices it."""
    record = PRICES
    try:
        sheet = load_price_sheet(date)
        record = STREAMS
        attributions = TokenAccount.from_events(run.log).by_attribution()
        calls = run_calls(
            run.path, attributions, resolve=context.allowlist.resolve, seals=stream_seals(run.log)
        )
        record = PRICES
        return price_events(run.config, run.manifest_id, run.log, sheet, calls=calls)
    except (OrchestratorError, ObserveError, PathRefusedError) as exc:
        refused = _refused(run.position, run.name, record, exc)
        refused.context["date"] = date
        raise refused from None


def _sum(calls: Iterable[CallCost], named: frozenset[str]) -> dict[str, object] | None:
    """The calls' tokens and price summed, and whether any is a lower bound; ``None`` if none."""
    chosen = list(calls)
    if not chosen:
        return None
    tokens: dict[str, int] = {}
    for call in chosen:
        for key, count in call.tokens.model_dump().items():
            tokens[key] = tokens.get(key, 0) + count
    return {
        "tokens": tokens,
        "usd": str(sum(call.usd for call in chosen)),
        "lower_bound": any(call.attribution in named for call in chosen),
    }


def _row(call: CallCost, named: frozenset[str]) -> dict[str, object]:
    """One priced call as the line holds it, and whether the line names it unread."""
    return {**call.model_dump(mode="json"), "lower_bound": call.attribution in named}


def _spend(run: _Run, line: CostLine) -> dict[str, object]:
    """The line's calls grouped: each session under its subtask's role, the rest apart."""
    held = line.reconciliation
    named = frozenset(() if held is None else (*held.unread, *held.ttl_unread))
    role_of = {e.subtask_id: e.assigned_role for e in run.log if isinstance(e, SubtaskPlanned)}
    ended = {e.session_id: e for e in run.log if isinstance(e, SessionEnded)}
    roles: dict[str, list[tuple[CallCost, SessionEnded]]] = {}
    apart: dict[str, list[CallCost]] = {group: [] for group in (*APART.values(), LEFT_OVER)}
    for call in line.calls:
        kind, who = call.attribution.split(":", 1)
        end = ended.get(who) if kind == "session" else None
        if end is not None:
            roles.setdefault(role_of[end.subtask_id], []).append((call, end))
        else:
            apart[APART.get(kind, LEFT_OVER)].append(call)
    return {
        "view": VIEW,
        "roles": [
            {
                "role": role,
                "sum": _sum((call for call, _ in roles[role]), named),
                "sessions": [
                    {
                        **_row(call, named),
                        "session_id": end.session_id,
                        "subtask_id": end.subtask_id,
                        "attempt": end.attempt,
                        "outcome": end.outcome,
                    }
                    for call, end in roles[role]
                ],
            }
            for role in roles
        ],
        "apart": {
            group: {"sum": _sum(calls, named), "calls": [_row(call, named) for call in calls]}
            for group, calls in apart.items()
        },
    }


@dataclass(frozen=True)
class Spend:
    """``GET /api/evidence/spend/...``: the run's cost line, and each role's sessions as a view."""

    census: Census

    def __call__(self, context: Context, params: Mapping[str, str]) -> Response:
        """The line at the sheet of the date named, its calls grouped by role and apart."""
        run = _named(context, params["root"], params["name"])
        line = _line(run, context, params["date"])
        return json_response(
            {"source": _source(run), "line": line.model_dump(mode="json"), **_spend(run, line)}
        )


# -- the comparison --------------------------------------------------------------------------


@dataclass(frozen=True)
class Comparison:
    """``GET /api/evidence/compare/...``: the comparison's side by side, or its refusal."""

    census: Census

    def __call__(self, context: Context, params: Mapping[str, str]) -> Response:
        """Both runs held to the roots and their first lines, then compared by the comparison."""
        a = _named(context, params["a_root"], params["a_name"])
        b = _named(context, params["b_root"], params["b_name"])
        try:
            side_by_side = self.census.compare(a.path, b.path)
        except CompareRefusedError as exc:
            drifted = [path for path in exc.context.get("drifted", "").split(",") if path]
            answer = {"error": str(exc), "drifted": drifted, "a": _source(a), "b": _source(b)}
            return json_response(answer, 422)
        except (OrchestratorError, ObserveError) as exc:
            msg = "the two runs could not be compared"
            raise RunRefusedError(msg, **_place(a.position, a.name, "comparison", exc)) from None
        return json_response(
            {"a": _source(a), "b": _source(b), "comparison": side_by_side.model_dump(mode="json")}
        )


# -- the catch count -------------------------------------------------------------------------


@dataclass(frozen=True)
class Catches:
    """``GET /api/evidence/catches``: the catch count per kind of run, never added together."""

    census: Census

    def __call__(self, context: Context, params: Mapping[str, str]) -> Response:
        """Each kind's count over its own runs' gate events; the runs not read named apart."""
        runs: dict[Kind, list[dict[str, object]]] = {kind: [] for kind in KINDS}
        events: dict[Kind, list[GateEvent]] = {kind: [] for kind in KINDS}
        unread: list[dict[str, object]] = []
        for position, name, run_dir in run_directories(context.allowlist):
            try:
                run = _read(context, position, name, run_dir)
                found = gate_events(run.log, run.manifest_id)
            except (PathRefusedError, RunRefusedError) as exc:
                unread.append({"root": position, "name": name, **refusal(exc)})
                continue
            except OrchestratorError as exc:
                refused = RunRefusedError(str(exc), **_place(position, name, EVENTS, exc))
                unread.append({"root": position, "name": name, **refusal(refused)})
                continue
            kind = kind_of(run.config)
            runs[kind].append(_source(run))
            events[kind].extend(found)
        kinds = [
            {
                "kind": kind,
                "runs": runs[kind],
                "rows": [row.model_dump(mode="json") for row in self.census.catches(events[kind])],
            }
            for kind in KINDS
        ]
        return json_response({"kinds": kinds, "unread": unread})


# -- the gap trend ---------------------------------------------------------------------------


#: The reason a publication that is not a plain file of its own, or not to be read, is refused.
REFUSED = "publication_refused"

#: What the page shows of a trend line, and of a tier's count: all the route serves of either.
#: A line's run-set ids, its role, arm and second label, and a tier's raw counts are not shown,
#: so they are not sent.
LINE_SHOWN = ("week", "version", "measurements", "numbers", "unverified", "exposed_since")
COUNT_SHOWN = ("rate", "unscored", "flaky")
TIERS = ("visible", "validation", "held_out")


def _shown_line(line: Mapping[str, Any]) -> dict[str, object]:
    """A published trend line cut to what the page shows."""
    shown: dict[str, object] = {key: line[key] for key in LINE_SHOWN}
    numbers = line["numbers"]
    if numbers is not None:
        counts = {
            tier: None if numbers[tier] is None else {k: numbers[tier][k] for k in COUNT_SHOWN}
            for tier in TIERS
        }
        shown["numbers"] = {**numbers, **counts}
    return shown


def _shown_weeks(weeks: Iterable[Mapping[str, Any]]) -> list[dict[str, object]]:
    """The published weeks, each line cut to what the page shows."""
    return [{**week, "lines": [_shown_line(line) for line in week["lines"]]} for week in weeks]


def _published_bytes(context: Context, path: Path, most: int) -> bytes | None:
    """At most ``most + 1`` bytes of the publication at ``path``; ``None`` if it is not there.

    Judged by the allowlist first (a link out of the roots, toward the held-out tier or a
    credential, or a file with a second name, is refused before anything is opened), then opened
    never through a link and never waiting, and read only if what was opened is a regular file
    with one name on disk. A read route may open only absolute paths, so this opens the path
    itself, not a name beneath a directory's descriptor; the root is its parent, held real.

    Raises:
        PathRefusedError: any of those, in words.
    """
    context.allowlist.resolve(path)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            msg = "a link stands in its place, and a link is never followed to it"
            raise PathRefusedError(msg) from None
        msg = f"it cannot be opened ({os.strerror(exc.errno or 0)})"
        raise PathRefusedError(msg) from None
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise PathRefusedError("it is not a regular file, so nothing is read from it")
        if opened.st_nlink != 1:
            msg = "the file has more than one name on disk, so its other name may be refused"
            raise PathRefusedError(msg)
        chunks: list[bytes] = []
        size = 0
        while size <= most:
            chunk = os.read(fd, min(1 << 16, most + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        return b"".join(chunks)
    except OSError as exc:
        raise PathRefusedError(f"it cannot be read ({os.strerror(exc.errno or 0)})") from None
    finally:
        os.close(fd)


def _publications(context: Context, name: str, most: int) -> list[bytes]:
    """Every publication under ``name`` at the top of a root, each read as :func:`_published_bytes`.

    Raises:
        PathRefusedError: a place where one would lie is refused, in words.
    """
    found: list[bytes] = []
    for root in context.allowlist.roots:
        data = _published_bytes(context, root.path / name, most)
        if data is not None:
            found.append(data)
    return found


def _trend_refused(role: str, error: str, reason: str, read_at: object = None) -> dict[str, object]:
    """A role's trend that is not shown: the sentence, its reason, and when it was read, if so."""
    return {"role": role, "state": "refused", "error": error, "reason": reason, "read_at": read_at}


@dataclass(frozen=True)
class GapTrend:
    """``GET /api/evidence/gaps``: each role's published gap trend, or why it is not shown."""

    census: Census

    def __call__(self, context: Context, params: Mapping[str, str]) -> Response:
        """Per role, in order: no publication, its weeks as published, or a refusal."""
        return json_response({"roles": [self._role(context, r) for r in self.census.trend.roles]})

    def _role(self, context: Context, role: str) -> dict[str, object]:
        """The one publication of ``role`` at the top of a root, read by its own parser."""
        trend = self.census.trend
        try:
            found = _publications(context, trend.name(role), trend.most)
        except PathRefusedError as exc:
            return _trend_refused(role, f"the published gap trend is not read: {exc}", REFUSED)
        if not found:
            return {"role": role, "state": "none"}
        if len(found) > 1:
            msg = (
                f"two or more of the folders this server reads each hold a published gap trend of "
                f"the {role} role, so which one is meant cannot be told; keep it in one folder"
            )
            return _trend_refused(role, msg, "publications_more_than_one")
        try:
            published = trend.parse(found[0], role).model_dump(mode="json")
        except trend.refused as exc:
            reason = getattr(exc, "context", {}).get("refused_because", "publication_unreadable")
            return _trend_refused(role, str(exc), str(reason))
        refused = published["refused"]
        if refused is not None:
            error, reason = refused["error"], refused["refused_because"]
            return _trend_refused(role, error, reason, published["read_at"])
        return {
            "role": role,
            "state": "read",
            "read_at": published["read_at"],
            "weeks": _shown_weeks(published["weeks"]),
        }


# -- the tier status ---------------------------------------------------------------------------

#: The fields a published check's counts are served by, and the three tiers' counts.
CHECK_SHOWN = ("tasks", "all_yes", "left_out", "source")
#: How the request's guard ends its refusal of an open beyond the roots, as it words it.
OUTSIDE_THE_ROOTS = "outside the roots it may read"
#: Why a publication is not read when its place changed between the judgement and the open.
TIERS_SWAPPED = (
    "the published tier status is not read: its place changed while it was being read, so "
    "nothing of it was opened; load the page again"
)


def _shown_check(check: Mapping[str, Any] | None) -> dict[str, object] | None:
    """A published check cut to its named fields: none, its counts and source, or why refused."""
    if check is None:
        return None
    if "refused" in check:
        return {"refused": check["refused"]}
    return {key: check[key] for key in CHECK_SHOWN}


@dataclass(frozen=True)
class TierStatus:
    """``GET /api/evidence/tiers``: each role's published current tier version, or why not shown."""

    census: Census

    def __call__(self, context: Context, params: Mapping[str, str]) -> Response:
        """Per role, in order: no publication, its version as published, or a refusal."""
        return json_response({"roles": [self._role(context, r) for r in self.census.tiers.roles]})

    def _role(self, context: Context, role: str) -> dict[str, object]:
        """The one publication of ``role`` at the top of a root, read by its own parser.

        Every field served is named here and copied from what the parser read: nothing else a
        file held reaches the answer.
        """
        tiers = self.census.tiers
        try:
            found = _publications(context, tiers.name(role), tiers.most)
        except PathRefusedError as exc:
            return _trend_refused(role, f"the published tier status is not read: {exc}", REFUSED)
        except GuardRefusedError as exc:
            # The place was judged, then swapped before the open, and the request's guard refused
            # the open itself: nothing was read. Any other guard refusal is this package's fault.
            if exc.context.get("event") != "open" or not str(exc).endswith(OUTSIDE_THE_ROOTS):
                raise
            return _trend_refused(role, TIERS_SWAPPED, REFUSED)
        if not found:
            return {"role": role, "state": "none"}
        if len(found) > 1:
            msg = (
                f"two or more of the folders this server reads each hold a published tier status "
                f"of the {role} role, so which one is meant cannot be told; keep it in one folder"
            )
            return _trend_refused(role, msg, "publications_more_than_one")
        try:
            published = tiers.parse(found[0], role).model_dump(mode="json")
        except tiers.refused as exc:
            reason = getattr(exc, "context", {}).get("refused_because", "publication_unreadable")
            return _trend_refused(role, str(exc), str(reason))
        if "refused" in published:
            reason = str(published["refused"])
            return _trend_refused(role, tiers.said(reason), reason, published["read_at"])
        counts = published["counts"]
        return {
            "role": role,
            "state": "read",
            "read_at": published["read_at"],
            "version": published["version"],
            "counts": {tier: counts[tier] for tier in TIERS},
            "check": _shown_check(published["check"]),
            "exposure": published["exposure"],
            "version_state": published["version_state"],
            "measured": published["measured"],
        }


#: The path of the spend route over one run at one price sheet's date.
SPEND = "/api/evidence/spend/{root:index}/{name:name}/{date:date}"
#: The path of the comparison of a baseline run with a candidate.
COMPARE = "/api/evidence/compare/{a_root:index}/{a_name:name}/{b_root:index}/{b_name:name}"
#: The path of the catch count per kind of run.
CATCHES = "/api/evidence/catches"
#: The path of each role's published gap trend.
GAPS = "/api/evidence/gaps"
#: The path of each role's published current tier version.
TIERS_STATUS = "/api/evidence/tiers"


def routes(census: Census) -> tuple[Route, ...]:
    """Every route this module serves, over the census the root hands in.

    The same census gives equal routes, so the root's registration, run once per command, is
    the same registration each time.
    """
    return (
        Route("GET", "/api/evidence/runs", "read", Runs(census)),
        Route("GET", SPEND, "read", Spend(census)),
        Route("GET", COMPARE, "read", Comparison(census)),
        Route("GET", CATCHES, "read", Catches(census)),
        Route("GET", GAPS, "read", GapTrend(census)),
        Route("GET", TIERS_STATUS, "read", TierStatus(census)),
    )
