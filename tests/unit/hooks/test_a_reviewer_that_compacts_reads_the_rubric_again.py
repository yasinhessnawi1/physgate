"""After a compaction a reviewer is told where its material is, and reads the rubric again.

A compaction summarises what the reviewer read; the rubric's text is what a summary must not
stand in for (ARCH-020). For a reviewer whose run allows compaction, the configuration names
the files to read again after each compaction (the rubric) and the note it is told:

- the session-start hook, started after a compaction (``source: "compact"``), records the
  compaction and returns the note **in place of** the required-reading announcement, which
  would otherwise send the reviewer through its whole reading again;
- every read is recorded with the number of compactions before it;
- once there is a compaction, every tool but Read is refused, with the required-reading
  refusal's own words, until each file to read again has been read in full since the last one.
  A file read in full before a compaction stays read.

Without those fields, which is every role session and every reviewer whose run keeps
compaction off, the hook behaves exactly as before, and the configuration's bytes are those it
always had. The event's ``source`` is read by the schema and the lean validator alike.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from hook_helpers import SESSION, event, write_config

from physgate.hooks import lean, reading
from physgate.hooks.config import HookInput, SessionConfig

NOTE = "Your conversation was compacted: a stand-in for the note."


def _announcement(paths: list[str]) -> str:
    """What the session-start hook has always said, byte for byte."""
    return (
        "Before any other tool, read each of these files in full with the Read tool. "
        "Every other tool is refused until they have been read:\n"
        + "\n".join(f"- {p}" for p in paths)
    )


def _config(tmp_path: Path, **fields: Any) -> tuple[Path, SessionConfig]:  # noqa: ANN401
    try:
        path, _, config = write_config(tmp_path, **fields)
    except ValueError as exc:
        msg = f"the configuration does not take these fields: {exc}"
        raise AssertionError(msg) from exc
    return path, config


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    read = tmp_path / "read"
    read.mkdir()
    out = {"transcript": read / "transcript-01-of-01.md", "rubric": read / "rubric.md"}
    out["transcript"].write_text("one\ntwo\nthree\n")
    out["rubric"].write_text("item a\nitem b\n")
    return out


def _reviewer(tmp_path: Path, files: dict[str, Path], **fields: Any) -> tuple[Path, SessionConfig]:  # noqa: ANN401
    return _config(
        tmp_path,
        profile="reviewer",
        role=None,
        required_reading=sorted(str(p) for p in files.values()),
        **fields,
    )


def _compacting(tmp_path: Path, files: dict[str, Path]) -> tuple[Path, SessionConfig]:
    return _reviewer(
        tmp_path, files, after_compaction=[str(files["rubric"])], compaction_note=NOTE
    )


def _start(source: str | None) -> HookInput:
    fields = {} if source is None else {"source": source}
    return HookInput.model_validate(event("SessionStart", **fields))


def _read(config: SessionConfig, path: Path) -> None:
    lines = len(path.read_text().splitlines())
    hook_input = HookInput.model_validate(
        event(
            "PostToolUse",
            tool_name="Read",
            tool_input={"file_path": str(path)},
            tool_response={
                "type": "text",
                "file": {
                    "filePath": str(path),
                    "content": "...",
                    "numLines": lines + 1,
                    "startLine": 1,
                    "totalLines": lines + 1,
                },
            },
        )
    )
    assert reading.post_tool_use(hook_input, config).allow


def _verdict(config: SessionConfig) -> Any:  # noqa: ANN401 - the hook's decision
    return reading.pre_tool_use(
        HookInput.model_validate(event(tool_name="StructuredOutput", tool_input={})), config
    )


def _compactions(config: SessionConfig) -> int:
    count = getattr(reading, "compactions", None)
    assert count is not None, "the hook layer keeps no count of the compactions it was told of"
    return int(count(config, SESSION))


# --- the event and the configuration -----------------------------------------------------------


def test_the_event_s_source_is_read_by_the_schema_and_the_lean_validator() -> None:
    raw = event("SessionStart", source="compact")
    assert getattr(HookInput.model_validate(raw), "source", None) == "compact"
    assert getattr(lean.parse_input(json.dumps(raw)), "source", None) == "compact"
    assert getattr(HookInput.model_validate(event("SessionStart")), "source", "absent") is None


def test_both_validators_read_the_compaction_fields_and_their_absence(
    tmp_path: Path, files: dict[str, Path]
) -> None:
    path, config = _compacting(tmp_path, files)
    parsed = lean.parse_config(path.read_bytes())
    assert tuple(getattr(parsed, "after_compaction", ())) == (str(files["rubric"]),)
    assert getattr(parsed, "compaction_note", None) == NOTE
    plain_path, plain = _reviewer(tmp_path / "plain", files)
    plain_parsed = lean.parse_config(plain_path.read_bytes())
    assert tuple(getattr(plain_parsed, "after_compaction", ("absent",))) == ()
    assert getattr(plain_parsed, "compaction_note", "absent") is None
    assert tuple(getattr(plain, "after_compaction", ("absent",))) == ()


def test_only_a_reviewer_reads_again_and_only_what_it_must_read(
    tmp_path: Path, files: dict[str, Path]
) -> None:
    _compacting(tmp_path / "ok", files)
    for name, fields in (
        ("role", {"required_reading": [str(files["rubric"])]}),
        ("unlisted", {"profile": "reviewer", "role": None, "required_reading": []}),
        (
            "note-alone",
            {
                "profile": "reviewer",
                "role": None,
                "required_reading": [str(files["rubric"])],
                "after_compaction": [],
            },
        ),
    ):
        compaction: dict[str, Any] = {"after_compaction": [str(files["rubric"])]}
        if name == "note-alone":
            compaction = {"after_compaction": []}
        with pytest.raises(ValueError, match="compaction"):
            write_config(tmp_path / name, **{**fields, **compaction, "compaction_note": NOTE})


def test_a_configuration_without_them_is_written_with_the_bytes_it_always_had(
    tmp_path: Path, files: dict[str, Path]
) -> None:
    from physgate.hooks import settings

    written = getattr(settings, "config_bytes", None)
    assert written is not None, "the installer has no one writer of the configuration's bytes"
    _, plain = _reviewer(tmp_path, files)
    data = json.loads(written(plain))
    assert "after_compaction" not in data and "compaction_note" not in data
    _, compacting = _compacting(tmp_path / "c", files)
    data = json.loads(written(compacting))
    assert data["after_compaction"] == [str(files["rubric"])]
    assert data["compaction_note"] == NOTE
    assert SessionConfig.model_validate_json(written(compacting)) == compacting


# --- the session's start ----------------------------------------------------------------------


def test_after_a_compaction_the_note_replaces_the_announcement_and_is_recorded(
    tmp_path: Path, files: dict[str, Path]
) -> None:
    _, config = _compacting(tmp_path, files)
    decision = reading.session_start(_start("compact"), config)
    assert decision.allow
    assert decision.context == NOTE
    assert _compactions(config) == 1
    reading.session_start(_start("compact"), config)
    assert _compactions(config) == 2


@pytest.mark.parametrize("source", [None, "startup", "resume", "clear"])
def test_any_other_start_is_announced_as_before_and_records_nothing(
    tmp_path: Path, files: dict[str, Path], source: str | None
) -> None:
    _, config = _compacting(tmp_path, files)
    decision = reading.session_start(_start(source), config)
    assert decision.context == _announcement(list(config.required_reading))
    assert _compactions(config) == 0


def test_without_the_fields_a_compaction_s_start_is_announced_as_before(
    tmp_path: Path, files: dict[str, Path]
) -> None:
    _, config = _reviewer(tmp_path, files)
    _compactions(config)
    decision = reading.session_start(_start("compact"), config)
    assert decision.context == _announcement(list(config.required_reading))
    assert _compactions(config) == 0


# --- the verdict after a compaction -----------------------------------------------------------


def test_after_a_compaction_the_verdict_waits_for_the_rubric_read_since(
    tmp_path: Path, files: dict[str, Path]
) -> None:
    _, config = _compacting(tmp_path, files)
    _read(config, files["transcript"])
    _read(config, files["rubric"])
    assert _verdict(config).allow
    reading.session_start(_start("compact"), config)
    _compactions(config)
    refused = _verdict(config)
    assert not refused.allow
    assert refused.reason.startswith("Required reading is not complete.")
    # The rubric read before the compaction does not count; the transcript read before it does.
    assert str(files["rubric"]) in refused.reason
    assert str(files["transcript"]) not in refused.reason
    _read(config, files["rubric"])
    assert _verdict(config).allow
    # Each compaction asks for it again.
    reading.session_start(_start("compact"), config)
    assert not _verdict(config).allow
    _read(config, files["rubric"])
    assert _verdict(config).allow


def test_the_harness_s_own_check_after_the_session_holds_the_same_rule(
    tmp_path: Path, files: dict[str, Path]
) -> None:
    from physgate.orchestrator import dispatch

    path, config = _compacting(tmp_path, files)
    seen = getattr(dispatch, "compactions_seen", None)
    assert seen is not None, "the adapter cannot ask the hook layer how many compactions it saw"
    _read(config, files["transcript"])
    _read(config, files["rubric"])
    assert dispatch.read_in_full(path, SESSION)
    assert seen(path, SESSION) == 0
    reading.session_start(_start("compact"), config)
    assert seen(path, SESSION) == 1
    assert not dispatch.read_in_full(path, SESSION)
    _read(config, files["rubric"])
    assert dispatch.read_in_full(path, SESSION)


def test_without_the_fields_a_compaction_changes_nothing_of_the_check(
    tmp_path: Path, files: dict[str, Path]
) -> None:
    _, config = _reviewer(tmp_path, files)
    _read(config, files["transcript"])
    _read(config, files["rubric"])
    reading.session_start(_start("compact"), config)
    assert _verdict(config).allow
    assert _compactions(config) == 0


def test_the_lean_validator_refuses_what_the_schema_refuses(
    tmp_path: Path, files: dict[str, Path]
) -> None:
    from hook_helpers import config_dict

    rubric, transcript = str(files["rubric"]), str(files["transcript"])
    reviewer: dict[str, Any] = {"profile": "reviewer", "role": None}
    cases = {
        "role": {"required_reading": [rubric], "after_compaction": [rubric]},
        "unlisted": {**reviewer, "required_reading": [transcript], "after_compaction": [rubric]},
        "note-alone": {**reviewer, "required_reading": [rubric], "after_compaction": []},
    }
    for name, fields in cases.items():
        data = json.dumps(config_dict(tmp_path / name, **fields, compaction_note=NOTE)).encode()
        with pytest.raises(lean.LeanValidationError, match="compaction"):
            lean.parse_config(data)
        with pytest.raises(ValueError, match="compaction"):
            SessionConfig.model_validate_json(data)
    without_note = {
        **reviewer,
        "required_reading": [rubric],
        "after_compaction": [rubric],
    }
    data = json.dumps(config_dict(tmp_path / "no-note", **without_note)).encode()
    with pytest.raises(lean.LeanValidationError, match="compaction"):
        lean.parse_config(data)
    with pytest.raises(ValueError, match="compaction"):
        SessionConfig.model_validate_json(data)
