"""Two runs on the same tool environment compare equal wherever it lies; another environment drifts.

A tool environment's record names absolute paths: its roots, its interpreter, its prefix and each
native tool. Two machines that run the same environment place it at other roots, so drift compares
a normal form: each path relative to the root that holds it, with the digest over every file, the
counts, the interpreter's version, every distribution and every tool's version. A changed digest,
version or library is drift; another root is not.
"""

from __future__ import annotations

from pathlib import Path

from observe_rig import config, target_repo

from physgate.evaluation.observe.compare import drift
from physgate.toolenv.record import Distribution, NativeTool, ToolEnvironment


def _environment(root: str, *, digest: str = "a" * 64, numpy: str = "2.3.1") -> ToolEnvironment:
    return ToolEnvironment(
        interpreter=f"{root}/venv/bin/python",
        resolved=f"{root}/venv/bin/python3.12",
        python_version="3.12.9",
        prefix=f"{root}/venv",
        distributions=(Distribution(name="numpy", version=numpy),),
        native_tools=(
            NativeTool(
                name="pio",
                path=f"{root}/bin/pio",
                resolved=f"{root}/venv/bin/pio",
                version="6.1.18",
            ),
        ),
        roots=(root,),
        manifest_digest=digest,
        entries=12,
        total_bytes=3456,
    )


def _drift(tmp_path: Path, mine: ToolEnvironment, theirs: ToolEnvironment) -> list[str]:
    repo = target_repo(tmp_path)
    return drift(
        config("run-a", repo, "electrical", tool_environment=mine),
        config("run-b", repo, "electrical", tool_environment=theirs),
    )


def test_the_same_environment_at_two_roots_is_no_drift(tmp_path: Path) -> None:
    assert _drift(tmp_path, _environment("/srv/tools"), _environment("/home/u/pg-tools")) == []


def test_a_changed_digest_is_drift(tmp_path: Path) -> None:
    changed = _environment("/srv/tools", digest="b" * 64)
    assert "tool_environment" in _drift(tmp_path, _environment("/srv/tools"), changed)


def test_a_changed_library_at_another_root_is_drift(tmp_path: Path) -> None:
    changed = _environment("/home/u/pg-tools", numpy="2.3.2")
    assert "tool_environment" in _drift(tmp_path, _environment("/srv/tools"), changed)


def test_a_run_with_an_environment_and_one_without_drift(tmp_path: Path) -> None:
    repo = target_repo(tmp_path)
    found = drift(
        config("run-a", repo, "electrical", tool_environment=_environment("/srv/tools")),
        config("run-b", repo, "electrical", tool_environment=None),
    )
    assert "tool_environment" in found
