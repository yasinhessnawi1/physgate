"""A run's sequences as a rerun compares them, and the first place two runs part.

What "reproduces" means is set by what is controllable, and stated here in code.
The binary exposes no seed and no temperature, so there are two levels:

- **exact**, for a run whose model calls went to a scripted endpoint on this
  machine (a loopback address) or to no endpoint at all. Every record must match
  after a normalisation of exactly the fields that differ between two runs of
  one brief and seed by construction, measured, not assumed:

  - *mapped:* the run id and the run directory to placeholders; each session id
    to its order of first appearance; each commit id to its git tree, since a
    commit id carries its commit time;
  - *dropped:* ``ts`` on every line; the ``seconds`` a worktree removal and the
    installation check took; a token line's ``message_id``; the scratch
    ``graph_root`` of a proposal check; a review's usage ``message_id``s; a
    trajectory's seal, whose stream carries
    uuids and durations by design; and the first line's configuration digest,
    which is replaced by comparing the two configurations with the run id mapped.

  Then these must be equal: the configuration, every event line field by field,
  the ledger, the approval queue and its decisions, the graph journal raw, and
  the tree of every commit on the run's branches and in its store repository.

- **decisions**, for a run on a real model. Its prompt differs between reruns
  (the binary's own context names the run's branch, a short commit id and the
  date) and it has no seed, so what must match is the sequence of decisions
  only: each planned subtask; per attempt the gate verdict and failing check, or
  why the gate was skipped, the review verdict, and how the attempt ended; the
  integration gate; and a halt. Tokens, trees, trajectories and durations are
  reported as measured differences and never scored.

The lists below are data. Adding a field to them after comparisons exist changes
what those comparisons meant, so it is a decision, not an edit.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from physgate.evaluation.observe.exceptions import ManifestError
from physgate.orchestrator.exceptions import GitError
from physgate.orchestrator.git import git
from physgate.orchestrator.run_config import RunConfig

Level = Literal["exact", "decisions"]
#: Where a position in a record stands in the run: event line, subtask, attempt, stage.
Position = tuple[int | None, str | None, int | None, str | None]

#: Dropped before an exact comparison: on every line, and per event kind.
DROPPED_EVERYWHERE: frozenset[str] = frozenset({"ts"})
DROPPED: dict[str, frozenset[str]] = {
    "worktree_removed": frozenset({"seconds"}),
    "install_checked": frozenset({"seconds"}),
    "tokens_used": frozenset({"message_id"}),
    "proposals_checked": frozenset({"graph_root"}),
    "session_ended": frozenset({"trajectory_seal"}),
    "leftover_read": frozenset({"trajectory_seal"}),
    "run_started": frozenset({"config_sha256"}),
}
#: Dropped at a path inside a line, per event kind; ``*`` stands for every item of
#: a list. A review's message ids are random on any real API, like a token line's.
DROPPED_AT: dict[str, tuple[tuple[str, ...], ...]] = {
    "review_ran": (("result", "usage", "*", "message_id"),),
}

#: The records of an exact comparison, in the order a divergence is looked for.
RECORDS: tuple[str, ...] = (
    "config",
    "events",
    "ledger",
    "queue",
    "queue_decisions",
    "journal",
    "git",
)

#: A field one line has and the other does not, as a divergence shows it.
_ABSENT = "<absent>"
_FIRST = ("kind", "step")
_COMMIT = re.compile(r"\b[0-9a-f]{40}\b")
_LOOPBACK = re.compile(r"^https?://(127\.\d+\.\d+\.\d+|localhost|\[::1\])(:\d+)?(/.*)?$")


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Divergence(_Frozen):
    """The first place two runs' records part, and where in the run it was."""

    record: str
    #: The line's position in its record.
    index: Annotated[int, Field(ge=0)]
    #: The event line the position stands for: for the event log its own sequence
    #: number, for a decision the line that made it.
    seq: Annotated[int, Field(ge=0)] | None
    #: The first field that differs, as a dotted path; ``None`` when one run has no
    #: line at this position.
    field: str | None
    recorded: str | None
    rerun: str | None
    subtask_id: str | None
    attempt: Annotated[int, Field(ge=1)] | None
    #: The stage the attempt was in when the lines parted.
    stage: str | None


def level_of(config: RunConfig) -> Level:
    """How a run is compared: exactly when no real model answered it."""
    return "exact" if _LOOPBACK.match(config.endpoint) else "decisions"


def _lines(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for raw in path.read_text().splitlines():
        if raw.strip():
            line = json.loads(raw)
            if not isinstance(line, dict):
                msg = "a record holds a line that is not an object"
                raise ManifestError(msg, path=str(path))
            out.append(line)
    return out


def _walk(value: Any) -> Iterator[tuple[str, Any]]:  # noqa: ANN401 - JSON of any shape
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


class RunView:
    """A run as an exact comparison reads it: its records with the measured normalisation."""

    def __init__(self, run_dir: Path) -> None:
        """Read the run's identity, its sessions in order and its commits' trees."""
        self.run_dir = Path(run_dir).resolve()
        try:
            self.config: dict[str, Any] = json.loads((self.run_dir / "run.json").read_text())
        except FileNotFoundError:
            msg = "the run directory holds no configuration"
            raise ManifestError(msg, run_dir=str(self.run_dir)) from None
        self.run_id: str = self.config["run_id"]
        self.events = _lines(self.run_dir / "events.jsonl")
        self.sessions: dict[str, str] = {}
        for line in self.events:
            for key, value in _walk(line):
                sid = value.split(":", 1)[1] if key == "attribution" else value
                if key in ("session_id", "attribution") and sid not in self.sessions:
                    self.sessions[sid] = f"<session {len(self.sessions) + 1}>"
        self.trees: dict[str, str] = {}
        for repo in self._repositories():
            for row in git(repo, "log", "--all", "--format=%H %T").splitlines():
                commit, tree = row.split()
                self.trees[commit] = tree
        self._names: dict[str, str] = {
            str(self.run_dir): "<run-dir>",
            **self.sessions,
            self.run_id: "<run>",
        }
        longest_first = sorted(self._names, key=len, reverse=True)
        self._pattern = re.compile("|".join([*map(re.escape, longest_first), _COMMIT.pattern]))

    def _repositories(self) -> list[Path]:
        return [
            repo
            for repo in (self.run_dir / "worktrees" / "_integration", self.run_dir / "store")
            if (repo / ".git").exists()
        ]

    def text(self, value: str) -> str:
        """``value`` with the run's own identifiers replaced by what they stand for.

        One pass, the longest name first, so a placeholder already written is never
        rewritten: a run id such as ``run-d`` occurs inside ``<run-dir>``.
        """

        def swap(found: re.Match[str]) -> str:
            name = found[0]
            if name in self._names:
                return self._names[name]
            return f"<tree {self.trees[name]}>" if name in self.trees else name

        return self._pattern.sub(swap, value)

    def value(self, value: Any) -> Any:  # noqa: ANN401 - JSON of any shape
        """``value`` normalised throughout."""
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, list):
            return [self.value(item) for item in value]
        if isinstance(value, dict):
            return {self.text(k): self.value(v) for k, v in value.items()}
        return value

    def line(self, line: dict[str, Any]) -> dict[str, Any]:
        """One line with the dropped fields removed and the rest normalised."""
        kind = str(line.get("kind"))
        dropped = DROPPED_EVERYWHERE | DROPPED.get(kind, frozenset())
        kept: Any = {k: v for k, v in line.items() if k not in dropped}
        for path in DROPPED_AT.get(kind, ()):
            kept = _drop_at(kept, path)
        normalised: dict[str, Any] = self.value(kept)
        return normalised

    def git_trees(self) -> list[dict[str, Any]]:
        """Every branch of the run, and the store repository, as the trees of its commits."""
        out = []
        repos = self._repositories()
        integration = self.run_dir / "worktrees" / "_integration"
        if integration in repos:
            prefix = f"refs/heads/physgate/{self.run_id}/"
            refs = git(integration, "for-each-ref", "--format=%(refname)", prefix).split()
            for ref in sorted(refs):
                # Graph order: commits of one second would otherwise order by chance.
                trees = git(integration, "log", "--topo-order", "--format=%T", ref).split()
                out.append({"ref": self.text(ref), "trees": trees})
        store = self.run_dir / "store"
        if store in repos:
            try:
                trees = git(store, "log", "--topo-order", "--format=%T").split()
                out.append({"ref": "store", "trees": trees})
            except GitError:  # a store repository with no commit yet
                out.append({"ref": "store", "trees": []})
        return out

    def records(self) -> dict[str, list[dict[str, Any]]]:
        """The records of an exact comparison, normalised, by name."""
        journal = self.run_dir / "store" / "journal.jsonl"
        return {
            "config": [self.value(self.config)],
            "events": [self.line(e) for e in self.events],
            "ledger": [self.line(e) for e in _lines(self.run_dir / "ledger.jsonl")],
            "queue": [self.line(e) for e in _lines(self.run_dir / "queue.jsonl")],
            "queue_decisions": [
                self.line(e) for e in _lines(self.run_dir / "queue_decisions.jsonl")
            ],
            "journal": [
                {"raw": raw}
                for raw in (journal.read_text().splitlines() if journal.exists() else [])
            ],
            "git": self.git_trees(),
        }


def _drop_at(value: Any, path: tuple[str, ...]) -> Any:  # noqa: ANN401 - JSON of any shape
    """``value`` without the field at ``path``; a missing step leaves it as it is."""
    if not path:
        return value
    head, rest = path[0], path[1:]
    if head == "*":
        return [_drop_at(item, rest) for item in value] if isinstance(value, list) else value
    if not isinstance(value, dict) or head not in value:
        return value
    if not rest:
        return {k: v for k, v in value.items() if k != head}
    return {**value, head: _drop_at(value[head], rest)}


def _flat(value: Any, prefix: str = "") -> dict[str, Any]:  # noqa: ANN401 - JSON of any shape
    if isinstance(value, dict) and value:
        out: dict[str, Any] = {}
        for key, item in value.items():
            out.update(_flat(item, f"{prefix}.{key}" if prefix else key))
        return out
    if isinstance(value, list) and value:
        out = {}
        for i, item in enumerate(value):
            out.update(_flat(item, f"{prefix}[{i}]"))
        return out
    return {prefix: value}


def first_divergence(
    record: str,
    recorded: Sequence[dict[str, Any]],
    rerun: Sequence[dict[str, Any]],
    where: Callable[[int], Position] | None = None,
) -> Divergence | None:
    """The first line at which two runs' records differ, and its first differing field.

    ``where`` names the event line, subtask, attempt and stage a position stands for.
    """
    for index in range(max(len(recorded), len(rerun))):
        mine = recorded[index] if index < len(recorded) else None
        theirs = rerun[index] if index < len(rerun) else None
        if mine == theirs:
            continue
        field = None
        if mine is not None and theirs is not None:
            fm, ft = _flat(mine), _flat(theirs)
            # What a line is comes first: a different kind or step says more than any field.
            keys = sorted(fm.keys() | ft.keys(), key=lambda k: (k not in _FIRST, k))
            field = next(k for k in keys if fm.get(k, _ABSENT) != ft.get(k, _ABSENT))
        seq, subtask, attempt, stage = where(index) if where else (None, None, None, None)
        return Divergence(
            record=record,
            index=index,
            seq=seq,
            field=field,
            recorded=None if mine is None else json.dumps(_pick(mine, field), sort_keys=True),
            rerun=None if theirs is None else json.dumps(_pick(theirs, field), sort_keys=True),
            subtask_id=subtask,
            attempt=attempt,
            stage=stage,
        )
    return None


def _pick(line: dict[str, Any], field: str | None) -> Any:  # noqa: ANN401 - JSON of any shape
    return line if field is None else _flat(line).get(field, _ABSENT)


def event_position(
    events: Sequence[dict[str, Any]], seqs: Sequence[int] | None = None
) -> Callable[[int], Position]:
    """For a position in a record drawn from ``events``: its line, subtask, attempt and stage.

    ``seqs`` maps each position to the event line it came from; by default a
    position is the line itself.
    """
    by_seq = {line.get("seq"): i for i, line in enumerate(events)}

    def where(index: int) -> Position:
        if seqs is not None:
            if index >= len(seqs):
                return None, None, None, None
            index = by_seq[seqs[index]]
        if index >= len(events):
            return None, None, None, None
        line = events[index]
        subtask, attempt = line.get("subtask_id"), line.get("attempt")
        stage = None
        for earlier in events[: index + 1]:
            if (
                earlier.get("kind") == "stage_entered"
                and earlier.get("subtask_id") == subtask
                and earlier.get("attempt") == attempt
            ):
                stage = earlier.get("stage")
        seq = line.get("seq")
        return (
            seq if isinstance(seq, int) else None,
            subtask if isinstance(subtask, str) else None,
            attempt if isinstance(attempt, int) else None,
            stage if isinstance(stage, str) else None,
        )

    return where


def decisions(events: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """The run's decisions in log order, each with the sequence number that made it."""
    out: list[dict[str, Any]] = []
    for e in events:
        kind, at = e.get("kind"), {"subtask_id": e.get("subtask_id"), "attempt": e.get("attempt")}
        step: dict[str, Any] | None = None
        if kind == "subtask_planned":
            step = {"step": "planned", "subtask_id": e["subtask_id"]}
        elif kind == "gate_ran":
            result = e["result"]
            step = {"step": "gate", **at, "verdict": result["verdict"]}
            step["failing_check"] = result["failing_check"]
        elif kind == "gate_skipped":
            step = {"step": "gate_skipped", **at, "reason": e["reason"]}
        elif kind == "review_ran":
            step = {"step": "review", **at, "verdict": e["result"]["verdict"]}
        elif kind == "merged":
            step = {"step": "merged", **at}
        elif kind == "attempt_rejected":
            step = {"step": "rejected", **at, "finding_key": e["finding_key"]}
        elif kind == "escalated":
            step = {"step": "escalated", "subtask_id": e["subtask_id"]}
        elif kind == "session_ended" and e["outcome"] == "infrastructure":
            step = {"step": "infrastructure", **at, "cause": e["cause"]}
        elif kind == "incident":
            step = {"step": "incident", "subtask_id": e["subtask_id"], "cause": e["cause"]}
        elif kind == "integration_gate_ran":
            result = e["result"]
            step = {"step": "integration_gate", "verdict": result["verdict"]}
            step["failing_check"] = result["failing_check"]
        elif kind == "integration_gate_skipped":
            step = {"step": "integration_skipped", "reason": e["reason"]}
        elif kind == "integration_escalated":
            step = {"step": "integration_escalated"}
        elif kind == "halted":
            step = {"step": "halted", "reason": e["reason"]}
        if step is not None:
            out.append({**step, "seq": e["seq"]})
    return out
