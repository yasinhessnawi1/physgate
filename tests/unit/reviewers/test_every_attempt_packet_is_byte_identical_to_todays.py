# ruff: noqa: E501 - each pinned digest is written whole, on its line
"""An attempt's review is shown exactly what it was shown before the plan's review existed.

The plan's review has a packet of its own and a path of its own through the reviewer, and the
attempt's review shares the session code with it. This holds what the attempt's reviewer is
given, byte for byte, to digests taken on the code before the plan's review was added: every file
under ``read/``, the packet's record, and the prompt and verdict schema its session is spawned
with, for a plain attempt, one a person ordered, and one of integration's subtask with its issued
state. The review is driven through ``ClaudeReviewer.review`` itself, up to its spawn.

What differs between two builds of the same attempt is fixed or left out: the nonces are drawn
from a fixed sequence, the session id is fixed, and the temporary directory and the fixture's
commit ids (which carry the time they were made) are replaced by names before anything is hashed.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from pathlib import Path
from typing import Any

import pytest
from knowledge_fixture import write_fixture
from packet_fixture import ISSUED, SPEC, artefact_of, make_attempt, stream
from rubric_fixture import PLACEHOLDER

import physgate.reviewers.claude as claude
from physgate.orchestrator.credentials import Credential
from physgate.orchestrator.dispatch import Installed
from physgate.orchestrator.protocols import IssuedSpec, IssuedState, PersonOrder
from physgate.orchestrator.run_config import RunBounds
from physgate.reviewers.claude import ClaudeReviewer, ReviewerSetup
from physgate.reviewers.rubric import Rubric, parse_rubric

SESSION = uuid.UUID("00000000-0000-4000-8000-000000000001")
STATE = "# Integration's issued state\n\nEvery pair's contract: none tested yet.\n"
ORDER = PersonOrder(kind="fix_after_block", item_id="run-1-s1", of_attempt=1, instruction="Fix it.")


class _SpawnedError(Exception):
    """The review reached its spawn: everything it is shown has been written."""


def _state() -> IssuedState:
    data = STATE.encode()
    return IssuedState(text=STATE, sha256=hashlib.sha256(data).hexdigest(), length=len(data))


def shown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str) -> dict[str, str]:
    """Every byte the attempt's review is shown in ``form``, by name, normalised and hashed."""
    draws = iter(f"{n:016x}" for n in range(1, 1000))
    monkeypatch.setattr(secrets, "token_hex", lambda size: next(draws))
    monkeypatch.setattr(uuid, "uuid4", lambda: SESSION)
    monkeypatch.setattr(claude, "binary_version", lambda binary: "2.1.301")
    attempt = make_attempt(tmp_path, stream())
    library = tmp_path / "harness"
    write_fixture(library, ("cross", "control"))
    digest = hashlib.sha256(ISSUED.encode()).hexdigest()
    update: dict[str, Any] = {
        "base_commit": attempt.spec_commit,
        "issued_spec": IssuedSpec(commit=attempt.spec_commit, path=SPEC, sha256=digest),
        "repository": str(attempt.worktree),
    }
    if form == "ordered":
        update["ordered_by_person"] = ORDER
    if form == "integration":
        update["integration_state"] = _state()
    artefact = artefact_of(attempt).model_copy(update=update)
    spawned: dict[str, Any] = {}

    def spawn(
        self: object, packet: object, sdir: Path, installed: object, sid: str, **kw: Any
    ) -> Any:  # noqa: ANN401
        spawned.update(kw)
        raise _SpawnedError

    installed = Installed(settings="s", config="c", spawn_args=(), spawn_env={})
    monkeypatch.setattr(ClaudeReviewer, "_install", lambda self, packet, sdir: installed)
    monkeypatch.setattr(ClaudeReviewer, "_spawn", spawn)
    rubric = Rubric(
        role="control",
        text=PLACEHOLDER,
        sha256=hashlib.sha256(PLACEHOLDER.encode()).hexdigest(),
        items=parse_rubric(PLACEHOLDER),
    )
    (tmp_path / "reviews").mkdir()
    setup = ReviewerSetup(
        run_id="run-1",
        models={"control": "claude-sonnet-5"},
        claude_version="2.1.301",
        bounds=RunBounds(
            binary_max_retries=0,
            session_wall_clock_s=60.0,
            session_max_turns=20,
            infra_retry_delays_s=(),
        ),
        effort="high",
        max_output_tokens=64000,
        token_ceiling=100_000,
        review_root=tmp_path / "reviews",
        repo=None,
        install_bin=tmp_path / "install" / "bin" / "x",
        binary="claude",
        base_url=None,
        credential=Credential(mode="api_key", secret="not-a-key"),
        library=library,
    )
    reviewer = ClaudeReviewer(role="control", setup=setup, rubric=rubric)
    with pytest.raises(_SpawnedError):
        reviewer.review(artefact)
    names = {
        str(tmp_path): "<tmp>",
        attempt.attempt_commit: "<attempt>",
        attempt.spec_commit: "<spec>",
    }

    def normal(data: bytes) -> str:
        for value, name in names.items():
            data = data.replace(value.encode(), name.encode())
        return hashlib.sha256(data).hexdigest()

    [review] = (tmp_path / "reviews").iterdir()
    found = {
        p.relative_to(review).as_posix(): normal(p.read_bytes())
        for p in sorted(review.rglob("*"))
        if p.is_file() and p.parts[len(review.parts)] not in ("session", "packet.json")
    }
    # The listing names files by full path, so its digest and size in the record depend on the
    # directory's; the listing itself is held above, normalised.
    record = json.loads((review / "packet.json").read_text())
    for part in record["files_parts"]:
        part.update(sha256="<listing>", bytes="<listing>")
    found["packet.json"] = normal(json.dumps(record, indent=1).encode())
    found["<prompt>"] = normal(spawned["prompt"].encode())
    found["<schema>"] = normal(json.dumps(spawned["schema"], sort_keys=True).encode())
    return found


#: Taken on the code before the plan's review was added (c44088e9), by :func:`shown`.
PINNED: dict[str, dict[str, str]] = {
    "plain": {
        "<prompt>": "035d4c7324b962330d91ad865c6e95181865466bed58c6c4beff7ca0334a296f",
        "<schema>": "d5c61a119d76ef79399c478e3c6c4ebf98d972a6613eafd7dfb21fa046c94f31",
        "packet.json": "eadb6d140913d1fc7e47c381355c0234c0a962436254364ba243ea4dbc21bd86",
        "read/diff-01-of-01.patch": "1a5b850ed048a66a42a97227e04f94d1d12d1acdb5f3b403594dae5b8a5cdf37",
        "read/files-01-of-01.md": "64fa980a589208ab0d57fda3ebaaf090f37a2a92c465de2b55f28ac8c832195e",
        "read/knowledge/control/skill.md": "7f6db5b531beb4a0e58910feec49b55eed1ccf799282dbdd50dceefa7ad32e3f",
        "read/knowledge/control/standards.md": "17e01656cc9329f09553d2258445ebec28881fddf2b2f102b04a6f858dd7908e",
        "read/knowledge/cross/standards.md": "17e01656cc9329f09553d2258445ebec28881fddf2b2f102b04a6f858dd7908e",
        "read/rubric.md": "1aa9a1ae1cf24b1e72b143d3e56c0deb89d49554c138bab503d5149a74c9a63d",
        "read/spec_as_issued.md": "b30036946b9c9dede462b171dca4c49fb82132852b184a8e5162b01cd82f5eea",
        "read/transcript-01-of-01.md": "226b48aebf1d14f511cc47449b15056524bfe704ab730947941a6774b297de4e",
        "read/worktree/.physgate/specs/s1.md": "5b7d08241cbad861cd9616b956478f3144e986b6c4abaef19e6520307d6853fc",
        "read/worktree/m/ctl.py": "ad0577166e7c97ba81e032102d0315c61853df25d1c652414de5f601f7fd379a",
        "read/worktree/m/link": "2fb8bbdff4d80f8e2eb782b4c887783ac8964fe7bf681de0385807998a1ef27b",
    },
    "ordered": {
        "<prompt>": "34d188b845da5ac86165a2c5c0d855529eeaae080e2443ccd3f1c66c64c4cb66",
        "<schema>": "d5c61a119d76ef79399c478e3c6c4ebf98d972a6613eafd7dfb21fa046c94f31",
        "packet.json": "97c01539843b803e0c3c585710a9588a2e3e88d0d91dbf92b6ecede3ce5c0250",
        "read/diff-01-of-01.patch": "1a5b850ed048a66a42a97227e04f94d1d12d1acdb5f3b403594dae5b8a5cdf37",
        "read/files-01-of-01.md": "95a50aea945ebdb9e08e749571586773f079ab069e157735acca088993fab37d",
        "read/knowledge/control/skill.md": "7f6db5b531beb4a0e58910feec49b55eed1ccf799282dbdd50dceefa7ad32e3f",
        "read/knowledge/control/standards.md": "17e01656cc9329f09553d2258445ebec28881fddf2b2f102b04a6f858dd7908e",
        "read/knowledge/cross/standards.md": "17e01656cc9329f09553d2258445ebec28881fddf2b2f102b04a6f858dd7908e",
        "read/person_order.md": "5798cfefa8d7f3fec965823dc0ff569da9a10aea070957eec78c0f85dd78046b",
        "read/rubric.md": "1aa9a1ae1cf24b1e72b143d3e56c0deb89d49554c138bab503d5149a74c9a63d",
        "read/spec_as_issued.md": "b30036946b9c9dede462b171dca4c49fb82132852b184a8e5162b01cd82f5eea",
        "read/transcript-01-of-01.md": "226b48aebf1d14f511cc47449b15056524bfe704ab730947941a6774b297de4e",
        "read/worktree/.physgate/specs/s1.md": "5b7d08241cbad861cd9616b956478f3144e986b6c4abaef19e6520307d6853fc",
        "read/worktree/m/ctl.py": "ad0577166e7c97ba81e032102d0315c61853df25d1c652414de5f601f7fd379a",
        "read/worktree/m/link": "2fb8bbdff4d80f8e2eb782b4c887783ac8964fe7bf681de0385807998a1ef27b",
    },
    "integration": {
        "<prompt>": "7de017ae6cdee257ab7745f19ccd89e139e38952f68c3a57bc31474469b709d9",
        "<schema>": "d5c61a119d76ef79399c478e3c6c4ebf98d972a6613eafd7dfb21fa046c94f31",
        "packet.json": "778f0d03fa6e4cd60ab5f139536bd8830c99a485afafb286fb733f7f5c1c66a3",
        "read/diff-01-of-01.patch": "1a5b850ed048a66a42a97227e04f94d1d12d1acdb5f3b403594dae5b8a5cdf37",
        "read/files-01-of-01.md": "3572f886a85b0c230fba51efc94dce5211dcd1fd8e38a0a5cd7c1c5eddee6f9e",
        "read/integration_state.md": "4b4a61486165c0195313ed27aa59ec8a4fb665592220f3c1add32451d476ea1e",
        "read/knowledge/control/skill.md": "7f6db5b531beb4a0e58910feec49b55eed1ccf799282dbdd50dceefa7ad32e3f",
        "read/knowledge/control/standards.md": "17e01656cc9329f09553d2258445ebec28881fddf2b2f102b04a6f858dd7908e",
        "read/knowledge/cross/standards.md": "17e01656cc9329f09553d2258445ebec28881fddf2b2f102b04a6f858dd7908e",
        "read/rubric.md": "1aa9a1ae1cf24b1e72b143d3e56c0deb89d49554c138bab503d5149a74c9a63d",
        "read/spec_as_issued.md": "b30036946b9c9dede462b171dca4c49fb82132852b184a8e5162b01cd82f5eea",
        "read/transcript-01-of-01.md": "226b48aebf1d14f511cc47449b15056524bfe704ab730947941a6774b297de4e",
        "read/worktree/.physgate/specs/s1.md": "5b7d08241cbad861cd9616b956478f3144e986b6c4abaef19e6520307d6853fc",
        "read/worktree/m/ctl.py": "ad0577166e7c97ba81e032102d0315c61853df25d1c652414de5f601f7fd379a",
        "read/worktree/m/link": "2fb8bbdff4d80f8e2eb782b4c887783ac8964fe7bf681de0385807998a1ef27b",
    },
}


@pytest.mark.parametrize("form", ["plain", "ordered", "integration"])
def test_every_attempt_packet_is_byte_identical_to_todays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, form: str
) -> None:
    found = shown(tmp_path, monkeypatch, form)
    assert len(found) > 10
    assert found == PINNED[form]
