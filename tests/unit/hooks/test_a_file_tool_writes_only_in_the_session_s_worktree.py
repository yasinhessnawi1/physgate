"""A file tool writes in its session's worktree, and nowhere else.

The hook layer's rules name what is protected. A write no rule named was allowed, wherever it
went: the worktree's parent, the operator's home (a shell startup file there runs code as the
operator), another run's records, a round's output, the shared temporary directories. A file tool
runs in the client's own process, outside the OS layer, so the hook is the one bound it meets, and
nothing could list every place where a write would matter. So a write by ``Write``, ``Edit`` or
``NotebookEdit`` is refused unless its target, as written and as resolved, lies exactly beneath
the session's worktree with no link on the way; the listed rules are asked first, so each refusal
they give keeps its reason, and the new refusal names no path outside the worktree.

Each session here is installed by the real installer from the argument list its real spawner
builds: a role session by the dispatcher's own ``_install`` (in the OS layer, with hooks only, and
with ``hooks: off``), a raw baseline session by the raw arm's own ``_install`` (a round's trial,
and outside a round), the ``orchestrator`` profile from its request, and a reviewer from the
argument list its spawner writes. Each call is judged by the generated PreToolUse command's own
entry point, every wired hook taking part, after a real SessionStart and the required reading.
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "orchestrator"))
from orch_helpers import SCRIPTED_BOUNDS, make_config  # noqa: E402

from physgate.evaluation.per_role.arms import raw  # noqa: E402
from physgate.hooks import cli as hooks_cli  # noqa: E402
from physgate.hooks import paths, runtime  # noqa: E402
from physgate.hooks.config import SessionConfig  # noqa: E402
from physgate.hooks.registry import REGISTRY  # noqa: E402
from physgate.hooks.settings import (  # noqa: E402
    InstallRequest,
    build_config,
    current_installation,
    install,
)
from physgate.orchestrator import dispatch  # noqa: E402
from physgate.orchestrator.credentials import Credential  # noqa: E402
from physgate.orchestrator.dispatch import harness_protection, place_apart  # noqa: E402
from physgate.orchestrator.merge import RunGit  # noqa: E402
from physgate.orchestrator.ports import SessionRequest  # noqa: E402
from physgate.oslayer.probe import Absent, shared_temp_dirs  # noqa: E402

try:
    from physgate.orchestrator import left_out
except ImportError:  # the code before the scratch folder existed: the row fails on its words
    left_out = None  # type: ignore[assignment]

#: The machine's own shared temporary directories: their refusal is one of the rows here.
pytestmark = pytest.mark.machine_temps

SID = "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0"
REVIEW_ID = "7d0c5e1a-3b2f-4c6d-8e9f-0a1b2c3d4e5f"
#: Named to the installer, never made: the session's own temporary directory and another's.
OWN_TEMP = Path("/var/tmp/pgs/0123456789")
OTHER_TEMP = Path("/var/tmp/pgs/ffffffffff")
WRITERS = ("Write", "Edit", "NotebookEdit")
GIT_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": os.devnull,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}

#: What the new refusal says, in words that do not depend on the call.
OUTSIDE = "file tools write only in its own worktree"

# The listed rules' reasons, by a phrase of each.
WT_SETTINGS = "a settings write can switch the hooks off"
HARNESS = "the checkout the orchestrator runs from"
HOOK_CODE = "the code the hooks run from"
REVIEW_MATERIAL = "material only the paired reviewer reads"
RUN_RECORD = "one of the run's own records, which the orchestrator alone writes"
WITHHELD_RECORD = "one of the run's own records that no session doing design work reads"
RUN_ROOT = "the orchestrator protects it for this session"
SESSIONS = "the run's session directories"
HELD_OUT = "held-out evaluation tier"
WITHHELD_WHOLE = "withheld from this session whole"
CLAUDE_TEMP = "every Claude Code session of this user"
SHARED_TEMP = "write temporary files in this session's own temporary directory, which $TMPDIR"
HARNESS_TEMPS = "where the harness keeps its own temporary files"
OWN_TEMPS = "where each session keeps its own temporary files"
TWO_NAMES = paths.HARD_LINKED
HOME_CLAUDE = "Claude Code's own directory in this session's home"


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, env=GIT_ENV, check=True, capture_output=True)


def _write(path: Path, text: str = "stand-in\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def make_layout(base: Path) -> SimpleNamespace:
    """A stand-in for the operator's home: a run, another run, a review root, a round, a store."""
    home = base / "home"
    run_dir = home / "physgate-runs" / "run-a"
    repo = home / "target"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q", "-b", "main")
    _write(repo / "README.md", "a target\n")
    _write(repo / "modules" / "electrical" / "driver.py", "x = 1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")
    run = RunGit(repo=repo, run_dir=run_dir, run_id="run-a")
    for name, branch in (
        ("_integration", run.run_branch),
        ("s1", run.subtask_branch("s1")),
        ("s2", run.subtask_branch("s2")),
    ):
        _git(repo, "worktree", "add", "-q", "-b", branch, str(run_dir / "worktrees" / name))
    for name in ("run.json", "events.jsonl", "ledger.jsonl", "queue.jsonl", "writes.jsonl"):
        _write(run_dir / name, "")
    _write(run_dir / "queue_decisions.jsonl", "")
    _write(run_dir / "decomposition" / "plan.json", "{}\n")
    (run_dir / "series").mkdir()
    _write(run_dir / "store" / "journal.jsonl", "")
    other = home / "physgate-runs" / "run-b"
    for name in ("run.json", "events.jsonl", "ledger.jsonl"):
        _write(other / name, '{"other": "run"}\n')
    review = home / "review-scratch"
    _write(review / "r0123456789ab" / "read" / "brief.md", "a packet's brief\n")
    _write(review / "r0123456789ab" / "session" / "verdict.json", "{}\n")
    _write(home / "rounds" / "round-1" / "round.json", '{"round": 1}\n')
    _write(home / "notes" / "existing.txt", "a\n")
    twice = _write(home / "notes" / "twice.txt", "a\n")
    os.link(twice, home / "notes" / "twice-second-name.txt")
    _write(home / ".claude" / "settings.json", "{}\n")
    _write(home / ".claude" / "CLAUDE.md", "the operator's own instructions\n")
    _write(home / ".local" / "bin" / "tool", "#!/bin/sh\necho a\n")
    _write(home / "dev" / "other-checkout" / "src" / "physgate" / "gate" / "check.py", "a\n")
    store = home / "tiers-store"
    _write(store / "control" / "withheld" / "pool" / "task.json", "{}\n")
    (store / "control" / "work").mkdir(parents=True)
    (home / "install" / "bin").mkdir(parents=True)
    # A stand-in for the checkout the orchestrator runs from. The real one is the checkout these
    # rows run in, where other test processes compile bytecode while a session's sentinel would
    # put its source tree back.
    harness = home / "harness"
    _write(harness / "pyproject.toml", "[project]\nname = 'stand-in'\n")
    _write(harness / "src" / "physgate" / "gate" / "check.py", "CHECK = True\n")
    _write(harness / "knowledge" / "control" / "skill.md", "a skill\n")
    return SimpleNamespace(
        harness=harness,
        home=home,
        run=run,
        run_dir=run_dir,
        repo=repo,
        other=other,
        review=review,
        store=store,
    )


def _installer_in_process(
    monkeypatch: pytest.MonkeyPatch, seen: list[list[str]], *, waive: bool
) -> None:
    """The spawner's ``hooks install`` call, run by the installer's own command in this process.

    ``waive``: whether the layer may be absent, and whether hooks may be off, are the run
    configuration's own questions, with rows of their own; waived here, as those rows do.
    """
    real_run = subprocess.run

    def run(argv: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:  # noqa: ANN401
        if list(argv[1:3]) == ["hooks", "install"]:
            seen.append(list(argv))
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = hooks_cli.main(argv[1:])
            return subprocess.CompletedProcess(argv, code, out.getvalue(), err.getvalue())
        return real_run(argv, **kw)

    monkeypatch.setattr(subprocess, "run", run)
    if waive:
        monkeypatch.setattr(hooks_cli, "_os_layer_refusal", lambda _args: None)
        monkeypatch.setattr(hooks_cli, "_hooks_refusal", lambda _args: None)


def install_role(
    lay: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
    *,
    review_root: Path,
    layer: bool,
    hooks: str = "on",
) -> tuple[Path, Path]:
    """A role session of run-a in ``worktrees/s1``, by the dispatcher's own ``_install``."""
    seen: list[list[str]] = []
    _installer_in_process(monkeypatch, seen, waive=not layer or hooks == "off")
    dispatcher = dispatch.ClaudeDispatcher(
        config=make_config(run_id="run-a"),
        run=lay.run,
        store_root=lay.run_dir / "store",
        install_bin=lay.home / "install" / "bin" / "physgate",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        review_root=review_root,
    )
    if hooks == "off":
        # An ablation run's configuration is made only from a clean checkout with a commit; the
        # arm is one field the dispatcher reads, set here on a copy.
        dispatcher._config = dispatcher._config.model_copy(update={"hooks": "off"})
    # The interface contracts are read from the run's event log; none take part here.
    monkeypatch.setattr(dispatcher, "_contracts", lambda _request: ())
    request = SessionRequest(
        subtask_id="s1",
        attempt=1,
        assigned_role="control",
        spec_path=".physgate/specs/s1.md",
        module_dir="modules/control",
        model="claude-opus-5-5",
        repair_instruction=None,
        bounds=SCRIPTED_BOUNDS,
    )
    worktree = lay.run_dir / "worktrees" / "s1"
    sdir = lay.run_dir / "sessions" / SID
    installed = dispatcher._install(
        request, worktree, sdir, OWN_TEMP if layer else None, own_temp=OWN_TEMP
    )
    assert seen, "the dispatcher ran no installer"
    return worktree, Path(installed.settings)


def install_baseline(
    lay: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, *, trial: bool
) -> tuple[Path, Path, dict[str, Path]]:
    """A raw session by the raw arm's own ``_install``: a round's trial, or one outside a round."""
    seen: list[list[str]] = []
    _installer_in_process(monkeypatch, seen, waive=False)
    store = lay.store
    held = (str(store / "control" / "withheld"), str(store / "control" / "work"))
    setup = raw.RawSetup(
        binary="claude",
        claude_version="2.1.322",
        model="claude-sonnet-5",
        effort="high",
        max_output_tokens=64000,
        thinking_display="summarized",
        bounds=SCRIPTED_BOUNDS,
        credential=Credential(mode="api_key", secret="not-a-key"),
        base_url=None,
        install_bin=lay.home / "install" / "bin" / "physgate",
        role_python=None,
        held_out=held,
        held_out_canaries=(),
        network="open",
        os_layer=Absent(reason="not asked here: the layer's directory is given by hand"),
    )
    extra: dict[str, Path] = {}
    if trial:
        trial_dir = store / "control" / "work" / "baseline-R1-0001-1"
        place = trial_dir / "place"
        out = lay.home / "rounds" / "baseline-out"
        _write(out / "baseline.json", "{}\n")
        _write(trial_dir / "harness" / "raw.json", "{}\n")
        setup = dataclasses.replace(
            setup, held_out_carved=str(place), held_out_also=(os.path.realpath(out),)
        )
        extra = {"round_out": out, "harness_beside": trial_dir / "harness", "place": place}
    else:
        place = lay.home / "raw-work" / "w1"
    worktree, sdir = place / "worktree", place / "session"
    worktree.mkdir(parents=True)
    sdir.mkdir()
    installed = raw._install(setup, worktree, sdir, OWN_TEMP, own_temp=OWN_TEMP)
    assert seen, "the raw arm ran no installer"
    return worktree, Path(installed["settings"]), extra


def install_reviewer(lay: SimpleNamespace) -> tuple[Path, Path]:
    """A reviewer, by the argument list its spawner builds."""
    root = lay.review
    read = root / REVIEW_ID / "read"
    sdir = root / REVIEW_ID / "session"
    worktree = read / "worktree"
    _write(worktree / "answer.md", "the work under review\n")
    rubric = _write(read / "rubric.md", "the rubric\n" * 5)
    state = sdir / "state"
    state.mkdir(parents=True)
    apart = place_apart(root)
    argv = [
        *("hooks", "install", "--profile", "reviewer", "--worktree", str(worktree)),
        *("--read-root", str(read), "--state-dir", str(state), "--target", str(sdir / "settings")),
        *("--claude-config-dir", str(sdir / "config"), "--user-home", str(sdir / "home")),
        *("--temp", str(OWN_TEMP), "--ceiling", "100000", "--reading", str(rubric)),
        *harness_protection(),
        *("--held-out", str(lay.store / "control" / "withheld")),
        *("--sentinel-apart", str(apart)),
    ]
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert hooks_cli.main(argv) == 0
    return worktree, Path(json.loads(out.getvalue())["settings"])


def install_orchestrator_profile(lay: SimpleNamespace) -> tuple[Path, Path]:
    """The ``orchestrator`` profile, from its request; its home is the stand-in home."""
    worktree = lay.home / "dev" / "checkout"
    worktree.mkdir(parents=True)
    sdir = lay.home / "orch-session"
    done = install(
        InstallRequest(
            profile="orchestrator",
            role=None,
            worktree=str(worktree),
            own_branch=None,
            store_root=None,
            state_dir=str(sdir / "state"),
            target_dir=str(sdir / "session"),
            claude_config_dir=str(sdir / "config"),
            user_home=str(lay.home),
            token_ceiling=100_000,
        ),
        REGISTRY,
    )
    return worktree, done.settings_path


class Hooks:
    """The generated hook commands of one installed session, and its log."""

    def __init__(self, settings_path: Path, worktree: Path) -> None:
        self.settings = json.loads(settings_path.read_text())
        self.worktree = worktree
        self.commands = {
            event: groups[0]["hooks"][0]["command"]
            for event, groups in self.settings["hooks"].items()
        }
        argv = shlex.split(self.commands["PreToolUse"])
        assert argv[4:7] == ["-I", "-m", "physgate.hooks"], argv
        config_path = Path(argv[argv.index("--config") + 1])
        self.config = SessionConfig.model_validate_json(config_path.read_bytes())
        self.log = Path(self.config.state_dir) / "hooks.log.jsonl"

    def _stdin(self, event: str, **fields: Any) -> str:  # noqa: ANN401
        return json.dumps(
            {"session_id": SID, "cwd": str(self.worktree), "hook_event_name": event} | fields
        )

    def _log_lines(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []

    def call(self, event: str, **fields: Any) -> tuple[int, str, list[str]]:  # noqa: ANN401
        """One event through the generated command's entry point, in this process.

        The exit code, what the session is told, and the hook log's new lines.
        """
        argv = shlex.split(self.commands[event])[7:]
        before = len(self._log_lines())
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = runtime.main(argv, self._stdin(event, **fields), REGISTRY)
        return code, err.getvalue().strip(), self._log_lines()[before:]

    def call_as_a_process(self, event: str, **fields: Any) -> tuple[int, str]:  # noqa: ANN401
        """The same event through the generated command itself: the trampoline, a new process."""
        done = subprocess.run(
            shlex.split(self.commands[event]),
            input=self._stdin(event, **fields),
            capture_output=True,
            text=True,
            check=False,
            cwd=self.worktree,
        )
        return done.returncode, done.stderr.strip()

    def start(self) -> None:
        """SessionStart, then every required file read in full, as a session does first."""
        for path in self.config.required_reading:
            if not os.path.exists(path):
                _write(Path(path), "A line of required reading.\n" * 5)
        # As a process of its own, as the client starts it: the hook's entry module is compiled
        # then, before the sentinel takes its record of the harness checkout's source.
        code, said = self.call_as_a_process("SessionStart", source="startup")
        assert code == 0, said
        for path in self.config.required_reading:
            lines = len(Path(path).read_text().splitlines()) + 1
            response = {
                "type": "text",
                "file": {"filePath": path, "numLines": lines, "startLine": 1, "totalLines": lines},
            }
            code, said, _ = self.call(
                "PostToolUse",
                tool_name="Read",
                tool_input={"file_path": path},
                tool_response=response,
            )
            assert code == 0, said

    def write(self, tool: str, path: str) -> tuple[int, str, list[str]]:
        return self.call("PreToolUse", tool_name=tool, tool_input=tool_input(tool, path))


def tool_input(tool: str, path: str) -> dict[str, Any]:
    if tool == "Write":
        return {"file_path": path, "content": "written by the row\n"}
    if tool == "Edit":
        return {"file_path": path, "old_string": "a", "new_string": "b"}
    return {"notebook_path": path, "new_source": "x = 1", "cell_id": "c1"}


def _other_case(path: Path, below: Path) -> str:
    """``path`` with everything beneath ``below`` in the other letter case."""
    return str(below / str(path.relative_to(below)).swapcase())


#: The kinds of session that have a writing file tool, by a short name.
WRITING_KINDS = {
    "role-in-the-layer": "a role session in the OS layer, its run's review root the standing one",
    "role-hooks-only": "a role session with hooks only, no OS layer",
    "role-hooks-off": "a role session with hooks: off, in the OS layer",
    "raw-trial": "a raw baseline session, a round's trial",
    "raw-outside-a-round": "a raw baseline session outside a round",
    "orchestrator": "a session of the orchestrator profile",
}
ROLE = ("role-in-the-layer", "role-hooks-only", "role-hooks-off")
RAW = ("raw-trial", "raw-outside-a-round")


def installed(kind: str, base: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """One session of ``kind``, installed and started, in a fresh stand-in home."""
    lay = make_layout(Path(os.path.realpath(base)))
    monkeypatch.setattr(dispatch, "harness_root", lambda: lay.harness)
    extra: dict[str, Path] = {}
    if kind in ROLE:
        worktree, settings = install_role(
            lay,
            monkeypatch,
            review_root=lay.review if kind == "role-in-the-layer" else lay.run_dir / "reviews",
            layer=kind != "role-hooks-only",
            hooks="off" if kind == "role-hooks-off" else "on",
        )
    elif kind in RAW:
        worktree, settings, extra = install_baseline(lay, monkeypatch, trial=kind == "raw-trial")
    elif kind == "reviewer":
        worktree, settings = install_reviewer(lay)
    else:
        worktree, settings = install_orchestrator_profile(lay)
    hooks = Hooks(settings, worktree)
    hooks.start()
    return SimpleNamespace(lay=lay, worktree=worktree, hooks=hooks, extra=extra)


def outside_targets(s: SimpleNamespace) -> list[tuple[str, str, dict[str, str]]]:
    """(what it is, its path, the listed rule that refuses it first, by kind).

    A kind not named in the third field is refused by the worktree rule: no listed rule names
    the target for it. Nothing here is written.
    """
    lay, worktree, home = s.lay, s.worktree, s.lay.home
    (worktree / "link-dir-out").symlink_to(home / "notes")
    (worktree / "link-file-out").symlink_to(home / "notes" / "existing.txt")
    (worktree / "link-review-out").symlink_to(lay.review)
    up = os.path.relpath(home / "notes", worktree)
    trial = {"raw-trial": WITHHELD_WHOLE}
    role_only = dict.fromkeys(ROLE, "")
    rows: list[tuple[str, str, dict[str, str]]] = [
        ("a new file in the worktree's parent", str(worktree.parent / "new.txt"), trial),
        ("a file two levels above the worktree", str(worktree.parent.parent / "new.txt"), trial),
        ("home: a file in a directory no rule names", str(home / "notes" / "new.txt"), {}),
        ("home: a shell startup file", str(home / ".zshenv"), {}),
        (
            "home: the operator's own client settings",
            str(home / ".claude" / "settings.json"),
            {"orchestrator": HOME_CLAUDE},
        ),
        (
            "home: the operator's own client instructions",
            str(home / ".claude" / "CLAUDE.md"),
            {"orchestrator": HOME_CLAUDE},
        ),
        ("home: a tool on the operator's path", str(home / ".local" / "bin" / "tool"), {}),
        ("home: a launch agent", str(home / "Library" / "LaunchAgents" / "x.plist"), {}),
        (
            "home: another checkout's gate source",
            str(home / "dev" / "other-checkout" / "src" / "physgate" / "gate" / "check.py"),
            {},
        ),
        (
            "a review root no rule names, a packet's brief",
            str(lay.review / "r0123456789ab" / "read" / "brief.md"),
            {"role-in-the-layer": REVIEW_MATERIAL},
        ),
        (
            "a review root no rule names, a verdict",
            str(lay.review / "r0123456789ab" / "session" / "verdict.json"),
            {"role-in-the-layer": REVIEW_MATERIAL},
        ),
        (
            "a review root, through a link in the worktree",
            str(worktree / "link-review-out" / "new.txt"),
            {"role-in-the-layer": REVIEW_MATERIAL, **trial},
        ),
        (
            "a round's output folder, its record",
            str(home / "rounds" / "round-1" / "round.json"),
            {},
        ),
        ("a round's output folder, a new file", str(home / "rounds" / "round-1" / "new.json"), {}),
        ("another run's event log", str(lay.other / "events.jsonl"), {}),
        ("another run's ledger", str(lay.other / "ledger.jsonl"), {}),
        ("another run's configuration", str(lay.other / "run.json"), {}),
        (
            "the session's own run's event log",
            str(lay.run_dir / "events.jsonl"),
            {k: RUN_RECORD for k in role_only},
        ),
        (
            "the session's own run's configuration",
            str(lay.run_dir / "run.json"),
            {k: WITHHELD_RECORD for k in role_only},
        ),
        ("a new name in the session's own run directory", str(lay.run_dir / "review.json"), {}),
        (
            "another subtask's worktree in the same run",
            str(lay.run_dir / "worktrees" / "s2" / "modules" / "electrical" / "driver.py"),
            {},
        ),
        (
            "the run's integration worktree",
            str(lay.run_dir / "worktrees" / "_integration" / "README.md"),
            {k: RUN_ROOT for k in role_only},
        ),
        (
            "a session directory of the run",
            str(lay.run_dir / "sessions" / SID / "config" / "x.json"),
            {k: SESSIONS for k in role_only},
        ),
        ("the target repository's own checkout", str(lay.repo / "README.md"), {}),
        (
            "the tier-set store, a pool task",
            str(lay.store / "control" / "withheld" / "pool" / "task.json"),
            dict.fromkeys(RAW, HELD_OUT),
        ),
        (
            "/tmp, a new file",
            "/tmp/never-made-by-the-row.txt",
            {k: SHARED_TEMP for k in (*ROLE, *RAW)},
        ),
        ("/var/tmp, a new file", "/var/tmp/never-made-by-the-row.txt", {}),
        *(
            (
                "a shared temporary directory, a new file",
                f"{d}/never-made-by-the-row.txt",
                {k: SHARED_TEMP for k in (*ROLE, *RAW)},
            )
            for d in shared_temp_dirs()
        ),
        (
            "the place the harness keeps its own temporary files",
            "/var/tmp/pgh/0123456789/physgate-git-store-x/config",
            {k: HARNESS_TEMPS for k in (*ROLE, *RAW)},
        ),
        (
            "Claude Code's shared temporary directory",
            f"/tmp/claude-{os.getuid()}/never-made-by-the-row.txt",
            {k: CLAUDE_TEMP for k in (*ROLE, *RAW)},
        ),
        (
            "the session's own temporary directory",
            str(OWN_TEMP / "helper.py"),
            {k: OWN_TEMPS for k in (*ROLE, *RAW)},
        ),
        (
            "another session's temporary directory",
            str(OTHER_TEMP / "helper.py"),
            {k: OWN_TEMPS for k in (*ROLE, *RAW)},
        ),
        (
            "an existing file outside the worktree, overwritten",
            str(home / "notes" / "existing.txt"),
            {},
        ),
        (
            "an existing file outside the worktree with two names",
            str(home / "notes" / "twice.txt"),
            dict.fromkeys(WRITING_KINDS, TWO_NAMES),
        ),
        (
            "through a directory link in the worktree",
            str(worktree / "link-dir-out" / "new.txt"),
            trial,
        ),
        ("through a file link in the worktree", str(worktree / "link-file-out"), trial),
        ("through .., absolute", f"{worktree}/{up}/new.txt", {}),
        ("through .., relative to the working directory", f"{up}/new.txt", {}),
        ("through a link and then ..", str(worktree / "link-dir-out" / ".." / ".zshenv"), {}),
        ("the home's shell startup file, spelt with ~", "~/.zshenv", {}),
        (
            "the worktree in another letter case",
            _other_case(worktree / "case-new.txt", home),
            trial,
        ),
        (
            "an unnamed file outside, in another letter case",
            _other_case(home / "notes" / "existing.txt", home),
            {},
        ),
        (
            "the run's configuration, in another letter case",
            _other_case(lay.run_dir / "run.json", home),
            {k: WITHHELD_RECORD for k in role_only},
        ),
    ]
    rows += [
        (f"a round's trial: {name}", str(path / "new.txt"), {"raw-trial": reason})
        for name, path, reason in (
            ("the round's own output folder", s.extra.get("round_out"), HELD_OUT),
            (
                "the harness's directory beside the session's place",
                s.extra.get("harness_beside"),
                HELD_OUT,
            ),
            ("the session's own place beside its worktree", s.extra.get("place"), WITHHELD_WHOLE),
        )
        if path is not None
    ]
    return rows


def _expected(kind: str, rules: dict[str, str]) -> str:
    return rules.get(kind) or OUTSIDE


@pytest.mark.parametrize("kind", list(WRITING_KINDS), ids=list(WRITING_KINDS))
def test_a_write_outside_the_worktree_is_refused_to_every_session_that_has_a_writing_tool(
    kind: str, outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = installed(kind, outside_tmp, monkeypatch)
    wrong: list[str] = []
    for what, path, rules in outside_targets(s):
        want = _expected(kind, rules)
        for tool in WRITERS:
            code, said, _ = s.hooks.write(tool, path)
            if code == 0 or want not in said or f"The {tool} call is refused" not in said:
                wrong.append(f"{tool} {what}: wanted {want!r}, told {said[:300]!r}")
    assert not wrong, "\n".join(wrong)


@pytest.mark.parametrize("kind", list(WRITING_KINDS), ids=list(WRITING_KINDS))
def test_a_write_inside_the_worktree_is_allowed_as_before(
    kind: str, outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = installed(kind, outside_tmp, monkeypatch)
    worktree = s.worktree
    _write(worktree / "notes" / "existing.md", "a\n")
    targets = [
        str(worktree / "notes" / "existing.md"),
        str(worktree / "new.py"),
        str(worktree / "modules" / "control" / "scratch" / "helper.py"),
        "notes/existing.md",
        "./modules/control/new.ipynb",
        f"{worktree}/modules/../notes/new.md",
    ]
    # The worktree spelt as the system resolves it, where that is another spelling (on macOS a
    # temporary directory under /var is /private/var).
    resolved = os.path.realpath(worktree)
    targets.append(f"{resolved}/resolved-spelling.txt")
    refused = [
        f"{tool} {path}: {said[:300]}"
        for path in targets
        for tool in WRITERS
        for code, said, _ in [s.hooks.write(tool, path)]
        if code != 0
    ]
    assert not refused, "\n".join(refused)


@pytest.mark.parametrize("kind", list(WRITING_KINDS), ids=list(WRITING_KINDS))
def test_every_refusal_a_listed_rule_gives_keeps_its_reason(
    kind: str, outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = installed(kind, outside_tmp, monkeypatch)
    rows = [
        (str(s.worktree / ".claude" / "settings.json"), WT_SETTINGS),
        (str(Path(hooks_cli.__file__).resolve()), HOOK_CODE),
        (
            str(s.lay.harness / "src" / "physgate" / "gate" / "check.py"),
            OUTSIDE if kind == "orchestrator" else HARNESS,
        ),
    ]
    wrong = [
        f"{tool} {path}: wanted {want!r}, told {said[:300]!r}"
        for path, want in rows
        for tool in WRITERS
        for code, said, _ in [s.hooks.write(tool, path)]
        if code == 0 or want not in said or (want != OUTSIDE and OUTSIDE in said)
    ]
    assert not wrong, "\n".join(wrong)


def test_a_write_through_a_link_inside_the_worktree_is_refused_even_where_it_points_inside(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A link the session made can point elsewhere by the time the tool writes: the real path is
    # the one a file tool names.
    s = installed("role-hooks-only", outside_tmp, monkeypatch)
    _write(s.worktree / "modules" / "control" / "plant.py", "a\n")
    (s.worktree / "inner").symlink_to(s.worktree / "modules" / "control")
    (s.worktree / "inner-file").symlink_to(s.worktree / "modules" / "control" / "plant.py")
    for path in (
        str(s.worktree / "inner" / "plant.py"),
        str(s.worktree / "inner" / "new.py"),
        str(s.worktree / "inner-file"),
        str(s.worktree / "inner" / ".." / "new.py"),
    ):
        for tool in WRITERS:
            code, said, _ = s.hooks.write(tool, path)
            assert code != 0 and OUTSIDE in said, (tool, path, said)
    code, said, _ = s.hooks.write("Write", str(s.worktree / "modules" / "control" / "plant.py"))
    assert code == 0, said


def test_the_refusal_says_where_a_session_writes_and_names_no_path(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    s = installed("role-in-the-layer", outside_tmp, monkeypatch)
    target = str(s.lay.home / ".zshenv")
    code, said, logged = s.hooks.write("Write", target)
    assert code != 0
    assert said == paths.OUTSIDE_THE_WORKTREE.format(tool="Write")
    assert "in its own worktree" in said
    # It names the one folder a throwaway helper goes in, and no other path.
    scratch = f"{getattr(left_out, 'SCRATCH_DIR', '.physgate/scratch')}/"
    assert f"A throwaway helper script or note goes in the worktree's {scratch} folder" in said
    assert "never part of an attempt" in said
    assert "/" not in said.replace(scratch, "")
    assert logged, "the refusal left no line in the hook log"
    # The log keeps the call's own input, as for every refusal; its reason names no path.
    for line in logged:
        assert json.loads(line)["reason"] == said, line


def test_the_generated_command_itself_refuses_a_write_outside_the_worktree(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for kind in ("role-in-the-layer", "raw-outside-a-round"):
        s = installed(kind, outside_tmp / kind, monkeypatch)
        refused = s.hooks.call_as_a_process(
            "PreToolUse",
            tool_name="Write",
            tool_input=tool_input("Write", str(s.lay.home / ".zshenv")),
        )
        allowed = s.hooks.call_as_a_process(
            "PreToolUse",
            tool_name="Write",
            tool_input=tool_input("Write", str(s.worktree / "x.py")),
        )
        assert refused[0] != 0 and OUTSIDE in refused[1], (kind, refused)
        assert allowed[0] == 0, (kind, allowed)


def test_a_reviewer_has_no_writing_tool(outside_tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    s = installed("reviewer", outside_tmp, monkeypatch)
    assert s.hooks.config.profile == "reviewer"
    assert not set(s.hooks.config.tools_allowed) & {"Write", "Edit", "NotebookEdit", "MultiEdit"}
    for tool in WRITERS:
        code, said, _ = s.hooks.write(tool, str(s.worktree / "answer.md"))
        assert code != 0 and f"The {tool} tool is not available to a reviewer session" in said


def test_a_shell_command_s_word_outside_the_worktree_is_not_judged_by_this_rule(
    tmp_path: Path,
) -> None:
    # The OS layer judges where a command writes, and a session's commands write their own
    # temporary directory: the worktree rule is the file tools' alone.
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    config = build_config(
        InstallRequest(
            profile="role",
            role="control",
            worktree=str(worktree),
            own_branch=None,
            store_root=None,
            state_dir=str(tmp_path / "o" / "state"),
            target_dir=str(tmp_path / "o" / "session"),
            claude_config_dir=str(tmp_path / "o" / "cfg"),
            user_home=str(tmp_path / "o" / "home"),
            token_ceiling=1000,
            # pytest's directory lies in a shared temporary one, which has rows of its own.
            shared_temps=(),
        ),
        current_installation(),
    )
    elsewhere = str(tmp_path / "elsewhere" / "build.log")
    assert paths.protection(elsewhere, str(worktree), config, writing=True, shell=True) is None
    assert paths.protection(elsewhere, str(worktree), config, writing=True) is None


def test_a_link_beyond_a_missing_part_and_a_dot_dot_is_still_seen(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The walk of the spelling as written stops at the first part that does not exist: the
    # normalised spelling is walked too, so ``missing/../link/x`` meets ``link`` as a link, here
    # in a run with no root withheld whole around the worktree (whose exception is asked apart).
    s = installed("role-hooks-only", outside_tmp, monkeypatch)
    _write(s.worktree / "modules" / "control" / "plant.py", "a\n")
    (s.worktree / "inner").symlink_to(s.worktree / "modules" / "control")
    for path in (
        str(s.worktree / "missing" / ".." / "inner" / "plant.py"),
        str(s.worktree / "missing" / ".." / "inner" / "new.py"),
    ):
        for tool in WRITERS:
            code, said, _ = s.hooks.write(tool, path)
            assert code != 0 and OUTSIDE in said, (tool, path, said)


@pytest.mark.parametrize("kind", ["role-hooks-only", "raw-outside-a-round"])
def test_a_link_out_beyond_a_missing_part_is_refused_by_the_walk_alone(
    kind: str, outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ``worktree/missing/../<link to a directory outside>/new``: the resolved spelling lies outside
    # as well, so with the walk's normalised spelling taken away the resolved test refuses it, and
    # with the resolved test taken away the walk does.
    s = installed(kind, outside_tmp, monkeypatch)
    (s.worktree / "out").symlink_to(s.lay.home / "notes")
    path = str(s.worktree / "missing" / ".." / "out" / "new.txt")
    for tool in WRITERS:
        code, said, _ = s.hooks.write(tool, path)
        assert code != 0 and OUTSIDE in said, (tool, said)
    assert not (s.lay.home / "notes" / "new.txt").exists()
    from physgate.hooks.paths import _no_link_beneath

    assert not _no_link_beneath(str(s.worktree), os.path.normpath(path))


@pytest.mark.parametrize("kind", ["role-hooks-only", "raw-outside-a-round"])
def test_the_worktree_spelt_through_a_linked_parent_is_not_its_own_spelling(
    kind: str, outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A spelling that resolves into the worktree but is not the worktree's own: an allowance is
    # held to the worktree as it is spelt, not to whatever reaches it.
    s = installed(kind, outside_tmp, monkeypatch)
    alias = s.lay.home / "alias"
    alias.symlink_to(s.worktree.parent)
    path = str(alias / s.worktree.name / "new.txt")
    assert os.path.realpath(path).startswith(os.path.realpath(s.worktree))
    for tool in WRITERS:
        code, said, _ = s.hooks.write(tool, path)
        assert code != 0 and OUTSIDE in said, (tool, said)


def test_a_part_that_cannot_be_looked_at_is_taken_as_a_link(
    outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A name past the system's 255 bytes cannot be looked at (the system answers with an error
    # that is not "no such file"): the write is refused, never taken as a part not there yet.
    s = installed("role-hooks-only", outside_tmp, monkeypatch)
    path = str(s.worktree / ("n" * 300) / "x.txt")
    for tool in WRITERS:
        code, said, _ = s.hooks.write(tool, path)
        assert code != 0 and OUTSIDE in said, (tool, said)


@pytest.mark.parametrize(
    ("where", "target"),
    [("modules", "../../x.txt"), ("home-notes", "new.txt"), ("home-notes", "existing.txt")],
)
def test_a_relative_target_is_read_from_the_call_s_working_directory(
    where: str, target: str, outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Where the call's working directory is not the worktree, a relative target lands there: it
    # is refused where that lies outside, never read as if it were the worktree's own.
    s = installed("role-hooks-only", outside_tmp, monkeypatch)
    cwd = s.worktree / "modules" if where == "modules" else s.lay.home / "notes"
    cwd.mkdir(parents=True, exist_ok=True)
    argv = shlex.split(s.hooks.commands["PreToolUse"])[7:]
    for tool in WRITERS:
        stdin = json.dumps(
            {
                "session_id": SID,
                "cwd": str(cwd),
                "hook_event_name": "PreToolUse",
                "tool_name": tool,
                "tool_input": tool_input(tool, target),
            }
        )
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = runtime.main(argv, stdin, REGISTRY)
        assert code != 0 and OUTSIDE in err.getvalue(), (tool, err.getvalue())


def test_the_refusal_says_what_holds_of_the_scratch_folder_and_no_more() -> None:
    # In the words the role prompt uses: the folder's files are recorded, a record naming code in
    # it is refused; nothing says that what code there computes is never a record.
    said = paths.OUTSIDE_THE_WORKTREE.format(tool="Write")
    assert "each file recorded by name and digest for the review" in said
    assert "a record that names code in it is refused" in said
    assert "accepted as a record" not in said


@pytest.mark.parametrize("kind", ["role-in-the-layer", "role-hooks-only", "raw-trial"])
def test_a_file_tool_read_of_the_harness_s_own_temporary_place_is_refused(
    kind: str, outside_tmp: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The Read tool runs outside the OS layer: this rule is all that keeps a file tool from the
    # harness's stores (a review packet's store, a change check's), on every layer.
    from physgate.hooks.reasons import HARNESS_TEMPS_REASON
    from physgate.oslayer.harness_temp import harness_temps_root

    s = installed(kind, outside_tmp, monkeypatch)
    store = os.path.join(harness_temps_root(), "0123456789", "physgate-review-store-x", "config")
    code, said, _ = s.hooks.call("PreToolUse", tool_name="Read", tool_input={"file_path": store})
    assert code != 0 and HARNESS_TEMPS_REASON in said, said
