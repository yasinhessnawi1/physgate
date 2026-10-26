"""Tests of the authoring (§2.2, §2.5): its inputs, sandbox, audit, checks, assembly and routes.

The fixed inputs, the sandbox, the audit, the checks, the assembly, and every route, resume,
replacement, restart and cap of the sheet.

Run explicitly, from the repository root: ``uv run pytest -q experiments/R-PG-03``.

The sheet is driven with its sessions and checks stood in for (no binary runs, no model is
called); the sandbox's own proof runs the pinned binary's macOS build on the scripted endpoint
with a dummy credential, and is skipped where that build is not on the machine.
"""

from __future__ import annotations

import difflib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import authoring as au  # noqa: E402
import common  # noqa: E402
import fixture as fx  # noqa: E402

# ---- the fixed inputs ---------------------------------------------------------------------------


def criteria() -> list[str]:
    return (HERE / "CRITERIA.md").read_text().split("\n")


def fenced_after(marker: str) -> str:
    lines = criteria()
    i = next(k for k, ln in enumerate(lines) if ln.startswith(marker))
    j = next(k for k in range(i, len(lines)) if lines[k] == "```markdown")
    e = next(k for k in range(j + 1, len(lines)) if lines[k] == "```")
    return "\n".join(lines[j + 1 : e]) + "\n"


def quoted_after(marker: str) -> str:
    lines = criteria()
    i = next(k for k, ln in enumerate(lines) if ln.startswith(marker))
    j = next(k for k in range(i + 1, len(lines)) if lines[k].startswith("> "))
    out = []
    while lines[j].startswith(">"):
        out.append(lines[j][2:].strip())
        j += 1
    return " ".join(out) + "\n"


def test_rules_md_is_appendix_a_and_brief_c_is_appendix_b_byte_for_byte() -> None:
    assert au.fixed("rules.md").decode() == fenced_after("## Appendix A.")
    assert au.fixed("brief_C.md").decode() == fenced_after("**`brief_C.md`:**")


@pytest.mark.parametrize(
    ("name", "marker"),
    [
        ("continue_third.txt", "**The third continuation, for X1 only:**"),
        ("launch_X3.txt", "**The launch message for X3**"),
        ("resume.txt", "**The resume message**"),
    ],
)
def test_each_message_is_appendix_b_s_words(name: str, marker: str) -> None:
    assert au.fixed(name).decode() == quoted_after(marker)


@pytest.mark.parametrize("brief", ["brief_A.md", "brief_B.md"])
def test_the_briefs_are_r_pg_02_s_with_lines_added_and_nothing_else_changed(brief: str) -> None:
    old = (au.R_PG_02 / "briefs" / brief).read_text().splitlines()
    new = au.fixed(brief).decode().splitlines()
    ops = difflib.SequenceMatcher(a=old, b=new, autojunk=False).get_opcodes()
    assert all(tag in ("equal", "insert") for tag, *_ in ops)
    added = " ".join(" ".join(new[j1:j2]) for tag, _, _, j1, j2 in ops if tag == "insert")
    words = " ".join(added.split())
    line = (
        "`rules.md`: rules this set adds to the format. Where they say more than "
        "`format.md`, they hold."
    )
    assert line in words
    if brief == "brief_B.md":
        sentence = (
            "Your error breaks the revision in exactly one place; every rule of `rules.md` "
            "still holds everywhere else."
        )
        assert sentence in words


def test_every_input_is_held_to_its_frozen_digest() -> None:
    found = au.inputs_record()
    assert found["continue_A.txt"].startswith("4cef18d7") and found["continue_B.txt"].startswith(
        "660015c3"
    )
    assert found["parts_sheet.md"] == common.EDITED_TABLE_SHA256
    assert found["guard.py"] == au.GUARD_SHA256


# ---- the sandbox ---------------------------------------------------------------------------------


def test_a_session_s_directory_is_new_its_inputs_listed_and_its_guard_r_pg_02_s(
    tmp_path: Path,
) -> None:
    scratch, config = au.prepare(tmp_path / "S-1", {"brief.md": b"b\n", "clean/a01.json": b"{}"})
    assert (scratch / "clean" / "a01.json").read_bytes() == b"{}"
    assert json.loads((tmp_path / "S-1" / "inputs.json").read_text()) == {
        "brief.md": common.sha256_bytes(b"b\n"),
        "clean/a01.json": common.sha256_bytes(b"{}"),
    }
    assert (config / "guard.py").read_bytes() == au.GUARD.read_bytes()
    hook = json.loads((config / "settings.json").read_text())["hooks"]["PreToolUse"][0]["hooks"][0][
        "command"
    ]
    assert hook.endswith(f"{config / 'guard.py'} {scratch}")
    with pytest.raises(au.RefusedError, match="always new"):
        au.prepare(tmp_path / "S-1", {})


def test_a_memory_file_above_a_session_s_directory_is_refused(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("x")
    with pytest.raises(au.RefusedError, match="memory file"):
        au.prepare(tmp_path / "a" / "S-1", {})


def test_the_session_command_is_r_pg_02_s_sandbox() -> None:
    argv = au.argv(
        "/bin/claude", Path("/c"), "Read brief.md in this directory, then do what it says.\n", None
    )
    assert argv[argv.index("--tools") + 1] == "Read,Write,Edit"
    assert argv[argv.index("--setting-sources") + 1] == "" and "--strict-mcp-config" in argv
    assert argv[argv.index("--model") + 1] == common.AUTHOR_MODEL
    assert "--resume" not in argv and au.argv("/b", Path("/c"), "x", "sid")[-2:] == [
        "--resume",
        "sid",
    ]
    env = au.env(Path("/c"))
    assert env["HOME"] == "/c/home" and "ANTHROPIC_BASE_URL" not in env


# ---- the audit -----------------------------------------------------------------------------------


def turn_files(
    root: Path,
    events: list[dict[str, Any]],
    message: str = "launch.txt",
    scan: dict[str, int] | None = None,
) -> dict[str, Any]:
    (root / "turns").mkdir(parents=True, exist_ok=True)
    (root / "scratch").mkdir(exist_ok=True)
    (root / "turns" / "01-launch.stream.jsonl").write_text(fx.stream(*events))
    return {
        "turn": 1,
        "label": "launch",
        "message": message,
        "secret_scan": scan or {"token_value": 0, "sk_ant_prefix": 0, "oat_prefix": 0},
    }


def call(tid: str, name: str, path: str | None = None) -> dict[str, Any]:
    tool_input = {"file_path": path} if path else {"command": "x"}
    return {
        "type": "assistant",
        "message": {
            "model": common.AUTHOR_MODEL,
            "content": [{"type": "tool_use", "id": tid, "name": name, "input": tool_input}],
        },
    }


@pytest.mark.parametrize(
    ("events", "message", "scan", "failure"),
    [
        (
            [call("t1", "Bash"), fx.tool_result("t1", "No such tool available: Bash", True)],
            "launch.txt",
            None,
            None,
        ),
        ([call("t1", "Bash"), fx.tool_result("t1", "ok")], "launch.txt", None, "a tool other than"),
        (
            [
                call("t1", "Read", "/etc/hosts"),
                fx.tool_result(
                    "t1", "/etc/hosts is outside this session's working directory", True
                ),
            ],
            "launch.txt",
            None,
            None,
        ),
        (
            [call("t1", "Read", "/etc/hosts"), fx.tool_result("t1", "127.0.0.1 localhost")],
            "launch.txt",
            None,
            "outside",
        ),
        (
            [{"type": "assistant", "message": {"model": "another-model", "content": []}}],
            "launch.txt",
            None,
            "a model",
        ),
        ([], "/tmp/another-message.txt", None, "a message from anyone"),
        ([], "launch.txt", {"token_value": 0, "sk_ant_prefix": 1, "oat_prefix": 0}, "a secret"),
    ],
    ids=[
        "a-tool-tried-and-unavailable",
        "a-tool-used",
        "a-refusal",
        "a-read-outside-that-succeeded",
        "another-model",
        "a-message-not-fixed",
        "a-secret",
    ],
)
def test_the_audit_of_a_turn(
    tmp_path: Path,
    events: list[dict[str, Any]],
    message: str,
    scan: dict[str, int] | None,
    failure: str | None,
) -> None:
    outcome = turn_files(tmp_path, events, message, scan)
    found = au.audit(tmp_path, outcome, {}, {"launch.txt"})
    if failure is None:
        assert found["failed"] == []
    else:
        assert any(failure in f for f in found["failed"]), found["failed"]


def test_a_passed_copy_changed_at_the_turn_s_end_is_an_audit_failure(tmp_path: Path) -> None:
    outcome = turn_files(tmp_path, [])
    (tmp_path / "scratch" / "base.json").write_text("{}")
    record = {"base.json": common.sha256_bytes(b"{} ")}
    assert any(
        "passed copy" in f for f in au.audit(tmp_path, outcome, record, {"launch.txt"})["failed"]
    )
    record = {"base.json": common.sha256_bytes(b"{}")}
    assert au.audit(tmp_path, outcome, record, {"launch.txt"})["failed"] == []


# ---- the checks and the assembly -----------------------------------------------------------------


def pilot(tmp: Path) -> tuple[Path, bytes, dict[str, Any]]:
    """A writer's scratch made of the test design: base.json and its revisions as clean/aNN.json."""
    corpus = fx.write_set(tmp / "corpus")
    scratch = tmp / "scratch"
    (scratch / "clean").mkdir(parents=True)
    (scratch / "base.json").write_text((corpus / "base.json").read_text())
    arts = {}
    for k, path in enumerate(sorted((corpus / "artefacts").glob("*.json")), 1):
        a = json.loads(path.read_text())
        rid = f"a{k:02d}"
        arts[rid] = a
        rev = {"id": rid, "assigned_role": a["assigned_role"], "summary": "s", "clean": a["clean"]}
        (scratch / "clean" / f"{rid}.json").write_text(json.dumps(rev))
    return scratch, (corpus / "sources.json").read_bytes(), arts


def test_a_clean_revision_that_does_not_load_or_carries_a_telltale_word_is_a_fact(
    tmp_path: Path,
) -> None:
    scratch, sheet, _ = pilot(tmp_path)
    good = au.check_clean(scratch, ["a01", "a02", "a03", "a04"], sheet, tmp_path / "w1")
    assert {f["check"] for f in good} <= {"the source check"}  # the test design's sheet is its own
    (scratch / "clean" / "a02.json").write_text(
        json.dumps({"id": "a02", "clean": {"nodes": [{"id": "x"}]}})
    )
    rev = json.loads((scratch / "clean" / "a03.json").read_text())
    node = rev["clean"]["nodes"][0]
    node["quantities"]["the_planted_value"] = next(iter(node["quantities"].values()))
    (scratch / "clean" / "a03.json").write_text(json.dumps(rev))
    facts = au.check_clean(scratch, ["a01", "a02", "a03"], sheet, tmp_path / "w2")
    assert {f["place"] for f in facts if f["check"] == "the loader"} == {
        "clean/a02.json",
        "clean/a03.json",
    }


def test_the_injection_s_assembly_rule_is_r_pg_02_s() -> None:
    clean = [{"id": "a.x", "v": 1}, {"id": "b.y", "v": 2}]
    assert au.injected_nodes("a01", clean, {"replace": [{"id": "a.x", "v": 9}], "drop": []}) == [
        {"id": "a.x", "v": 9},
        clean[1],
    ]
    assert au.injected_nodes("a01", clean, {"replace": [], "drop": ["b.y"]}) == [clean[0]]
    bad: dict[str, Any]
    for bad in (
        {"replace": [], "drop": []},
        {"replace": [{"id": "c.z"}], "drop": []},
        {"replace": [{"id": "a.x"}], "drop": ["a.x"]},
        {"replace": [{"id": "a.x"}, {"id": "a.x"}]},
    ):
        with pytest.raises(au.RefusedError):
            au.injected_nodes("a01", clean, bad)


def test_a_batch_is_assembled_from_the_passed_copies_alone_and_held_to_completeness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch, sheet, arts = pilot(tmp_path)
    errors = tmp_path / "errors"
    (errors / "injections").mkdir(parents=True)
    passed, injections = {"base.json": common.sha256_file(scratch / "base.json")}, {}
    for rid, a in arts.items():
        passed[f"clean/{rid}.json"] = common.sha256_file(scratch / "clean" / f"{rid}.json")
        replace = [n for n in a["injected"]["nodes"] if n not in a["clean"]["nodes"]]
        dropped = [
            n["id"]
            for n in a["clean"]["nodes"]
            if n["id"] not in {m["id"] for m in a["injected"]["nodes"]}
        ]
        inj = {
            "id": rid,
            "error_class": a["error_class"],
            "expected_check": a["expected_check"],
            "description": a["description"],
            "edge": a["edge"],
            "replace": replace,
            "drop": dropped,
        }
        (errors / "injections" / f"{rid}.json").write_text(json.dumps(inj))
        injections[f"injections/{rid}.json"] = common.sha256_file(
            errors / "injections" / f"{rid}.json"
        )
    monkeypatch.setattr(au, "ids_of", lambda batch: sorted(arts))
    out = au.assemble(
        "X",
        "1",
        scratch,
        errors,
        passed,
        injections,
        tmp_path / "fresh-v2-x1",
        sheet,
        fx.edited_table(),
    )
    problems = au.check_injections(out, "1", set(), tmp_path / "w")
    assert problems == ["the loader or completeness: CorpusError"]  # four items, not five per class
    (scratch / "clean" / "a01.json").write_text("{}")
    with pytest.raises(au.RefusedError, match="recorded digest"):
        au.assemble(
            "X",
            "1",
            scratch,
            errors,
            passed,
            injections,
            tmp_path / "again",
            sheet,
            fx.edited_table(),
        )


# ---- the sheet's routes --------------------------------------------------------------------------


class Sheet:
    """The sheet with its sessions and checks stood in for; every turn and check scripted."""

    def __init__(self, tmp: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.tmp = tmp
        self.ended: list[str] = []  # what each next turn's stream shows, in order; "completed" else
        self.failing: list[list[str]] = []  # each next turn's audit failures
        self.checks: list[int] = []  # each next clean check's count of facts
        self.errors: list[list[str]] = []  # each next injection check's problems
        self.turns: list[tuple[str, str, str]] = []
        monkeypatch.setenv("RP3_RUNS", str(tmp / "runs"))
        monkeypatch.setenv("RP3_NO_WAIT", "1")
        monkeypatch.setattr(au, "session_files", lambda kind, p, pair: {"brief.md": b"b"})
        monkeypatch.setattr(au, "sheet_bytes", lambda: (b"table", b"sheet"))
        monkeypatch.setattr(au, "turn", self.turn)
        monkeypatch.setattr(au, "audit", self.audit)
        monkeypatch.setattr(au, "check_clean", self.check_clean)
        monkeypatch.setattr(
            au,
            "check_injections",
            lambda out, batch, earlier, work: self.errors.pop(0) if self.errors else [],
        )
        monkeypatch.setattr(au, "assemble", self.assemble)
        monkeypatch.setattr(au, "edges_of", lambda out: set())

    def turn(self, root: Path, label: str, message: str, resume: str | None) -> dict[str, Any]:
        self.turns.append((root.name, label, Path(message).name))
        (root / "scratch" / "injections").mkdir(parents=True, exist_ok=True)
        for k in range(1, 41):
            (root / "scratch" / "injections" / f"a{k:02d}.json").write_text("{}")
        for k in range(1, 11):
            (root / "scratch" / "injections" / f"s{k:02d}.json").write_text("{}")
        ended = self.ended.pop(0) if self.ended else "completed"
        return {
            "turn": len(self.turns),
            "label": label,
            "ended": ended,
            "session_id": "sid",
            "tokens": 1,
            "message": Path(message).name,
        }

    def audit(
        self, root: Path, outcome: dict[str, Any], passed: dict[str, str], names: set[str]
    ) -> dict[str, Any]:
        failed = self.failing.pop(0) if self.failing else []
        return {"tool_calls": {}, "guard_refusals": 0, "models": [], "failed": failed}

    def check_clean(
        self, scratch: Path, ids: list[str], sheet: bytes, work: Path
    ) -> list[dict[str, str]]:
        n = self.checks.pop(0) if self.checks else 0
        return [au.rules_check.fact("rule 3", "clean/a01.json", "n", "q", "m")] * n

    def assemble(
        self,
        pair: str,
        batch: str,
        clean_dir: Path,
        injection_dir: Path,
        passed: dict[str, str],
        injections: dict[str, str],
        out: Path,
        sheet: bytes,
        table: bytes,
    ) -> Path:
        fx.write_set(out)
        return out

    def step(self, state: dict[str, Any]) -> dict[str, Any]:
        return au.next_step(state)

    def until(self, state: dict[str, Any], stop: str, limit: int = 200) -> dict[str, Any]:
        for _ in range(limit):
            got = self.step(state)
            if stop in json.dumps(got):
                return got
        raise AssertionError(f"never reached {stop!r}: {state.get('log', [])[-3:]}")


@pytest.fixture
def sheet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sheet:
    return Sheet(tmp_path, monkeypatch)


def test_the_sheet_runs_pair_x_s_order_and_assembles_its_corpora(sheet: Sheet) -> None:
    state = au.read_state()
    sheet.until(state, "C-check", limit=40) if False else None
    for _ in range(40):
        got = sheet.step(state)
        if got["step"] == "pair done":
            break
    labels = [(s, label, m) for s, label, m in sheet.turns]
    assert labels == [
        ("X1-1", "launch", "launch.txt"),
        ("X1-1", "continue", "continue_A.txt"),
        ("X1-1", "third", "continue_third.txt"),
        ("X2-1", "launch", "launch.txt"),
        ("X2-1", "continue", "continue_B.txt"),
        ("C-1", "launch", "launch.txt"),
    ]
    assert state["pairs"]["X"]["s_status"] == "passed"
    for name in ("fresh-v2-x1", "fresh-v2-x2", "fresh-v2-s"):
        assert (sheet.tmp / "runs" / "sets" / name / "MANIFEST.json").is_file()


def test_the_facts_go_back_at_most_four_rounds_then_the_pair_restarts(sheet: Sheet) -> None:
    state = au.read_state()
    sheet.checks = [1, 1, 1, 1, 1]
    got = sheet.until(state, "restart")
    facts_turns = [t for t in sheet.turns if t[1].startswith("facts-1-")]
    assert len(facts_turns) == 4 and all(m.startswith("facts-1-") for _, _, m in facts_turns)
    assert got["attempt"] == 2 and state["pairs"]["X"]["restarts"] == 1


def test_the_restarts_are_capped_and_the_authoring_stops_for_the_owner(sheet: Sheet) -> None:
    state = au.read_state()
    sheet.failing = [["a tool other than Read, Write and Edit was used"]] * 3
    sheet.until(state, "stopped for the owner")
    assert state["pairs"]["X"]["restarts"] == 2 and "restarts are spent" in state["stopped"]


def test_a_usage_limit_waits_for_the_reset_and_resumes_once_per_turn(sheet: Sheet) -> None:
    state = au.read_state()
    sheet.ended = ["usage_limit"]
    sheet.until(state, "waiting")
    assert sheet.step(state)["step"] == "waiting"
    state["waiting"]["released"] = True
    sheet.step(state)
    assert sheet.turns[-1][1:] == ("resume-launch", "resume.txt")
    assert state["pairs"]["X"]["sessions"]["W"]["usage_resumes"] == 1


def test_a_second_usage_limit_in_one_turn_counts_as_an_audit_failure(sheet: Sheet) -> None:
    state = au.read_state()
    sheet.ended = ["usage_limit", "usage_limit"]
    sheet.until(state, "waiting")
    state["waiting"]["released"] = True
    got = sheet.until(state, "restart")
    assert "usage-limit" in got["why"]


def test_an_infrastructure_cut_climbs_the_ladder_then_waits_for_the_owner(sheet: Sheet) -> None:
    state = au.read_state()
    sheet.ended = ["infrastructure"] * 4
    got = sheet.until(state, "waiting")
    assert "service is back" in got["for"]
    assert [t[1] for t in sheet.turns] == [
        "launch",
        "resume-launch",
        "resume-launch",
        "resume-launch",
    ]
    delays = [
        e["delay_s"] for e in state["log"] if e["event"] == "resume after an infrastructure cut"
    ]
    assert delays == [60.0, 900.0, 2700.0]
    state["waiting"]["released"] = True
    sheet.step(state)
    assert sheet.turns[-1][1] == "resume-launch" and state["pairs"]["X"]["restarts"] == 0


def test_an_error_session_whose_injections_fail_is_replaced_and_its_cap_stops_the_authoring(
    sheet: Sheet,
) -> None:
    state = au.read_state()
    sheet.errors = [["the blindness check on an item"]] * 6  # each check reads both batches
    got = sheet.until(state, "stopped for the owner")
    assert state["pairs"]["X"]["replacements"]["E"] == 2
    assert [t[0] for t in sheet.turns if t[1] == "launch" and t[0].startswith("X2")] == [
        "X2-1",
        "X2-2",
        "X2-3",
    ]
    assert "replacements are spent" in got["why"]


def test_the_s_batch_failing_goes_to_x3_once_and_then_the_class_is_not_run(sheet: Sheet) -> None:
    state = au.read_state()
    sheet.checks = [0, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
    for _ in range(60):
        got = sheet.step(state)
        if got["step"] == "pair done":
            break
    assert ("X3-1", "launch", "launch_X3.txt") in sheet.turns
    assert state["pairs"]["X"]["s_status"] == "cap"
    assert not any(t[0].startswith("C-") for t in sheet.turns)
    assert (sheet.tmp / "runs" / "sets" / "fresh-v2-x1").is_dir()


def test_pair_y_has_no_s_batch(sheet: Sheet) -> None:
    state = au.read_state()
    for _ in range(80):
        got = sheet.step(state)
        if state["pairs"].get("Y", {}).get("status") == "done":
            break
    y = [t for t in sheet.turns if t[0].startswith("Y")]
    assert [t[1] for t in y] == ["launch", "continue", "launch", "continue"]
    assert "third" not in {t[1] for t in y} and got


def test_the_authoring_waits_five_hours_after_r_pg_01b_and_never_beside_a_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RP3_RUNS", str(tmp_path))
    with pytest.raises(au.RefusedError, match="R-PG-01b's lines"):
        au.runs_allowed()
    import ledger

    ledger.append(
        tmp_path / ledger.LEDGER_NAME,
        {
            "kind": "rpg01b-round",
            "label": "r",
            "started_utc": "2026-10-29T08:00:00Z",
            "ended_utc": "2026-10-29T16:00:00Z",
            "tokens_every_try": 1,
        },
    )
    with pytest.raises(au.RefusedError, match="5 hours"):
        au.runs_allowed(now=ledger.seconds("2026-10-29T20:00:00Z"))
    au.runs_allowed(now=ledger.seconds("2026-10-29T21:00:01Z"))
    fx.write_blocks(tmp_path, [{"block": "x1", "attempt": 1, "valid": None}])
    with pytest.raises(au.RefusedError, match="never overlaps"):
        au.runs_allowed(now=ledger.seconds("2026-10-29T21:00:01Z"))


# ---- the sandbox's proof, on the scripted endpoint ----------------------------------------------

MAC = Path.home() / "pinned" / "claude-2.1.301-macos"


@pytest.mark.skipif(
    not MAC.is_file() or sys.platform != "darwin", reason="no pinned macOS build on this machine"
)
def test_the_sandbox_is_proven_on_the_scripted_endpoint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PHYSGATE_CLAUDE_BIN", str(MAC))
    monkeypatch.delenv(fx.TOKEN_NAME, raising=False)
    found = au.prove(tmp_path / "proof")
    g, c = found["guarded"], found["control"]
    assert found["holds"], json.dumps(found, indent=1)
    assert g["audit"]["guard_refusals"] >= 5 and g["audit"]["paths_outside_succeeded"] == 0
    assert c["planted_text_reached_the_model"] > 0


def test_the_command_sheet_names_its_steps_and_keeps_the_token_to_one_child() -> None:
    text = (HERE / "authoring.sh").read_text()
    for step in (
        "inputs)",
        "prove)",
        "status)",
        "limit-reset|service-back|owner-resume)",
        "owner-stop)",
        "next)",
    ):
        assert step in text
    assert 'rp3_exec_with_token setsid uv run --frozen python -I "$HERE/authoring.py" next' in text
    assert 'watch_limit.sh" "$AUTH/watcher.log" authoring' in text
    done = subprocess.run(
        ["bash", str(HERE / "authoring.sh"), "nonsense"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "RP3_RUNS": "/nonexistent"},
    )
    assert done.returncode == 2


def test_the_acceptance_checks_on_an_assembled_corpus(tmp_path: Path) -> None:
    corpus = fx.write_set(tmp_path / "fresh-v2-x1")
    got = au.accept(
        corpus, "1", None, "0" * 64, tmp_path / "w", (2, 3, 6)
    )  # item 4: test_rules_check
    assert got["item 2"] == {"base_failing_records": 0, "twins_with_a_failing_record": 0}
    assert set(got["item 3"]) == {"mismatch", "subtracted", "unresolved"}
    assert got["item 6 R3"]["problems"] == []
    complete = au.accept(corpus, "1", None, "0" * 64, tmp_path / "w2", (1,))
    assert complete["item 1 and 6"]["problems"] and not complete["holds"]  # four items, not twenty


def test_every_fixed_input_is_listed_with_its_sha256() -> None:
    listed: dict[str, str] = {}
    for line in (au.AUTHORING / "INPUTS.sha256").read_text().splitlines():
        digest, name = line.split()
        listed[name] = digest
    assert set(listed) == set(au.FIXED)
    for name, digest in listed.items():
        assert common.sha256_bytes(au.fixed(name)) == digest
