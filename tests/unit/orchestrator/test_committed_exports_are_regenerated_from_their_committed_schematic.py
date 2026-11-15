"""Committed circuit exports are held to the committed schematic: regenerated at commit, compared.

A role commits a schematic and the three text exports the helper wrote from it. At the change
check, the exports are regenerated from the committed schematic alone, by the command the run's
recorded tool environment names (its ``derived.json``), and any byte difference refuses the
attempt with a refusal of its own kind (``exports``) that names the file and says to regenerate.

Here the tool environment is a stand-in root: its ``derived.json`` names a stand-in program that
writes the three kinds from a stand-in schematic (``part`` and ``open`` lines), and the
regeneration runs through a runner of the test's own, which records what it was given; the
containment and the real program are the integration test's. Read here:

- an honest set passes; a hand-edited clean report over a failing schematic, a changed schematic
  with stale exports and an export changed over an unchanged schematic are each refused;
- a schematic without its exports, exports without their schematic, a partial set and two
  schematics sharing a name each have their refusal;
- a regeneration that fails, times out, writes over a cap or writes nothing refuses; an exit code
  the record words (a sub-sheet) is refused in the record's words;
- no recorded environment, or one that does not hold its record, refuses; a commit touching
  neither a schematic nor an export asks for nothing;
- the command's argument list holds nothing of the role's tree but the copied schematic's path,
  in a folder made new for the call and removed after it;
- the record is read strictly; the core names no tool; the refusal kind is classed everywhere.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import typing
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
from hook_helpers import make_store, node  # noqa: E402

from physgate.orchestrator import escalation_state, events, ports, repair  # noqa: E402
from physgate.orchestrator.apply import GitChangeChecker  # noqa: E402
from physgate.orchestrator.exceptions import InvocationError  # noqa: E402
from physgate.orchestrator.merge import RunGit, commit_attempt  # noqa: E402
from physgate.toolenv.record import ToolEnvironment  # noqa: E402

try:
    from physgate.orchestrator import derived
except ImportError:  # the module is what these rows ask for; each fails on its first assertion
    derived = None  # type: ignore[assignment]

REPO = Path(__file__).resolve().parents[3]
PLANNED = {"s1": "modules/s1"}
MODULE = "modules/s1"
_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.devnull,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}

#: The stand-in program: the three kinds from ``part`` and ``open`` lines, or as a word tells.
REGEN = r'''
import json, os, sys, time
source, module, name = sys.argv[1:4]
text = open(source, encoding="utf-8").read()
if "SUBSHEET" in text:
    sys.exit(3)
if "FAIL" in text:
    sys.exit(1)
if "SLEEP" in text:
    time.sleep(60)
if "NOWRITE" in text:
    sys.exit(0)
out = os.path.join(module, "exports")
os.makedirs(out, exist_ok=True)
lines = text.splitlines()
parts = [l.split()[1] for l in lines if l.startswith("part ")]
opens = [l.split()[1] for l in lines if l.startswith("open ")]
findings = [
    {"type": "pin_not_connected", "severity": "error", "description": "pin of " + p, "items": []}
    for p in opens
]
report = {
    "$schema": "https://schemas.kicad.org/erc.v1.json", "kicad_version": "stand-in",
    "date": "2000-01-01T00:00:00", "source": os.path.basename(source),
    "sheets": [{"path": "/", "violations": findings}],
}
with open(os.path.join(out, name + ".erc.json"), "w") as f:
    f.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
rel = os.path.relpath(source, module)
comps = "".join(' (comp (ref "' + p + '"))' for p in parts)
pad = " " * 1_000_001 if "BIG" in text else ""
with open(os.path.join(out, name + ".net"), "w") as f:
    f.write('(export (version "E")\n  (design (source "' + rel + '"))\n  (components'
            + comps + ")\n  (nets)" + pad + ")\n")
rows = "".join('"' + p + '","1k","R","1",""\n' for p in parts)
with open(os.path.join(out, name + ".csv"), "w") as f:
    f.write('"Reference","Value","Footprint","Quantity","DNP"\n' + rows)
'''

SOUND = "part R1\npart J1\n"
FAILING = "part R1\npart J1\nopen R1\nopen J1\n"
REFUSALS = {"3": "the schematic draws on a sub-sheet; one sheet per schematic is regenerated"}


def recipe(**changes: Any) -> dict[str, Any]:  # noqa: ANN401
    entry: dict[str, Any] = {
        "source": ".kicad_sch",
        "products": [".erc.json", ".net", ".csv"],
        "argv": ["{interpreter}", "-I", "{root}/regen.py", "{source}", "{module}", "{name}"],
        "timeout_s": 20,
        "refusals": REFUSALS,
    }
    entry.update(changes)
    return entry


def stand_in_root(tmp_path: Path, *entries: dict[str, Any], name: str = "root") -> Path:
    root = tmp_path / name
    root.mkdir(parents=True)
    (root / "regen.py").write_text(REGEN, encoding="utf-8")
    body = {"derivations": list(entries) if entries else [recipe()]}
    (root / "derived.json").write_text(json.dumps(body), encoding="utf-8")
    return root


def recorded(*roots: Path) -> ToolEnvironment:
    python = sys.executable
    return ToolEnvironment(
        interpreter=python,
        resolved=os.path.realpath(python),
        python_version="3.12.9",
        prefix=sys.prefix,
        distributions=(),
        native_tools=(),
        roots=tuple(str(r) for r in roots),
        manifest_digest="0" * 64,
        entries=1,
        total_bytes=0,
    )


class Runs:
    """A runner of the test's own: runs the command as given, no wrapper, and records each call."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        argv: Sequence[str],
        work: Path,
        env: Mapping[str, str],
        timeout_s: float,
        roots: Sequence[str],
    ) -> int | None:
        self.calls.append(
            {"argv": list(argv), "work": Path(work), "roots": list(roots), "timeout": timeout_s}
        )
        try:
            done = subprocess.run(  # noqa: S603 - the stand-in, as the record names it
                list(argv), cwd=work, env=dict(env), timeout=timeout_s, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            return None
        return done.returncode


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        env=_ENV,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def made(text: str, stem: str = "board", where: str = "") -> dict[str, bytes]:
    """The schematic ``text`` and the exports the stand-in writes from it, as module paths."""
    scratch = Path(tempfile.mkdtemp(prefix="made-"))
    module = scratch / "module"
    source = module / where / f"{stem}.kicad_sch"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(text, encoding="utf-8")
    program = scratch / "regen.py"
    program.write_text(REGEN, encoding="utf-8")
    subprocess.run(
        [sys.executable, "-I", str(program), str(source), str(module), stem], check=True
    )
    found = {
        f"{MODULE}/{p.relative_to(module).as_posix()}": p.read_bytes()
        for p in module.rglob("*")
        if p.is_file()
    }
    for p in sorted(scratch.rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    scratch.rmdir()
    return found


def attempt(
    tmp_path: Path, files: dict[str, bytes], start: dict[str, bytes] | None = None
) -> tuple[RunGit, str]:
    """A run whose base holds ``start`` and whose subtask ``s1`` commits ``files`` on top."""
    repo = tmp_path / "target"
    (repo / "modules").mkdir(parents=True)
    (repo / "modules" / "a.txt").write_text("0\n")
    for path, data in (start or {}).items():
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_bytes(data)
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    run = RunGit(repo=repo, run_dir=tmp_path / "run", run_id="r1")
    run.open_run_branch(_git(repo, "rev-parse", "HEAD"))
    worktree = run.open_subtask("s1")
    for path, data in files.items():
        target = worktree / path
        if data == b"<removed>":
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return run, commit_attempt(worktree, "s1", 1, "sess-1", repo=run.repo)


def checker(
    tmp_path: Path,
    run: RunGit,
    environment: Callable[[], ToolEnvironment | None],
    runs: Runs,
    record: ToolEnvironment,
) -> GitChangeChecker:
    store = tmp_path / "store"
    make_store(store, node("control.loop", "control"))
    try:
        return GitChangeChecker(
            run, store, dict(PLANNED), recorded=record, environment=environment, regenerate=runs
        )  # type: ignore[call-arg]
    except TypeError as exc:
        raise AssertionError(f"the checker takes the environment and a runner: {exc}") from None


def check(
    tmp_path: Path,
    files: dict[str, bytes],
    *,
    start: dict[str, bytes] | None = None,
    root: Path | None = None,
    environment: Callable[[], ToolEnvironment | None] | None = None,
) -> tuple[ports.ChangeCheck, Runs]:
    assert derived is not None, "physgate.orchestrator.derived holds the exports to the schematic"
    run, commit = attempt(tmp_path, files, start)
    the_root = root or stand_in_root(tmp_path)
    runs = Runs()
    record = recorded(the_root)
    found = checker(tmp_path, run, environment or (lambda: record), runs, record)
    return found.check("s1", commit, "control"), runs


def refused(found: ports.ChangeCheck, path: str) -> str:
    assert found.refused_by == "exports", (found.refused_by, found.reason)
    assert found.subject == path, (found.subject, found.reason)
    assert found.reason is not None and path in found.reason, found.reason
    return found.reason


# ---- the four the ruling names ---------------------------------------------------------------


def test_an_honest_set_passes_and_is_regenerated_once(tmp_path: Path) -> None:
    found, runs = check(tmp_path, made(FAILING))
    assert found.refused_by is None, found.reason
    assert len(runs.calls) == 1


def test_a_hand_edited_clean_report_over_a_failing_schematic_is_refused(tmp_path: Path) -> None:
    files = made(FAILING)
    clean = made(SOUND)[f"{MODULE}/exports/board.erc.json"]
    forged = clean.replace(b'"kicad_version": "stand-in"', b'"kicad_version": "MARKER-7731"')
    files[f"{MODULE}/exports/board.erc.json"] = forged
    found, _ = check(tmp_path, files)
    reason = refused(found, f"{MODULE}/exports/board.erc.json")
    assert "regenerate" in reason
    assert "MARKER-7731" not in reason and "violations" not in reason


def test_a_changed_schematic_with_stale_exports_is_refused(tmp_path: Path) -> None:
    start = made(SOUND)
    changed = {f"{MODULE}/board.kicad_sch": FAILING.encode()}
    found, runs = check(tmp_path, changed, start=start)
    reason = refused(found, f"{MODULE}/exports/board.erc.json")
    assert "regenerate" in reason
    assert len(runs.calls) == 1


def test_an_export_changed_over_an_unchanged_schematic_is_regenerated_and_compared(
    tmp_path: Path,
) -> None:
    start = made(FAILING)
    edited = start[f"{MODULE}/exports/board.csv"] + b'"R9","1k","R","1",""\n'
    found, runs = check(tmp_path, {f"{MODULE}/exports/board.csv": edited}, start=start)
    refused(found, f"{MODULE}/exports/board.csv")
    assert len(runs.calls) == 1


def test_a_schematic_in_a_folder_of_the_module_is_regenerated_at_its_own_path(
    tmp_path: Path,
) -> None:
    found, runs = check(tmp_path, made(SOUND, where="circuit"))
    assert found.refused_by is None, found.reason
    assert len(runs.calls) == 1


# ---- what has no pair ------------------------------------------------------------------------


def test_a_schematic_committed_without_its_exports_is_refused(tmp_path: Path) -> None:
    found, runs = check(tmp_path, {f"{MODULE}/board.kicad_sch": SOUND.encode()})
    reason = refused(found, f"{MODULE}/exports/board.erc.json")
    assert "regenerate" in reason
    assert runs.calls == []


def test_exports_committed_without_their_schematic_are_refused(tmp_path: Path) -> None:
    files = {k: v for k, v in made(SOUND).items() if k.endswith((".erc.json", ".net", ".csv"))}
    found, runs = check(tmp_path, files)
    refused(found, f"{MODULE}/exports/board.erc.json")
    assert runs.calls == []


def test_exports_whose_schematic_is_removed_are_refused(tmp_path: Path) -> None:
    start = made(SOUND)
    found, _ = check(tmp_path, {f"{MODULE}/board.kicad_sch": b"<removed>"}, start=start)
    refused(found, f"{MODULE}/exports/board.erc.json")


def test_a_partial_set_is_refused_naming_the_missing_export(tmp_path: Path) -> None:
    files = made(SOUND)
    del files[f"{MODULE}/exports/board.csv"]
    found, runs = check(tmp_path, files)
    refused(found, f"{MODULE}/exports/board.csv")
    assert runs.calls == []


def test_two_schematics_sharing_a_name_are_refused(tmp_path: Path) -> None:
    files = {**made(SOUND), f"{MODULE}/other/board.kicad_sch": SOUND.encode()}
    found, runs = check(tmp_path, files)
    refused(found, f"{MODULE}/other/board.kicad_sch")
    assert runs.calls == []


def test_a_schematic_and_its_exports_removed_together_ask_for_nothing(tmp_path: Path) -> None:
    start = made(SOUND)
    gone = dict.fromkeys(start, b"<removed>")
    found, runs = check(tmp_path, gone, start=start)
    assert found.refused_by is None, found.reason
    assert runs.calls == []


# ---- a regeneration that does not finish as asked ---------------------------------------------


@pytest.mark.parametrize(
    ("word", "said"),
    [
        ("FAIL", "exit code 1"),
        ("SLEEP", "timed out"),
        ("BIG", "cap"),
        ("NOWRITE", "not written"),
        ("SUBSHEET", "sub-sheet"),
    ],
)
def test_a_regeneration_that_fails_times_out_passes_a_cap_or_writes_nothing_refuses(
    tmp_path: Path, word: str, said: str
) -> None:
    files = made(SOUND)
    files[f"{MODULE}/board.kicad_sch"] = (SOUND + word + "\n").encode()
    root = stand_in_root(tmp_path, recipe(timeout_s=3))
    found, runs = check(tmp_path, files, root=root)
    assert found.refused_by == "exports", (found.refused_by, found.reason)
    assert found.reason is not None and said in found.reason, found.reason
    assert f"{MODULE}/board.kicad_sch" in found.reason
    assert len(runs.calls) == 1


# ---- the record ----------------------------------------------------------------------------------


def test_a_run_with_no_recorded_environment_refuses_a_committed_set(tmp_path: Path) -> None:
    found, _ = check(tmp_path, made(SOUND), environment=lambda: None)
    assert found.refused_by == "exports", (found.refused_by, found.reason)
    assert found.reason is not None and "tool environment" in found.reason


def test_an_environment_that_does_not_hold_its_record_refuses(tmp_path: Path) -> None:
    def not_held() -> ToolEnvironment | None:
        msg = "an entry of the tool environment changed since the run started"
        raise InvocationError(msg)

    found, runs = check(tmp_path, made(SOUND), environment=not_held)
    assert found.refused_by == "exports", (found.refused_by, found.reason)
    assert found.reason is not None and "changed since the run started" in found.reason
    assert runs.calls == []


def test_a_commit_touching_no_schematic_and_no_export_asks_for_nothing(tmp_path: Path) -> None:
    asked: list[int] = []

    def environment() -> ToolEnvironment | None:
        asked.append(1)
        return None

    found, runs = check(tmp_path, {f"{MODULE}/notes.txt": b"x\n"}, environment=environment)
    assert found.refused_by is None, found.reason
    assert (asked, runs.calls) == ([], [])


def test_the_command_holds_only_the_copied_schematic_in_a_fresh_folder_removed_after(
    tmp_path: Path,
) -> None:
    found, runs = check(tmp_path, made(SOUND))
    assert found.refused_by is None, found.reason
    (call,) = runs.calls
    work, argv = call["work"], call["argv"]
    assert not work.exists(), work
    assert not work.is_relative_to(tmp_path / "run")
    assert not work.is_relative_to(tmp_path / "target")
    inside = [a for a in argv if a.startswith(str(work))]
    assert inside == [str(work / "module" / "board.kicad_sch"), str(work / "module")], argv
    assert argv[0] == sys.executable and argv[-1] == "board", argv
    assert call["roots"] == [str(tmp_path / "root")]


def test_a_failed_regeneration_s_folder_is_removed_too(tmp_path: Path) -> None:
    files = made(SOUND)
    files[f"{MODULE}/board.kicad_sch"] = (SOUND + "FAIL\n").encode()
    found, runs = check(tmp_path, files)
    assert found.refused_by == "exports"
    assert not runs.calls[0]["work"].exists()


@pytest.mark.parametrize(
    ("entry", "why"),
    [
        (recipe(argv=["{interpreter}", "{home}/x.py"]), "placeholder"),
        (recipe(argv=["/usr/bin/env", "python3", "{source}"]), "interpreter"),
        (recipe(products=[".erc.json", ".net", ".csv", ".step"]), "product"),
        (recipe(timeout_s=0), "timeout"),
        (recipe(extra=1), "extra"),
    ],
)
def test_a_record_entry_outside_its_shape_is_refused(
    tmp_path: Path, entry: dict[str, Any], why: str
) -> None:
    assert derived is not None, "physgate.orchestrator.derived reads the record"
    root = stand_in_root(tmp_path, entry)
    with pytest.raises(derived.DerivedError):
        derived.read_derivations(recorded(root))
    assert why


def test_two_roots_deriving_the_same_kind_are_refused(tmp_path: Path) -> None:
    assert derived is not None, "physgate.orchestrator.derived reads the record"
    one, two = stand_in_root(tmp_path, name="one"), stand_in_root(tmp_path, name="two")
    with pytest.raises(derived.DerivedError):
        derived.read_derivations(recorded(one, two))


def test_a_root_without_a_record_derives_nothing_and_one_with_it_is_read(tmp_path: Path) -> None:
    assert derived is not None, "physgate.orchestrator.derived reads the record"
    empty = tmp_path / "empty"
    empty.mkdir()
    root = stand_in_root(tmp_path)
    found = derived.read_derivations(recorded(empty, root))
    assert [(r.root, r.derivation.source) for r in found] == [(str(root), ".kicad_sch")]


def test_with_no_wrapper_on_this_machine_the_regeneration_is_refused(tmp_path: Path) -> None:
    assert derived is not None, "physgate.orchestrator.derived runs the regeneration contained"
    run = derived.contained_runner(platform="linux", bwrap=None)
    with pytest.raises(derived.DerivedError):
        run([sys.executable, "-c", "pass"], tmp_path, {}, 5.0, [str(tmp_path)])


def test_the_core_names_no_tool() -> None:
    core = REPO / "src" / "physgate" / "orchestrator" / "derived.py"
    assert core.is_file(), "the core module that holds the exports is missing"
    text = core.read_text("utf-8")
    for word in ("kicad", "circuit", "netlist", "erc", "skidl", ".sch"):
        assert word not in text.casefold(), word


def test_the_refusal_kind_is_classed_wherever_refusal_kinds_are() -> None:
    told = ports.ChangeCheck.model_fields["refused_by"].annotation
    kinds = set(typing.get_args(typing.get_args(told)[0]))
    assert "exports" in kinds
    rejected = events.ProposalsChecked.model_fields["refused_by"].annotation
    assert kinds == set(typing.get_args(typing.get_args(rejected)[0]))
    held = escalation_state.ChangesPart.model_fields["refused_by"].annotation
    assert kinds == set(typing.get_args(typing.get_args(held)[0]))
    sources = set(typing.get_args(repair.FindingSource))
    assert kinds <= sources
    assert set(repair._WHO) == sources  # noqa: SLF001 - every source is worded


# ---- the check's own bounds: how many sets, and one deadline for all of them ------------------


def _sets_of(count: int, text: str = SOUND) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for n in range(count):
        files.update(made(text, stem=f"board{n}"))
    return files


def test_as_many_sets_as_the_cap_are_regenerated_and_pass(tmp_path: Path) -> None:
    assert derived is not None, "physgate.orchestrator.derived holds the exports to the schematic"
    cap = getattr(derived, "MAX_SETS_PER_CHECK", None)
    assert isinstance(cap, int) and cap >= 1, "a stated cap on the sets one check regenerates"
    found, runs = check(tmp_path, _sets_of(cap))
    assert found.refused_by is None, found.reason
    assert len(runs.calls) == cap


def test_one_set_past_the_cap_is_refused_in_words_and_none_is_regenerated(
    tmp_path: Path,
) -> None:
    assert derived is not None, "physgate.orchestrator.derived holds the exports to the schematic"
    cap = getattr(derived, "MAX_SETS_PER_CHECK", None)
    assert isinstance(cap, int) and cap >= 1, "a stated cap on the sets one check regenerates"
    found, runs = check(tmp_path, _sets_of(cap + 1))
    assert found.refused_by == "exports", (found.refused_by, found.reason)
    assert found.reason is not None and f"at most {cap}" in found.reason, found.reason
    assert runs.calls == []


def test_each_regeneration_is_given_no_more_than_the_check_s_time_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert derived is not None, "physgate.orchestrator.derived holds the exports to the schematic"
    monkeypatch.setattr(derived, "TOTAL_DEADLINE_S", 4.0, raising=False)
    root = stand_in_root(tmp_path, recipe(timeout_s=20))
    found, runs = check(tmp_path, _sets_of(2), root=root)
    assert found.refused_by is None, found.reason
    assert [call["timeout"] <= 4.0 for call in runs.calls] == [True, True], runs.calls
    assert runs.calls[1]["timeout"] <= runs.calls[0]["timeout"]


def test_running_out_of_the_check_s_deadline_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert derived is not None, "physgate.orchestrator.derived holds the exports to the schematic"
    monkeypatch.setattr(derived, "TOTAL_DEADLINE_S", 2.0, raising=False)
    files = _sets_of(2)
    files[f"{MODULE}/board0.kicad_sch"] = (SOUND + "SLEEP\n").encode()
    root = stand_in_root(tmp_path, recipe(timeout_s=20))
    found, runs = check(tmp_path, files, root=root)
    assert runs.calls and runs.calls[0]["timeout"] <= 2.0, runs.calls
    assert found.refused_by == "exports", (found.refused_by, found.reason)
    assert found.reason is not None and "deadline" in found.reason, found.reason
    assert len(runs.calls) == 1
