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
ablation run's or a development run's number, and never adds counts across kinds.

**Nothing of a protected tier.** No answer carries the held-out tier's roots, canaries or
digests (``HELD_OUT_FIELDS``): not as a setting and not as a pin. A comparison is refused across
another held-out tier, and says only that it was.

**A run that cannot be read is a row, never a refused list.** Its configuration was rewritten
after the run started (its first line names another), its log holds a line this package could
not have written, or a file it reads is refused by the allowlist: its row holds the reader's
sentence, the record it came from and the reader's own reason, and nothing else. Every refusal
names the run by its place, never by a path on disk.

The routes:

- ``GET /api/evidence/runs``: one row per run the roots hold, with its kind, the settings a
  comparison reports beside its numbers (``REPORTED``), as recorded, and the pins it is refused
  across (``DRIFT``) less the held-out tier's digest.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from physgate.evaluation.observe.compare import DRIFT, REPORTED
from physgate.evaluation.observe.exceptions import ObserveError
from physgate.evaluation.observe.manifest import manifest_id_of
from physgate.orchestrator.events import read_events
from physgate.orchestrator.exceptions import OrchestratorError
from physgate.orchestrator.run_config import RunConfig, load_run_config
from physgate.ui.exceptions import PathRefusedError
from physgate.ui.readers import HELD_OUT_FIELDS
from physgate.ui.routes import Context, Response, Route, json_response, run_directories

#: How the run's files are named in its directory.
RUN_CONFIG = "run.json"
EVENTS = "events.jsonl"

#: A run's kind, read from its record: the two kinds it may name, and neither.
Kind = Literal["reportable", "ablation", "development"]

#: The settings a comparison reports beside its numbers, sent as the record holds them.
FLAGS: tuple[str, ...] = tuple(field for field in REPORTED if field not in HELD_OUT_FIELDS)
#: The pins a comparison is refused across, by path, less the held-out tier's digest: a digest
#: names the tier's bytes, and no answer carries it.
PINS: tuple[str, ...] = tuple(path for path in DRIFT if path not in HELD_OUT_FIELDS)

#: The parts of a reader's refusal a row may carry beside its sentence: where in the record it
#: failed and why. Every other part (a path on disk, a digest) is left out.
REFUSAL_CONTEXT = ("offset", "reason")


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


def refusal(record: str, exc: Refusal) -> dict[str, str]:
    """A reader's refusal as a row holds it: the sentence, the record, its place and reason."""
    context: Mapping[str, str] = getattr(exc, "context", {})
    kept = {key: str(context[key]) for key in REFUSAL_CONTEXT if key in context}
    return {"error": str(exc), "record": record, **kept}


def _run_row(context: Context, position: int, name: str, run_dir: Path) -> dict[str, object]:
    """One run's row: what it recorded and the manifest id its first line names, or why not."""
    row: dict[str, object] = {"root": position, "name": name}
    record = RUN_CONFIG
    try:
        config = load_run_config(context.allowlist.resolve(run_dir / RUN_CONFIG))
        record = EVENTS
        log = read_events(context.allowlist.resolve(run_dir / EVENTS))
        record = RUN_CONFIG
        manifest_id = manifest_id_of(run_dir, log)
    except (OrchestratorError, ObserveError, PathRefusedError) as exc:
        return row | refusal(record, exc)
    except FileNotFoundError:
        return row | {"error": "the run directory holds no event log", "record": EVENTS}
    recorded = config.model_dump(mode="json")
    return row | {
        "run_id": config.run_id,
        "seed": config.seed,
        "manifest_id": manifest_id,
        "kind": kind_of(config),
        "flags": {field: recorded[field] for field in FLAGS},
        "pins": {path: _at(recorded, path) for path in PINS},
    }


def runs(context: Context, params: Mapping[str, str]) -> Response:
    """Every run the roots hold, one row each: its kind, settings and pins, or why it is unread."""
    rows = [
        _run_row(context, position, name, run_dir)
        for position, name, run_dir in run_directories(context.allowlist)
    ]
    return json_response({"runs": rows})


#: Every route this module serves, registered by the command's composition root.
ROUTES: tuple[Route, ...] = (Route("GET", "/api/evidence/runs", "read", runs),)
