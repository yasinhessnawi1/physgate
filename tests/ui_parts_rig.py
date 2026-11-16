"""The runs the operator UI's parts decision is tested on in a browser, and the drive after it.

ARCH-122. Each run is the scripted run on the reference brief that asks which parts a person
has (``unit/orchestrator/reference_parts_run.py``): the real loop, store, git and physics gate,
a stand-in decomposition with six components, stand-in sessions and reviewer, no model. It is
started and driven to its hold, where every part's item is open and nothing is dispatched. The
browser decides the parts through the page; then this module, run as a script, drives the run
once more, as ``physgate run`` would, so the page can show the run released.

Usage, after the browser decided every part: ``uv run python tests/ui_parts_rig.py <dir> <run>``,
where ``<dir>`` is the directory ``ui_e2e_runs.py`` built. It prints the step the run ended on.
"""

from __future__ import annotations

import sys
from pathlib import Path

#: Where the reference run's module and the observability tests' rig it builds on are kept.
for _tests in ("orchestrator", "evaluation"):
    _where = str(Path(__file__).resolve().parent / "unit" / _tests)
    if _where not in sys.path:
        sys.path.insert(0, _where)

import observe_rig  # noqa: E402 - importable once its directory is on the path
import reference_parts_run as ref  # noqa: E402
from knowledge_fixture import build_fixture_library  # noqa: E402

from physgate.orchestrator.decompose import start_run  # noqa: E402
from physgate.orchestrator.run_config import load_run_config  # noqa: E402

#: The runs the parts decision's browser tests read: one only looked at, one decided and driven.
PARTS_RUNS = ("run-parts-view", "run-parts-decide")


def _target(out: Path, name: str) -> Path:
    """Where a parts run's target repository is, beside the runs, never among them."""
    return out / "parts" / name / "target"


def parts_runs(out: Path, runs: Path) -> None:
    """Start each run of :data:`PARTS_RUNS` under ``runs`` and drive it to its parts' hold."""
    library = build_fixture_library(out / "parts" / "library")
    for name in PARTS_RUNS:
        repo = observe_rig.target_repo(_target(out, name).parent)
        cfg = ref.config(repo, name)
        start_run(
            ref.outcome(runs / name),
            config=cfg,
            run_dir=runs / name,
            target_repo=repo,
            library=library,
            brief=ref.BRIEF.read_text(),
        ).close()
        step, requests = ref.drive(runs, cfg, repo)
        if step != "wait" or requests:
            msg = f"{name} did not hold for its parts: it ended on {step}"
            raise RuntimeError(msg)


def drive_once_more(out: Path, name: str) -> str:
    """Drive the run ``name`` once more, as ``physgate run`` does; the step it ends on."""
    runs = out / "runs"
    cfg = load_run_config(runs / name / "run.json")
    step, _ = ref.drive(runs, cfg, _target(out, name))
    return step


def main(argv: list[str]) -> int:
    """Drive the run ``argv[2]`` built under ``argv[1]``, and print the step it ended on."""
    from stand_in_roles import register  # noqa: PLC0415 - as ``ui_e2e_runs`` registers them

    register()
    print(drive_once_more(Path(argv[1]), argv[2]), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
