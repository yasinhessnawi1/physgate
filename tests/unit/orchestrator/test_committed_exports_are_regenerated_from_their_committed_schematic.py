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
- no recorded environment, or one that does not hold its record, refuses, whatever file of the
  module the change touches: which files are sources is read from the held environment alone; a
  commit touching neither a schematic nor an export regenerates nothing;
- a failed regeneration is refused with its last line, bounded; time used up before a set
  starts refuses it unrun; an export kind no entry makes is refused; a product written as a link
  is no product; the check refuses and never raises;
- the command's argument list holds nothing of the role's tree but the copied schematic's path,
  in a folder made new for the call and removed after it;
- the record is read strictly; the core names no tool and starts no process (the runner is the
  OS layer's, whose wrapper is named in code and found on absolute folders only); the refusal
  kind is classed everywhere;
- what the machine does to a regeneration (a wrapper program gone, a folder that cannot be made
  or written, git that cannot read the commit, a record that cannot be read, a bound passed) is
  a refusal with a short reason, never a raise, and the loop rejects the attempt on it as on any
  refusal; a fault of the code is never taken as a pass;
- the check says how many sets it made again, on its result and on its line: none when nothing
  was to check, absent when it was refused before the exports;
- the core refuses a name outside the safe shape before any run, and puts the end of the
  options before the first path it gives the command;
- the runner bounds the error stream and what is written into the folder, runs the program in a
  session of its own, and ends everything it started.
"""

from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
import tempfile
import time
import typing
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hooks"))
from hook_helpers import make_store, node  # noqa: E402
from loop_fakes import FakeChanges, Rig, plan  # noqa: E402

from physgate.orchestrator import escalation_state, events, ports, repair  # noqa: E402
from physgate.orchestrator.apply import GitChangeChecker  # noqa: E402
from physgate.orchestrator.exceptions import GitError, InvocationError  # noqa: E402
from physgate.orchestrator.merge import RunGit, commit_attempt  # noqa: E402
from physgate.series.seal import SessionSeries  # noqa: E402
from physgate.toolenv.record import ToolEnvironment  # noqa: E402

try:
    from physgate.orchestrator import derived
except ImportError:  # the module is what these rows ask for; each fails on its first assertion
    derived = None  # type: ignore[assignment]

try:
    from physgate.oslayer import regeneration
except ImportError:  # the runner's home is what the rows below ask for
    regeneration = None  # type: ignore[assignment]

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
REGEN = r"""
import json, os, sys, time
args = sys.argv[1:]
if args[:1] == ["--"]:
    args = args[1:]
source, module, name = args[:3]
text = open(source, encoding="utf-8").read()
if "SUBSHEET" in text:
    sys.exit(3)
if "SAY" in text:
    sys.stderr.write("an earlier line\n" + "why " * 100 + "\x07\n\n")
    sys.exit(1)
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
            + comps + ')\n  (nets (net (code "1") (name "/A")))' + pad + ")\n")
rows = "".join('"' + p + '","1k","R","1",""\n' for p in parts)
with open(os.path.join(out, name + ".csv"), "w") as f:
    f.write('"Reference","Value","Footprint","Quantity","DNP"\n' + rows)
"""

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
    ) -> tuple[int | None, str]:
        self.calls.append(
            {"argv": list(argv), "work": Path(work), "roots": list(roots), "timeout": timeout_s}
        )
        try:
            done = subprocess.run(  # noqa: S603 - the stand-in, as the record names it
                list(argv), cwd=work, env=dict(env), timeout=timeout_s, check=False,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            return None, ""
        return done.returncode, done.stderr.decode("utf-8", errors="replace")[-4096:]


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
    subprocess.run([sys.executable, "-I", str(program), str(source), str(module), stem], check=True)
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
) -> GitChangeChecker:
    store = tmp_path / "store"
    make_store(store, node("control.loop", "control"))
    try:
        return GitChangeChecker(run, store, dict(PLANNED), environment=environment, regenerate=runs)
    except TypeError as exc:
        raise AssertionError(f"the checker takes the environment and a runner: {exc}") from None


def check(
    tmp_path: Path,
    files: dict[str, bytes],
    *,
    start: dict[str, bytes] | None = None,
    root: Path | None = None,
    environment: Callable[[], ToolEnvironment | None] | None = None,
    runs: Runs | None = None,
) -> tuple[ports.ChangeCheck, Runs]:
    assert derived is not None, "physgate.orchestrator.derived holds the exports to the schematic"
    run, commit = attempt(tmp_path, files, start)
    the_root = root or stand_in_root(tmp_path)
    the_runs = runs or Runs()
    record = recorded(the_root)
    found = checker(tmp_path, run, environment or (lambda: record), the_runs)
    return found.check("s1", commit, "control"), the_runs


def check_never_raising(
    tmp_path: Path,
    files: dict[str, bytes],
    **given: Any,  # noqa: ANN401
) -> tuple[ports.ChangeCheck, Runs]:
    """As :func:`check`, holding that the change check refuses and never raises."""
    try:
        return check(tmp_path, files, **given)
    except Exception as exc:  # noqa: BLE001 - what escapes the check is the finding
        raise AssertionError(f"the change check raised instead of refusing: {exc!r}") from None


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
    found, runs = check_never_raising(tmp_path, files)
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
    found, runs = check_never_raising(tmp_path, files, root=root)
    assert found.refused_by == "exports", (found.refused_by, found.reason)
    assert found.reason is not None and said in found.reason, found.reason
    assert f"{MODULE}/board.kicad_sch" in found.reason
    assert len(runs.calls) == 1


def test_a_failed_regeneration_is_refused_with_its_last_line_bounded(tmp_path: Path) -> None:
    files = made(SOUND)
    files[f"{MODULE}/board.kicad_sch"] = (SOUND + "SAY\n").encode()
    found, _ = check(tmp_path, files)
    assert found.refused_by == "exports", (found.refused_by, found.reason)
    assert found.reason is not None and "exit code 1" in found.reason, found.reason
    assert "why why" in found.reason, found.reason
    assert "an earlier line" not in found.reason and "\x07" not in found.reason, found.reason
    said = found.reason.split("why", 1)[1]
    assert len("why" + said) <= 200, len("why" + said)
    assert said.endswith("…"), said[-20:]


@pytest.mark.parametrize(
    ("said", "kept"),
    [
        ("", ""),
        ("\n \n", ""),
        ("first\nlast one\n", "last one"),
        ("a\tb\x1b[31m\n", "a b [31m"),
        ("x" * 200, "x" * 200),
        ("x" * 201, "x" * 199 + "…"),
    ],
)
def test_a_failed_command_s_last_line_is_kept_printable_and_cut(said: str, kept: str) -> None:
    assert derived is not None, "physgate.orchestrator.derived words a failed regeneration"
    assert getattr(derived, "MAX_SAID", None) == 200, "a stated bound on the line a refusal carries"
    assert derived.last_line(said) == kept


def test_a_product_written_as_a_link_is_not_written(tmp_path: Path) -> None:
    class Linking(Runs):
        """The stand-in's set, with its parts list moved aside and a link left in its place."""

        def __call__(self, argv: Sequence[str], work: Path, *rest: Any) -> tuple[int | None, str]:
            ended = super().__call__(argv, work, *rest)
            product = Path(work) / "module" / "exports" / "board.csv"
            aside = Path(work) / "aside.csv"
            product.rename(aside)
            product.symlink_to(aside)
            return ended

    found, runs = check(tmp_path, made(SOUND), runs=Linking())
    reason = refused(found, f"{MODULE}/exports/board.csv")
    assert "not written" in reason
    assert len(runs.calls) == 1


def test_an_export_of_a_kind_no_recorded_entry_makes_is_refused(tmp_path: Path) -> None:
    root = stand_in_root(tmp_path, recipe(products=[".erc.json", ".net"]))
    found, runs = check(tmp_path, made(SOUND), root=root)
    reason = refused(found, f"{MODULE}/exports/board.csv")
    assert "names no way to make it again" in reason
    assert runs.calls == []


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


def test_a_commit_touching_no_schematic_and_no_export_regenerates_nothing(
    tmp_path: Path,
) -> None:
    found, runs = check(tmp_path, {f"{MODULE}/notes.txt": b"x\n"})
    assert found.refused_by is None, found.reason
    assert runs.calls == []


def test_a_commit_touching_nothing_in_the_module_asks_for_nothing(tmp_path: Path) -> None:
    assert derived is not None, "physgate.orchestrator.derived holds the exports to the schematic"
    asked: list[int] = []

    def environment() -> ToolEnvironment | None:
        asked.append(1)
        return None

    run, commit = attempt(tmp_path, {"modules/a.txt": b"1\n"})
    base = _git(run.repo, "rev-parse", "main")
    try:
        held = derived.held_exports(
            run.repo, base, commit, MODULE, environment=environment, runner=Runs()
        )
    except Exception as exc:  # noqa: BLE001 - what escapes the check is the finding
        raise AssertionError(f"the check refuses or passes, and never raises: {exc!r}") from None
    told = (getattr(held, "refusal", "no refusal field"), getattr(held, "regenerated", None))
    assert (told, asked) == ((None, 0), [])


def test_which_files_are_sources_is_read_once_the_environment_holds(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    (root / "regen.py").write_text(REGEN, encoding="utf-8")
    record = recorded(root)

    def holds() -> ToolEnvironment | None:
        # What the hold vouches for is what is read: the record's file stands from here on.
        (root / "derived.json").write_text(json.dumps({"derivations": [recipe()]}), "utf-8")
        return record

    files = {f"{MODULE}/board.kicad_sch": SOUND.encode()}
    found, runs = check(tmp_path, files, root=root, environment=holds)
    reason = refused(found, f"{MODULE}/exports/board.erc.json")
    assert "missing" in reason
    assert runs.calls == []


def test_an_environment_that_does_not_hold_refuses_a_change_to_any_file_of_the_module(
    tmp_path: Path,
) -> None:
    def not_held() -> ToolEnvironment | None:
        msg = "the manifest digest of the tool environment is not the recorded one"
        raise InvocationError(msg)

    found, runs = check(tmp_path, {f"{MODULE}/notes.txt": b"x\n"}, environment=not_held)
    reason = refused(found, f"{MODULE}/notes.txt")
    assert "not the recorded one" in reason
    assert runs.calls == []


def test_time_used_up_before_a_set_starts_refuses_it_unrun(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert derived is not None, "physgate.orchestrator.derived holds the exports to the schematic"
    # A clock that stands still: the deadline is now, and no time is left, to the last digit.
    monkeypatch.setattr(derived, "time", SimpleNamespace(monotonic=lambda: 1000.0))
    monkeypatch.setattr(derived, "TOTAL_DEADLINE_S", 0.0)
    found, runs = check(tmp_path, made(SOUND))
    assert found.refused_by == "exports", (found.refused_by, found.reason)
    assert found.reason is not None and "deadline" in found.reason, found.reason
    assert runs.calls == []


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
        # The core places the end of the options itself, once: a record that places one too
        # would hand the program a second, which it reads as a path.
        (recipe(argv=["{interpreter}", "-I", "{root}/regen.py", "--", "{source}"]), "options"),
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


def test_a_held_record_outside_its_shape_refuses_the_change(tmp_path: Path) -> None:
    root = stand_in_root(tmp_path, recipe(timeout_s=0))
    found, runs = check(tmp_path, made(SOUND), root=root)
    reason = refused(found, f"{MODULE}/exports/board.csv")
    assert "record of how exports are made is refused" in reason
    assert runs.calls == []


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
    assert regeneration is not None, "physgate.oslayer.regeneration runs the regeneration"
    from physgate.oslayer.containment import ContainmentError

    marker = tmp_path / "ran"
    for platform in ("linux", "sunos5"):
        run = regeneration.contained_runner(platform=platform, bwrap=None)
        with pytest.raises(ContainmentError):
            run([sys.executable, "-c", f"open({str(marker)!r}, 'w')"], tmp_path, {}, 5.0, [])
    assert not marker.exists()


def test_the_wrapper_is_named_in_code_and_found_on_absolute_folders_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert regeneration is not None, "physgate.oslayer.regeneration runs the regeneration"
    assert regeneration.WRAPPER == "bwrap"
    tree, system = tmp_path / "role-tree", tmp_path / "system"
    for folder in (tree, system):
        folder.mkdir()
        (folder / "bwrap").write_text("#!/bin/sh\n", encoding="utf-8")
        (folder / "bwrap").chmod(0o755)
    monkeypatch.chdir(tree)
    assert regeneration.wrapper_on(os.pathsep.join([".", "role-tree/.."])) is None
    found = regeneration.wrapper_on(os.pathsep.join([".", str(system)]))
    assert found == str(system / "bwrap"), found


def test_the_runner_says_the_exit_code_and_the_end_of_the_error_stream(tmp_path: Path) -> None:
    assert regeneration is not None, "physgate.oslayer.regeneration runs the regeneration"
    bound = getattr(regeneration, "MAX_SAID_BYTES", None)
    assert bound == 4096, "a stated bound on the error stream kept"
    loud = "import sys; sys.stderr.write('x' * 10000 + 'END'); sys.exit(4)"
    code, said = regeneration._run([sys.executable, "-c", loud], tmp_path, {}, 20.0)  # noqa: SLF001
    assert code == 4
    assert said.endswith("END") and len(said) <= bound, (len(said), said[-10:])
    slow = "import time; time.sleep(30)"
    ended = regeneration._run([sys.executable, "-c", slow], tmp_path, {}, 0.5)  # noqa: SLF001
    assert ended == (None, "")


def test_the_core_starts_no_process_and_the_checker_s_runner_is_the_os_layer_s() -> None:
    core = REPO / "src" / "physgate" / "orchestrator" / "derived.py"
    text = core.read_text("utf-8")
    for word in ("subprocess", "sandbox", "bwrap", "seatbelt"):
        assert word not in text.casefold(), word
    assert regeneration is not None, "physgate.oslayer.regeneration runs the regeneration"
    assert callable(getattr(regeneration, "default_runner", None))


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


# ---- what the machine does to a regeneration: a refusal with a short reason, never a raise -----

SOURCE = f"{MODULE}/board.kicad_sch"


def _raised(call: Callable[[], object]) -> BaseException | None:
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - every kind is wanted here
        return exc
    return None


def said_of(found: ports.ChangeCheck, source: str = SOURCE) -> str:
    """The refusal's words after the source's path: what it says went wrong, held short."""
    reason = refused(found, source)
    said = reason.split(source, 1)[1]
    assert len(said) <= 300, len(said)
    return said


class Raising(Runs):
    """A runner that raises ``error`` in place of running the command."""

    def __init__(self, error: BaseException) -> None:
        super().__init__()
        self.error = error

    def __call__(self, argv: Sequence[str], work: Path, *rest: Any) -> tuple[int | None, str]:
        self.calls.append({"argv": list(argv), "work": Path(work)})
        raise self.error


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (FileNotFoundError(errno.ENOENT, "No such file or directory", "bwrap"), "FileNotFoundError"),
        (PermissionError(errno.EACCES, "Permission denied", "sandbox-exec"), "PermissionError"),
        (OSError(errno.EIO, "Input/output error"), "OSError"),
    ],
    ids=["the wrapper program gone", "permission", "input-output"],
)
def test_a_runner_that_meets_the_machine_is_a_refusal_never_a_raise(
    tmp_path: Path, error: OSError, kind: str
) -> None:
    found, runs = check_never_raising(tmp_path, made(SOUND), runs=Raising(error))
    said = said_of(found)
    assert kind in said and "could not be made again" in said, said
    assert str(error.filename) not in said, said
    assert len(runs.calls) == 1 and not runs.calls[0]["work"].exists()


def test_a_folder_that_cannot_be_made_for_the_regeneration_is_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert derived is not None, "physgate.orchestrator.derived holds the exports to the schematic"

    def no_room(*_: object, **__: object) -> str:
        raise OSError(errno.ENOSPC, "No space left on device")

    files = made(SOUND)
    monkeypatch.setattr(derived, "tempfile", SimpleNamespace(mkdtemp=no_room))
    found, runs = check_never_raising(tmp_path, files)
    assert "No space left on device" in said_of(found)
    assert runs.calls == []


def _plumbed(tmp_path: Path, files: dict[str, bytes]) -> tuple[Path, str, str]:
    """A repository whose second commit holds ``files``, written by git's plumbing alone.

    A path no folder on this machine can hold is committed the way a role's session could
    commit it: into the index and the tree, never into a working tree.
    """
    repo = tmp_path / "plumbed"
    (repo / "modules").mkdir(parents=True)
    (repo / "modules" / "a.txt").write_text("0\n")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "start")
    base = _git(repo, "rev-parse", "HEAD")
    for path, data in files.items():
        blob = subprocess.run(
            ["git", "hash-object", "-w", "--stdin"],
            cwd=repo, env=_ENV, input=data, capture_output=True, check=True,
        ).stdout.decode().strip()  # fmt: skip
        _git(repo, "update-index", "--add", "--cacheinfo", f"100644,{blob},{path}")
    tree = _git(repo, "write-tree")
    return repo, base, _git(repo, "commit-tree", tree, "-p", base, "-m", "attempt")


def _held_directly(
    repo: Path, base: str, commit: str, record: ToolEnvironment, runs: Runs
) -> object:
    assert derived is not None, "physgate.orchestrator.derived holds the exports to the schematic"
    try:
        held = derived.held_exports(
            repo, base, commit, MODULE, environment=lambda: record, runner=runs
        )
    except Exception as exc:  # noqa: BLE001 - what escapes the check is the finding
        raise AssertionError(f"the check refuses or passes, and never raises: {exc!r}") from None
    return getattr(held, "refusal", held)


def test_a_source_too_deep_to_be_placed_in_the_fresh_folder_is_a_refusal(tmp_path: Path) -> None:
    assert derived is not None, "physgate.orchestrator.derived holds the exports to the schematic"
    deep = "/".join(["d" * 200] * 25)  # past every platform's longest path
    source = f"{MODULE}/{deep}/board.kicad_sch"
    files = {path: data for path, data in made(SOUND).items() if "/exports/" in path}
    files[source] = SOUND.encode()
    repo, base, commit = _plumbed(tmp_path, files)
    runs = Runs()
    refusal = _held_directly(repo, base, commit, recorded(stand_in_root(tmp_path)), runs)
    assert isinstance(refusal, derived.ExportRefusal), refusal
    assert refusal.subject == source
    said = refusal.reason.split(source, 1)[1]
    assert "could not be made again" in said and len(said) <= 300, said
    assert runs.calls == []


def test_a_git_read_that_fails_while_a_set_is_made_again_is_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert derived is not None, "physgate.orchestrator.derived holds the exports to the schematic"
    real = derived.git

    def failing(repo: Path, *args: str, **given: Any) -> str:  # noqa: ANN401
        if "cat-file" in args:
            msg = "git cat-file failed: fatal: not a valid object name"
            raise GitError(msg)
        return real(repo, *args, **given)

    monkeypatch.setattr(derived, "git", failing)
    found, runs = check_never_raising(tmp_path, made(SOUND))
    said = said_of(found)
    assert "GitError" in said and "not a valid object" not in said, said
    assert runs.calls == []


@pytest.mark.parametrize("step", ["lstat", "read_bytes"])
def test_a_record_that_cannot_be_read_is_a_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, step: str
) -> None:
    real = getattr(Path, step)

    def denied(self: Path, *args: Any, **given: Any) -> Any:  # noqa: ANN401
        if self.name == "derived.json":
            raise PermissionError(errno.EACCES, "Permission denied", str(self))
        return real(self, *args, **given)

    files, root = made(SOUND), stand_in_root(tmp_path)
    monkeypatch.setattr(Path, step, denied)
    found, runs = check_never_raising(tmp_path, files, root=root)
    reason = refused(found, f"{MODULE}/exports/board.csv")
    assert "record of how exports are made is refused" in reason, reason
    assert "PermissionError" in reason, reason
    assert runs.calls == []


def test_a_fault_of_the_code_is_never_taken_as_a_pass(tmp_path: Path) -> None:
    try:
        found, _ = check(tmp_path, made(SOUND), runs=Raising(TypeError("a fault of the code")))
    except TypeError:
        return
    assert found.refused_by == "exports", (found.refused_by, found.reason)


@dataclass
class Given(FakeChanges):
    """The loop's change check, answering each call with a check the real checker made."""

    given: list[ports.ChangeCheck] = field(default_factory=list)

    def check(
        self,
        subtask_id: str,
        attempt_commit: str,
        role: str,
        *,
        series: SessionSeries | None = None,
        follows: int | None = None,
    ) -> ports.ChangeCheck:
        super().check(subtask_id, attempt_commit, role, series=series, follows=follows)
        return self.given[self.calls - 1]


def test_the_loop_rejects_the_attempt_on_a_regeneration_the_machine_stopped_and_goes_on(
    tmp_path: Path,
) -> None:
    stopped, _ = check_never_raising(
        tmp_path / "stopped", made(SOUND), runs=Raising(OSError(errno.EIO, "Input/output error"))
    )
    passed, _ = check_never_raising(tmp_path / "passed", made(SOUND))
    assert stopped.refused_by == "exports" and passed.refused_by is None
    where = tmp_path / "loop"
    where.mkdir()
    loop = Rig(where, changes=Given(given=[stopped, passed])).open()
    loop.start(plan("s1"))
    loop.run()
    loop.close()
    lines = events.read_events(where / "events.jsonl")
    checked = [e for e in lines if isinstance(e, events.ProposalsChecked)]
    told = [(e.attempt, e.refused_by, getattr(e, "exports_regenerated", "absent")) for e in checked]
    assert told == [(1, "exports", 0), (2, None, 1)], told
    assert checked[0].reason == stopped.reason
    rejected = [e for e in lines if isinstance(e, events.AttemptRejected)]
    assert [(e.attempt, e.finding.source, e.finding.subject) for e in rejected] == [
        (1, "exports", SOURCE)
    ]
    assert not [e for e in lines if isinstance(e, events.Incident)]


# ---- how many sets the check made again -----------------------------------------------------


def test_the_check_says_how_many_sets_it_made_again(tmp_path: Path) -> None:
    one, _ = check(tmp_path / "one", made(SOUND))
    two, _ = check(tmp_path / "two", _sets_of(2))
    none, _ = check(tmp_path / "none", {f"{MODULE}/notes.txt": b"x\n"})
    told = [getattr(found, "exports_regenerated", "absent") for found in (one, two, none)]
    assert told == [1, 2, 0], told


def test_a_refusal_counts_the_sets_made_again_equal_before_it(tmp_path: Path) -> None:
    files = _sets_of(2)
    files[f"{MODULE}/board1.kicad_sch"] = (SOUND + "FAIL\n").encode()
    found, runs = check(tmp_path, files)
    assert found.refused_by == "exports", (found.refused_by, found.reason)
    assert getattr(found, "exports_regenerated", "absent") == 1
    assert len(runs.calls) == 2


def test_a_check_refused_before_the_exports_are_reached_records_no_count(tmp_path: Path) -> None:
    found, runs = check(tmp_path, {**made(SOUND), "outside.txt": b"x\n"})
    assert found.refused_by == "write_scope", (found.refused_by, found.reason)
    assert getattr(found, "exports_regenerated", "absent") is None
    assert runs.calls == []


def _checked_line(**more: object) -> dict[str, object]:
    return {
        "seq": 3,
        "ts": "2026-11-15T10:00:00.000000Z",
        "run_id": "r1",
        "gate_mode": "on",
        "kind": "proposals_checked",
        "subtask_id": "s1",
        "attempt": 1,
        "checked_commit": "a" * 40,
        "refused_by": None,
        "reason": None,
        "subject": None,
        "graph_root": "scratch/graph",
        **more,
    }


def test_the_count_is_on_the_change_check_s_line_and_an_old_line_reads_as_before() -> None:
    assert "exports_regenerated" in ports.ChangeCheck.model_fields, "the check says its count"
    assert "exports_regenerated" in events.ProposalsChecked.model_fields, "its line says it too"
    old = events.ProposalsChecked.model_validate(_checked_line())
    assert getattr(old, "exports_regenerated", "absent") is None
    assert "exports_regenerated" not in json.loads(old.model_dump_json())
    for count in (0, 3):
        line = events.ProposalsChecked.model_validate(_checked_line(exports_regenerated=count))
        assert json.loads(line.model_dump_json())["exports_regenerated"] == count
    with pytest.raises(ValueError, match="exports_regenerated"):
        events.ProposalsChecked.model_validate(_checked_line(exports_regenerated=-1))


# ---- the name and the end of the options, in the core itself -------------------------------------


@pytest.mark.parametrize(
    "stem", ["-board", "my board", "bo\nard"], ids=["leading dash", "space", "newline"]
)
def test_the_core_refuses_a_name_outside_the_safe_shape_before_any_run(
    tmp_path: Path, stem: str
) -> None:
    assert derived is not None, "physgate.orchestrator.derived holds the exports to the schematic"
    run, commit = attempt(tmp_path, made(SOUND, stem=stem))
    base = _git(run.repo, "rev-parse", "main")
    runs = Runs()
    refusal = _held_directly(run.repo, base, commit, recorded(stand_in_root(tmp_path)), runs)
    assert isinstance(refusal, derived.ExportRefusal), refusal
    assert refusal.subject == f"{MODULE}/{stem}.kicad_sch", refusal
    assert "name" in refusal.reason, refusal.reason
    assert runs.calls == []


def test_the_end_of_the_options_stands_before_the_first_path_the_command_is_given(
    tmp_path: Path,
) -> None:
    found, runs = check(tmp_path, made(SOUND))
    assert found.refused_by is None, found.reason
    (call,) = runs.calls
    argv, work = call["argv"], call["work"]
    source = str(work / "module" / "board.kicad_sch")
    assert argv.count("--") == 1, argv
    assert argv.index("--") == argv.index(source) - 1, argv
    assert argv[:3] == [sys.executable, "-I", str(tmp_path / "root" / "regen.py")], argv


# ---- the runner's bounds, its session, and what it leaves behind ----------------------------


def test_a_regeneration_past_a_bound_is_a_refusal_in_the_runner_s_words(tmp_path: Path) -> None:
    assert regeneration is not None, "physgate.oslayer.regeneration runs the regeneration"
    bound = getattr(regeneration, "RegenerationBoundError", None)
    assert bound is not None, "the runner says a bound was passed by an error of its own"
    error = bound("the regeneration wrote more than 256000000 bytes into its folder")
    found, runs = check_never_raising(tmp_path, made(SOUND), runs=Raising(error))
    assert "more than 256000000 bytes" in said_of(found)


def test_an_error_stream_past_its_bound_refuses_and_the_program_is_ended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert regeneration is not None, "physgate.oslayer.regeneration runs the regeneration"
    bound = getattr(regeneration, "MAX_ERROR_BYTES", None)
    assert isinstance(bound, int), "a stated bound on what a regeneration writes to its errors"
    monkeypatch.setattr(regeneration, "MAX_ERROR_BYTES", 100_000)
    loud = "import sys, time; sys.stderr.write('x' * 200_000); sys.stderr.flush(); time.sleep(30)"
    started = time.monotonic()
    raised = _raised(
        lambda: regeneration._run([sys.executable, "-c", loud], tmp_path, {}, 60.0)  # noqa: SLF001
    )
    assert type(raised).__name__ == "RegenerationBoundError", raised
    assert time.monotonic() - started < 20.0, "the program was waited for, not ended"


@pytest.mark.parametrize("then", ["sleeps", "ends"])
def test_a_regeneration_that_writes_past_the_folder_s_bound_refuses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, then: str
) -> None:
    assert regeneration is not None, "physgate.oslayer.regeneration runs the regeneration"
    bound = getattr(regeneration, "MAX_WRITTEN_BYTES", None)
    assert isinstance(bound, int), "a stated bound on what a regeneration writes into its folder"
    monkeypatch.setattr(regeneration, "MAX_WRITTEN_BYTES", 100_000)
    work = tmp_path / "work"
    (work / "deep").mkdir(parents=True)
    rest = "time.sleep(30)" if then == "sleeps" else "pass"
    big = f"import time; open('deep/big', 'wb').write(b'x' * 200_000); {rest}"
    started = time.monotonic()
    raised = _raised(
        lambda: regeneration._run([sys.executable, "-c", big], work, {}, 60.0)  # noqa: SLF001
    )
    assert type(raised).__name__ == "RegenerationBoundError", raised
    assert time.monotonic() - started < 20.0, "the program was waited for, not ended"


def test_the_regeneration_runs_in_a_session_of_its_own(tmp_path: Path) -> None:
    assert regeneration is not None, "physgate.oslayer.regeneration runs the regeneration"
    said = "import os, sys; sys.stderr.write(str(os.getsid(0)))"
    code, out = regeneration._run([sys.executable, "-c", said], tmp_path, {}, 20.0)  # noqa: SLF001
    assert code == 0, out
    assert out.strip() and out.strip() != str(os.getsid(0)), out


@pytest.mark.parametrize("child", ["times out", "ends"])
def test_nothing_the_regeneration_started_outlives_it(tmp_path: Path, child: str) -> None:
    assert regeneration is not None, "physgate.oslayer.regeneration runs the regeneration"
    marker = tmp_path / "left-behind"
    grandchild = f"import time; time.sleep(2); open({str(marker)!r}, 'w')"
    rest = "time.sleep(30)" if child == "times out" else "pass"
    program = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}]); {rest}"
    )
    regeneration._run([sys.executable, "-c", program], tmp_path, {}, 1.0)  # noqa: SLF001
    time.sleep(3.5)
    assert not marker.exists(), "a process the regeneration started went on after it ended"
