from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from physgate.evaluation.per_role.arms.harness import extract

RUN = "run-1"
BRANCH = f"physgate/{RUN}/run"


def _repo(tmp_path: Path, files: dict[str, bytes], links: dict[str, str] | None = None) -> Path:
    repo = tmp_path / "target"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, env=env)

    run("init", "-q", "-b", "master")
    # The blob is what the run committed, byte for byte, whatever the machine's own git
    # would do to line endings on the way in.
    run("config", "core.autocrlf", "false")
    (repo / "README.md").write_text("target\n")
    for rel, data in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_bytes(data)
    for rel, target in (links or {}).items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).symlink_to(target)
    run("add", "-A")
    run("commit", "-q", "-m", "run")
    run("branch", BRANCH)
    return repo


ANSWER = json.dumps({"form": "lti_tf"}).encode()


def test_the_one_answer_in_a_module_directory_is_extracted(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"modules/control/answer.json": ANSWER, "answer.json": b"{}"})
    out = tmp_path / "out" / "answer.json"
    found = extract(repo, RUN, "answer.json", out)
    assert found.status == "found" and found.paths == ("modules/control/answer.json",)
    assert out.read_bytes() == ANSWER


@pytest.mark.parametrize(
    ("files", "status"),
    [
        ({"answer.json": ANSWER}, "contract_lost"),
        ({"modules/control/deep/answer.json": ANSWER}, "contract_lost"),
        (
            {"modules/control/answer.json": ANSWER, "modules/firmware/answer.json": ANSWER},
            "ambiguous",
        ),
        ({"modules/control/answer.json": b"x" * (64 * 1024 + 1)}, "too_large"),
        ({"modules/control/answer.json": b"\xff\xfe"}, "not_text"),
        ({"modules/control/answer.json/inner": ANSWER}, "not_a_file"),
    ],
    ids=["only at the root", "too deep", "two modules", "too large", "not text", "a directory"],
)
def test_anything_but_one_answer_file_is_no_answer_and_says_why(
    tmp_path: Path, files: dict[str, bytes], status: str
) -> None:
    out = tmp_path / "out" / "answer.json"
    found = extract(_repo(tmp_path, files), RUN, "answer.json", out)
    assert found.status == status
    assert not out.exists()


def test_a_link_named_as_the_answer_is_not_followed(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        {"elsewhere.json": ANSWER},
        links={"modules/control/answer.json": "../../elsewhere.json"},
    )
    out = tmp_path / "out" / "answer.json"
    assert extract(repo, RUN, "answer.json", out).status == "not_a_file"
    assert not out.exists()


@pytest.mark.parametrize(
    "answer",
    [b'{"form": "lti_tf"}\r\n', b'{"form":\r"lti_tf"}', b'{"form": "lti_tf"}\n'],
    ids=["CRLF", "a lone CR", "LF"],
)
def test_the_harness_answer_is_taken_byte_for_byte_as_the_raw_arm_s_is(
    tmp_path: Path, answer: bytes
) -> None:
    """The raw arm copies its answer as it is; the harness arm's is read the same way.

    A read that turns line endings into newlines scores bytes the run never wrote, and records
    a digest that is not the blob's.
    """
    repo = _repo(tmp_path, {"modules/control/answer.json": answer})
    out = tmp_path / "out" / "answer.json"
    found = extract(repo, RUN, "answer.json", out)
    assert found.status == "found"
    assert out.read_bytes() == answer
    assert found.sha256 == hashlib.sha256(answer).hexdigest()
