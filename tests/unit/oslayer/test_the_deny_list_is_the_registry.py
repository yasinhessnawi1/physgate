"""The OS layer's deny list is generated from the same registry the hooks read.

A session's protected paths are named once, in its session configuration. The
OS layer's settings are a function of that configuration and of the session's
own three writable places (its worktree, its temporary directory and its home),
so the two layers cannot disagree about what is protected. The rules:

- **Writes** are allowed only in the three places; everything else is denied by
  the OS already. A protected path inside one of them is denied by name, but on
  Linux a denied path that does not exist yet becomes an empty placeholder file
  while a command runs, so inside a writable place only what exists is named.
  A root with a writable path beneath it is named child by child, around it.
- **Reads** are denied for what the registry withholds from reading, and for
  what it marks as the OS layer's to withhold from shell commands. A read-denied
  root above the session's home has the home opened again.
- **The file tools** get no rule here: the hooks refuse them and log it, and a
  permission rule would refuse first, unlogged.
"""

from __future__ import annotations

import typing
from pathlib import Path
from typing import Any

import pytest

from physgate.hooks.config import (
    AbsolutePath,
    ExperimentRule,
    Installation,
    ProtectedRoot,
    SessionConfig,
)
from physgate.hooks.settings import InstallRequest, build_config, current_installation
from physgate.oslayer.policy import FIELD_RULES, OsPolicy, sandbox_policy


def _layout(tmp_path: Path) -> dict[str, Path]:
    run = tmp_path / "run"
    sdir = run / "sessions" / "s1"
    worktree = run / "worktrees" / "sub1"
    for d in (worktree / "src", sdir / "home", sdir / "state", sdir / "session", sdir / "config"):
        d.mkdir(parents=True)
    harness = tmp_path / "harness"
    (harness / "knowledge" / "reviewers").mkdir(parents=True)
    (harness / "corpora").mkdir()
    (worktree / "knowledge" / "control").mkdir(parents=True)
    (worktree / "knowledge" / "staging").mkdir(parents=True)
    (worktree / "knowledge" / "README.md").write_text("x")
    (worktree / "corpora").mkdir()
    (worktree / "experiments" / "R-XX-01").mkdir(parents=True)
    (worktree / "experiments" / "R-XX-01" / "CRITERIA.md").write_text("c")
    (worktree / "experiments" / "R-XX-02" / "metrics").mkdir(parents=True)
    (worktree / "experiments" / "R-XX-02" / "RESULT.md").write_text("r")
    (worktree / "experiments" / "R-XX-02" / "CRITERIA.md").write_text("c")
    held = tmp_path / "heldout"
    held.mkdir()
    temp = tmp_path / "pg-0123456789ab"
    temp.mkdir()
    return {
        "run": run,
        "sdir": sdir,
        "worktree": worktree,
        "harness": harness,
        "held": held,
        "temp": temp,
        "common": run / "repo" / ".git",
    }


def _config(paths: dict[str, Path]) -> SessionConfig:
    sdir = paths["sdir"]
    (paths["common"]).mkdir(parents=True, exist_ok=True)
    request = InstallRequest(
        profile="role",
        role="control",
        worktree=str(paths["worktree"]),
        own_branch="subtask/sub1",
        store_root=str(paths["run"] / "store"),
        state_dir=str(sdir / "state"),
        target_dir=str(sdir / "session"),
        claude_config_dir=str(sdir / "config"),
        user_home=str(sdir / "home"),
        token_ceiling=1000,
        held_out=(str(paths["held"]),),
        extra_protected=(str(paths["common"]), str(paths["worktree"] / ".git")),
        extra_protected_refuse_only=(
            str(paths["run"] / "sessions"),
            str(paths["run"] / "queue_decisions.jsonl"),
        ),
        harness_root=str(paths["harness"]),
    )
    return build_config(request, current_installation())


def _policy(tmp_path: Path) -> tuple[OsPolicy, dict[str, Path]]:
    paths = _layout(tmp_path)
    (paths["worktree"] / ".git").write_text("gitdir: x\n")
    policy = sandbox_policy(
        _config(paths), home=str(paths["sdir"] / "home"), temp_dir=str(paths["temp"])
    )
    return policy, paths


def _fs(policy: OsPolicy) -> dict[str, Any]:
    fs: dict[str, Any] = policy.settings["sandbox"]["filesystem"]
    return fs


def test_the_sandbox_is_strict_and_refuses_to_start_without_its_layer(tmp_path: Path) -> None:
    policy, _ = _policy(tmp_path)
    sandbox = policy.settings["sandbox"]
    assert sandbox["enabled"] is True
    assert sandbox["failIfUnavailable"] is True
    assert sandbox["allowUnsandboxedCommands"] is False
    assert sandbox["excludedCommands"] == []
    assert sandbox["autoAllowBashIfSandboxed"] is True


def test_only_the_session_s_home_and_its_own_descriptors_are_added_to_the_writable_places(
    tmp_path: Path,
) -> None:
    policy, paths = _policy(tmp_path)
    assert _fs(policy)["allowWrite"] == [str(paths["sdir"] / "home"), "/dev/fd"]


def test_every_protected_path_outside_the_writable_places_is_denied_whole(tmp_path: Path) -> None:
    policy, paths = _policy(tmp_path)
    deny = set(_fs(policy)["denyWrite"])
    for path in (
        paths["common"],
        paths["harness"],
        paths["held"],
        paths["run"] / "queue_decisions.jsonl",
        paths["run"] / "store",
    ):
        assert str(path) in deny, path


def test_a_root_above_a_writable_place_is_not_denied_over_it(tmp_path: Path) -> None:
    policy, paths = _policy(tmp_path)
    deny = _fs(policy)["denyWrite"]
    home = paths["sdir"] / "home"
    assert all(not Path(home).is_relative_to(Path(d)) for d in deny), deny
    # The session's other files beside its home stay denied by name.
    for name in ("state", "config"):
        assert str(paths["sdir"] / name) in deny


def test_inside_the_worktree_only_what_exists_is_named(tmp_path: Path) -> None:
    policy, paths = _policy(tmp_path)
    deny = set(_fs(policy)["denyWrite"])
    worktree = paths["worktree"]
    assert str(worktree / "corpora") in deny and str(worktree / ".git") in deny
    absent = [worktree / ".env", worktree / "src" / "physgate" / "gate", worktree / ".claude"]
    for path in absent:
        assert str(path) not in deny
        assert str(path) in policy.not_named


def test_the_knowledge_tree_is_named_child_by_child_around_its_staging(tmp_path: Path) -> None:
    policy, paths = _policy(tmp_path)
    deny = set(_fs(policy)["denyWrite"])
    knowledge = paths["worktree"] / "knowledge"
    assert str(knowledge) not in deny
    assert str(knowledge / "control") in deny and str(knowledge / "README.md") in deny
    assert not any(Path(d).is_relative_to(knowledge / "staging") for d in deny)


def test_frozen_experiments_are_named_as_the_hooks_freeze_them(tmp_path: Path) -> None:
    policy, paths = _policy(tmp_path)
    deny = set(_fs(policy)["denyWrite"])
    experiments = paths["worktree"] / "experiments"
    assert str(experiments / "R-XX-02") in deny  # a result exists: the whole directory
    assert str(experiments / "R-XX-01" / "CRITERIA.md") in deny  # criteria alone
    assert str(experiments / "R-XX-01") not in deny


def test_the_home_s_git_configuration_is_denied_whether_or_not_it_exists(tmp_path: Path) -> None:
    policy, paths = _policy(tmp_path)
    deny = set(_fs(policy)["denyWrite"])
    home = paths["sdir"] / "home"
    assert {str(home / ".gitconfig"), str(home / ".config" / "git")} <= deny


def test_reads_are_denied_for_what_is_withheld_and_the_home_is_opened_again(
    tmp_path: Path,
) -> None:
    policy, paths = _policy(tmp_path)
    fs = _fs(policy)
    deny = set(fs["denyRead"])
    for path in (
        paths["held"],
        paths["worktree"] / "corpora",
        paths["harness"],
        paths["harness"] / "knowledge" / "reviewers",
        paths["run"] / "sessions",
        paths["sdir"] / "state",
        paths["sdir"] / "config",
        paths["run"] / "queue_decisions.jsonl",
    ):
        assert str(path) in deny, path
    assert fs["allowRead"] == [str(paths["sdir"] / "home")]
    for readable in (paths["worktree"], paths["run"] / "store", paths["common"]):
        assert str(readable) not in deny


def test_no_permission_rule_is_written_so_the_hooks_see_every_file_tool_call(
    tmp_path: Path,
) -> None:
    # A Read rule would refuse a file tool before any hook ran, unlogged.
    policy, _ = _policy(tmp_path)
    assert set(policy.settings) == {"sandbox"}


def test_no_path_is_a_pattern(tmp_path: Path) -> None:
    policy, _ = _policy(tmp_path)
    fs = _fs(policy)
    for name in ("allowWrite", "denyWrite", "denyRead", "allowRead"):
        for path in fs[name]:
            assert path.startswith("/") and not set(path) & set("*?[")


def test_a_temporary_directory_inside_a_read_denied_root_is_refused(tmp_path: Path) -> None:
    paths = _layout(tmp_path)
    config = _config(paths)
    inside = str(paths["sdir"] / "tmp")  # under the run's sessions/, which shells may not read
    with pytest.raises(ValueError, match="temporary directory"):
        sandbox_policy(config, home=str(paths["sdir"] / "home"), temp_dir=inside)


#: The models whose fields are paths, found in the session configuration's fields.
_PATH_MODELS = (ProtectedRoot, ExperimentRule, Installation)


def _holds_paths(field: Any) -> bool:  # noqa: ANN401 - a pydantic field
    absolute = "'^/'" in repr(field) + repr(field.annotation)  # an AbsolutePath, bare or held
    nested = any(model.__name__ in repr(field.annotation) for model in _PATH_MODELS)
    return absolute or nested


def test_every_path_field_of_the_registry_has_a_rule() -> None:
    # A new kind of path in the session configuration cannot be added without the
    # generator saying what the OS layer does with it.
    assert "'^/'" in repr(typing.get_args(AbsolutePath))
    found = {name for name, f in SessionConfig.model_fields.items() if _holds_paths(f)}
    assert found == set(FIELD_RULES)
    assert {"worktree", "state_dir", "protected_roots", "held_out"} <= found


def test_the_withheld_fields_are_denied_on_their_own_without_the_roots_marks(
    tmp_path: Path,
) -> None:
    # Each field of the configuration that withholds reading is a rule of its own,
    # so a root that lost its mark does not reopen what the field names.
    paths = _layout(tmp_path)
    config = _config(paths)
    unmarked = config.model_copy(
        update={
            "protected_roots": tuple(
                r.model_copy(update={"reads": "open"}) for r in config.protected_roots
            )
        }
    )
    policy = sandbox_policy(unmarked, home=str(paths["sdir"] / "home"), temp_dir=str(paths["temp"]))
    deny = set(_fs(policy)["denyRead"])
    for path in (*config.held_out, *config.answer_keys, *config.review_material, config.state_dir):
        assert path in deny, path


def test_a_further_place_of_the_session_s_own_is_opened_again_like_its_home(
    tmp_path: Path,
) -> None:
    paths = _layout(tmp_path)
    config = _config(paths)
    home, bin_dir = str(paths["sdir"] / "home"), str(paths["sdir"] / "bin")
    policy = sandbox_policy(config, home=home, temp_dir=str(paths["temp"]), readable=(bin_dir,))
    assert _fs(policy)["allowRead"] == sorted([home, bin_dir])
