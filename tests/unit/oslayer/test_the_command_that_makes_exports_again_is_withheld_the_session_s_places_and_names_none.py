"""The command that makes a role's exports again is withheld the sessions' places, and names none.

At the change check the harness makes a role's committed circuit exports again from the committed
schematic, by the tool environment's own command, inside the tool containment (bubblewrap on
Linux, a generated Seatbelt profile on macOS). That command is run for a role's file, so it is
withheld at least what the role's session was: each place it is given as withheld is hidden whole
wherever it lies inside what the command reads (Linux) or denied to every read (macOS). A runner
given no withheld places refuses and starts nothing. When the wrapper's rules cannot be built, a
root of the command inside a withheld place among the causes, the refusal says so by kind and
names no place, and the change check's refusal carries those words alone: a withheld place is the
protected material's, and a refusal is shown to the role and written on the run's log. Nor is
anything the command itself wrote ever quoted: a regeneration that fails is refused by its exit
code alone, so a withheld place it prints, whole, cut at the edge of what is kept, or spelt
another way, reaches neither the refusal nor the check's line on the log (a refused attempt is
never issued to a review, so no packet is made of it).

Here no wrapper runs: the runner's last step, which starts the wrapped command, is replaced by one
that records the command (and, on macOS, the profile it names) and starts nothing. The wrapper
running for real is the integration rows'.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
from test_committed_exports_are_regenerated_from_their_committed_schematic import (  # noqa: E402
    FAILING,
    attempt,
    checker,
    made,
    recorded,
    stand_in_root,
)

from physgate.orchestrator.events import ProposalsChecked  # noqa: E402
from physgate.oslayer import regeneration  # noqa: E402
from physgate.oslayer.containment import SANDBOX_EXEC, ContainmentError  # noqa: E402

#: A wrapper path for the Linux rows: its options are built, and it is never started.
BWRAP = "/usr/bin/bwrap"


class Started:
    """The runner's last step, replaced: what would have started, and nothing started."""

    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.profiles: list[str] = []
        #: What the started command says on its error stream.
        self.said = ""

    def __call__(
        self, command: Sequence[str], work: Path, env: object, timeout_s: float
    ) -> tuple[int | None, str]:
        self.commands.append(list(command))
        if command[0] == SANDBOX_EXEC:
            self.profiles.append(Path(command[2]).read_text(encoding="utf-8"))
        return 1, self.said


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch) -> Started:
    seen = Started()
    monkeypatch.setattr(regeneration, "_run", seen)
    return seen


def _places(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A tool root with a withheld place inside it, and a withheld place beside it."""
    root = tmp_path / "tools"
    inside = root / "held-out-tier"
    inside.mkdir(parents=True)
    beside = tmp_path / "run"
    beside.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    return root, inside, beside


def _run(platform: str, tmp_path: Path, withheld: Sequence[str], roots: Sequence[str]) -> None:
    run = regeneration.contained_runner(
        platform=platform, bwrap=BWRAP, withheld=lambda: tuple(withheld)
    )
    program = os.path.join(roots[0], "python") if roots else "/usr/bin/true"
    run([program, "-I", "-c", "pass"], tmp_path / "work", {}, 5.0, roots)


def test_on_linux_a_withheld_place_inside_what_the_command_reads_is_hidden(
    tmp_path: Path, started: Started
) -> None:
    root, inside, beside = _places(tmp_path)
    _run("linux", tmp_path, [str(inside), str(beside)], [str(root)])
    (command,) = started.commands
    assert command[0] == BWRAP
    options = command[: command.index("--", 1)]
    hidden = os.path.realpath(inside)
    pairs = list(zip(options, options[1:], strict=False))
    assert ("--tmpfs", hidden) in pairs, options
    # Hidden after the root that holds it is bound, so the root's binding does not open it again.
    bound = pairs.index(("--ro-bind", os.path.realpath(root)))
    assert pairs.index(("--tmpfs", hidden)) > bound
    assert ("--remount-ro", hidden) in pairs


def test_on_macos_every_withheld_place_is_denied_to_every_read(
    tmp_path: Path, started: Started
) -> None:
    root, inside, beside = _places(tmp_path)
    _run("darwin", tmp_path, [str(inside), str(beside)], [str(root)])
    (profile,) = started.profiles
    denials = [line for line in profile.splitlines() if line.startswith("(deny file-read*")]
    for place in (inside, beside):
        assert any(f'"{os.path.realpath(place)}"' in line for line in denials), (place, denials)
    # Denied after the allowance of the root that holds it: the last rule that matches decides.
    lines = profile.splitlines()
    allowed = next(i for i, line in enumerate(lines) if line.startswith("(allow file-read* "))
    denied = next(
        i for i, line in enumerate(lines) if os.path.realpath(inside) in line and "deny" in line
    )
    assert denied > allowed


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_a_runner_given_no_withheld_places_refuses_and_starts_nothing(
    platform: str, tmp_path: Path, started: Started
) -> None:
    root, _inside, _beside = _places(tmp_path)
    run = regeneration.contained_runner(platform=platform, bwrap=BWRAP)
    with pytest.raises(ContainmentError):
        run([str(root / "python"), "-c", "pass"], tmp_path / "work", {}, 5.0, [str(root)])
    assert started.commands == []
    runner = regeneration.default_runner(platform=platform, search_path=os.path.dirname(BWRAP))
    with pytest.raises(ContainmentError):
        runner([str(root / "python"), "-c", "pass"], tmp_path / "work", {}, 5.0, [str(root)])
    assert started.commands == []


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_a_root_inside_a_withheld_place_refuses_in_words_that_name_no_place(
    platform: str, tmp_path: Path, started: Started
) -> None:
    secret = tmp_path / "held-out-tier-9c41"
    root = secret / "tools"
    root.mkdir(parents=True)
    (tmp_path / "work").mkdir()
    with pytest.raises(ContainmentError) as caught:
        _run(platform, tmp_path, [str(secret)], [str(root)])
    said = str(caught.value)
    assert "held-out-tier-9c41" not in said and str(tmp_path) not in said, said
    assert said == regeneration.UNCONTAINED
    assert started.commands == []


def test_the_change_check_s_refusal_of_an_uncontained_set_names_no_withheld_place(
    tmp_path: Path, started: Started
) -> None:
    secret = tmp_path / "held-out-tier-9c41"
    secret.mkdir()
    root = stand_in_root(secret)
    run, commit = attempt(tmp_path, made(FAILING))
    record = recorded(root)
    runner = regeneration.contained_runner(
        platform="linux", bwrap=BWRAP, withheld=lambda: (str(secret),)
    )
    found = checker(tmp_path, run, lambda: record, runner).check("s1", commit, "control")  # type: ignore[arg-type]
    assert found.refused_by == "exports", (found.refused_by, found.reason)
    assert found.reason is not None
    assert "held-out-tier-9c41" not in found.reason and str(tmp_path) not in found.reason
    assert regeneration.UNCONTAINED in found.reason, found.reason
    assert started.commands == []


#: A withheld place's distinctive part, as a regeneration might print it.
MARK = "tier 7731"


def _printed(place: str) -> dict[str, str]:
    """What a command might write of ``place``: whole, cut at its front, escaped and upper-cased."""
    return {
        "whole": f"cannot open {place}/brief.json: permission denied\n",
        "cut at the edge": f"{place[len(place) // 2 :]}/brief.json: permission denied\n",
        "escaped": f"denied: {place.replace(' ', chr(92) + '040').upper()}\n",
    }


class Says:
    """A runner that starts nothing and ends as a failed command that wrote ``said``."""

    def __init__(self, said: str) -> None:
        self.said = said

    def __call__(
        self,
        argv: Sequence[str],
        work: Path,
        env: object,
        timeout_s: float,
        roots: Sequence[str],
    ) -> tuple[int | None, str]:
        return 1, self.said


@pytest.mark.parametrize("form", ["whole", "cut at the edge", "escaped"])
def test_nothing_a_failed_regeneration_wrote_reaches_its_refusal_or_the_check_s_line(
    form: str, tmp_path: Path
) -> None:
    place = str(tmp_path / MARK)
    said = _printed(place)[form]
    assert "7731" in said
    run, commit = attempt(tmp_path, made(FAILING))
    record = recorded(stand_in_root(tmp_path))
    found = checker(tmp_path, run, lambda: record, Says(said)).check("s1", commit, "control")  # type: ignore[arg-type]
    assert found.refused_by == "exports", (found.refused_by, found.reason)
    ended = "the program ended with an error"
    assert found.reason is not None and ended in found.reason, found.reason
    line = ProposalsChecked(
        seq=1,
        ts="2026-11-24T00:00:00.000000Z",
        run_id="r1",
        gate_mode="on",
        subtask_id="s1",
        attempt=1,
        checked_commit="0" * 40,
        **found.model_dump(
            exclude={"declaration", "disputes", "series_checks", "proposed", "exports"}
        ),
    ).model_dump_json()
    for kept in (found.reason, line):
        assert "7731" not in kept and "permission denied" not in kept.casefold(), kept


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_the_withheld_places_are_asked_for_at_every_call(
    platform: str, tmp_path: Path, started: Started
) -> None:
    """A place withheld after the first call (a later run on the tier) is withheld at the next."""
    asked: list[int] = []
    root = tmp_path / "tools"
    first, second = root / "first", root / "second"
    first.mkdir(parents=True)
    second.mkdir()
    places = [str(first)]

    def withheld() -> list[str]:
        asked.append(len(asked))
        return list(places)

    run = regeneration.contained_runner(platform=platform, bwrap=BWRAP, withheld=withheld)
    run(["/bin/true"], tmp_path, {}, 5.0, [str(root)])
    places.append(str(second))
    run(["/bin/true"], tmp_path, {}, 5.0, [str(root)])
    assert len(asked) == 2
    last = started.profiles[-1] if platform == "darwin" else " ".join(started.commands[-1])
    assert os.path.realpath(second) in last, last
