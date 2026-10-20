"""The OS layer's deny list is generated from the same registry the hooks read.

A session's protected paths are named once, in its session configuration. The
OS layer's settings are a function of that configuration and of the session's
own three writable places (its worktree, its temporary directory and its home),
so the two layers cannot disagree about what is protected. The rules:

- **Writes** are allowed only in the three places; everything else is denied by
  the OS already. A protected path inside one of them is denied by name, existing
  or not; one that does not exist yet is listed for the sweep, because on Linux it
  becomes an empty placeholder file while a command runs.
  A root with a writable path beneath it is named child by child, around it.
- **Reads** are denied for what the registry withholds from reading, and for
  what it marks as the OS layer's to withhold from shell commands. A read-denied
  root above the session's home has the home opened again.
- **The file tools** get no rule here: the hooks refuse them and log it, and a
  permission rule would refuse first, unlogged.
"""

from __future__ import annotations

import os
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
from physgate.oslayer.policy import EVERY_ENTRY, FIELD_RULES, OsPolicy, sandbox_policy


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


def test_only_the_session_s_home_is_added_to_the_writable_places(
    tmp_path: Path,
) -> None:
    policy, paths = _policy(tmp_path)
    assert _fs(policy)["allowWrite"] == [str(paths["sdir"] / "home")]


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


def test_inside_the_worktree_an_absent_path_is_named_and_listed_for_the_sweep(
    tmp_path: Path,
) -> None:
    policy, paths = _policy(tmp_path)
    deny = set(_fs(policy)["denyWrite"])
    worktree = paths["worktree"]
    assert str(worktree / "corpora") in deny and str(worktree / ".git") in deny
    assert str(worktree / "corpora") not in policy.absent_named  # it exists
    for path in (worktree / ".env", worktree / ".claude"):  # absent, their parent exists
        assert str(path) in deny and str(path) in policy.absent_named
    # Absent with a missing parent: left to the hooks, so a command can still make ``src``.
    assert str(worktree / "src" / "physgate" / "gate") not in deny


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


def test_the_home_s_git_configuration_is_denied_where_its_parent_exists(tmp_path: Path) -> None:
    policy, paths = _policy(tmp_path)
    deny = set(_fs(policy)["denyWrite"])
    home = paths["sdir"] / "home"
    assert str(home / ".gitconfig") in deny  # absent, in the home, which exists
    # ``~/.config`` is absent too: denying ``~/.config/git`` would keep a tool from making
    # ``~/.config`` at all, so that one is the hooks' and the sentinel's alone.
    assert str(home / ".config" / "git") not in deny
    (home / ".config").mkdir()
    again = sandbox_policy(_config(paths), home=str(home), temp_dir=str(paths["temp"]))
    assert str(home / ".config" / "git") in _fs(again)["denyWrite"]


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


def test_every_write_protected_root_is_denied_or_left_to_a_script_by_name(tmp_path: Path) -> None:
    # Every root the hooks refuse a write to is named, inside the worktree too, whether it
    # exists yet or not; the one exception is a root the registry leaves to scripts.
    policy, paths = _policy(tmp_path)
    config = _config(paths)
    deny = set(_fs(policy)["denyWrite"])
    writable = (str(paths["worktree"]), str(paths["temp"]), str(paths["sdir"] / "home"))
    for root in config.protected_roots:
        above = any(Path(w).is_relative_to(root.path) for w in writable)
        orphan = not Path(root.path).exists() and not Path(root.path).parent.exists()
        if root.shell_writes == "allowed" or above or root.exceptions or orphan:
            continue
        # Named itself, or beneath a named path that denies it with everything else there.
        assert any(Path(root.path).is_relative_to(d) for d in deny), root.path
    worktree = paths["worktree"]
    for absent in (worktree / ".env", worktree / ".claude"):
        assert str(absent) in deny and str(absent) in policy.absent_named


def test_the_series_outbox_is_left_to_the_scripts_that_write_it(tmp_path: Path) -> None:
    # A record arrives only by a script's own write, and the collector judges it: an OS rule
    # cannot tell that script from any other command, so it is not the OS layer's to deny.
    policy, paths = _policy(tmp_path)
    outbox = paths["worktree"] / ".physgate" / "series"
    (paths["worktree"] / ".physgate").mkdir()
    policy = sandbox_policy(
        _config(paths), home=str(paths["sdir"] / "home"), temp_dir=str(paths["temp"])
    )
    assert str(outbox) not in _fs(policy)["denyWrite"]
    assert str(paths["worktree"] / ".physgate" / "lib") in _fs(policy)["denyWrite"]


def _outbox_policy(tmp_path: Path, platform: str) -> tuple[dict[str, Any], Path]:
    paths = _layout(tmp_path)
    outbox = paths["worktree"] / ".physgate" / "series"
    outbox.mkdir(parents=True)
    policy = sandbox_policy(
        _config(paths),
        home=str(paths["sdir"] / "home"),
        temp_dir=str(paths["temp"]),
        platform=platform,
    )
    return _fs(policy), outbox


def test_on_macos_the_outbox_is_read_denied_whole_and_left_writable(tmp_path: Path) -> None:
    # Seatbelt denies the listing and every file in it, and a write is not a read there, so
    # a script still creates and replaces its records.
    fs, outbox = _outbox_policy(tmp_path, "darwin")
    assert str(outbox) in fs["denyRead"]
    assert not any(outbox.is_relative_to(d) for d in fs["denyWrite"])


def test_on_linux_the_outbox_s_entries_are_read_denied_and_the_directory_is_not(
    tmp_path: Path,
) -> None:
    # bubblewrap lays an empty layer over a read-denied directory, and the writer's rename into
    # it fails as a move across devices: the entries are denied instead, as they stand when
    # each command starts.
    fs, outbox = _outbox_policy(tmp_path, "linux")
    assert str(outbox / EVERY_ENTRY) in fs["denyRead"]
    assert not any(outbox.is_relative_to(d) for d in fs["denyRead"] if not d.endswith("*"))
    assert not any(outbox.is_relative_to(d) for d in fs["denyWrite"])


def test_only_the_root_scripts_write_is_read_denied_by_its_entries(tmp_path: Path) -> None:
    fs, outbox = _outbox_policy(tmp_path, "linux")
    by_entries = [d for d in fs["denyRead"] if d.endswith(f"/{EVERY_ENTRY}")]
    assert by_entries and {str(Path(d).parent) for d in by_entries} <= {
        str(outbox),
        os.path.realpath(outbox),
    }


@pytest.mark.parametrize("platform", ["win32", "cygwin", "freebsd14", ""])
def test_a_platform_with_no_mechanism_for_the_outbox_gets_no_policy(
    tmp_path: Path, platform: str
) -> None:
    # Fails closed: no settings that would leave the outbox readable to the shell.
    with pytest.raises(ValueError, match="series outbox"):
        _outbox_policy(tmp_path, platform)


@pytest.mark.parametrize(
    "spelling",
    [
        "knowledge/control/x.md",
        "knowledge/staging/x.md",
        "knowledge/stagingx/x.md",
        "knowledge-other/x.md",
        "corpora/x.json",
        "corpora-other/x.json",
        ".physgate/lib/x.py",
        ".physgate/libx/x.py",
        ".physgate/series/r.json",
        ".physgate/series-other/r.json",
        "experiments/R-XX-02/new.md",
        "experiments/R-XX-02b/new.md",
        "experiments/R-XX-01/CRITERIA.md",
        "experiments/R-XX-01/notes.md",
        ".git",
        ".gitx",
        "src/physgate/gate/check.py",
        "src/physgate/gatex/check.py",
    ],
)
def test_the_os_rules_judge_a_write_as_the_hooks_do(tmp_path: Path, spelling: str) -> None:
    # The OS layer denies a write when the path is a named entry or lies beneath one, by
    # whole path components; the hooks' own matcher is held to the same answer.
    from physgate.hooks import paths as hook_paths

    (tmp_path / "x").mkdir()
    paths = _layout(tmp_path / "x")
    for name in (
        "knowledge/stagingx",
        "knowledge-other",
        "corpora-other",
        ".physgate/libx",
        "src/physgate",
    ):
        (paths["worktree"] / name).mkdir(parents=True, exist_ok=True)
    (paths["worktree"] / ".git").write_text("gitdir: x\n")
    policy = sandbox_policy(
        _config(paths), home=str(paths["sdir"] / "home"), temp_dir=str(paths["temp"])
    )
    target = paths["worktree"] / spelling
    deny = _fs(policy)["denyWrite"]
    os_denies = any(target == Path(d) or target.is_relative_to(Path(d)) for d in deny)
    hook = hook_paths.protection(str(target), str(paths["worktree"]), _config(paths), writing=True)
    script_only = ".physgate/series/" in spelling
    assert os_denies == (hook is not None and not script_only), (spelling, hook)


def test_a_child_made_in_the_knowledge_tree_after_the_start_is_the_hooks_alone(
    tmp_path: Path,
) -> None:
    # The tree is named child by child around its staging directory, as the children stand
    # when the session starts; one made later is refused by the hooks and put back by the
    # sentinel, and is the OS layer's stated residual.
    policy, paths = _policy(tmp_path)
    later = paths["worktree"] / "knowledge" / "made-later"
    assert not any(later.is_relative_to(d) for d in _fs(policy)["denyWrite"])


def test_a_path_given_through_a_link_is_named_where_it_really_is_too(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "via").symlink_to(real)
    policy, paths = _policy(tmp_path / "via")
    deny = set(_fs(policy)["denyWrite"])
    held_as_given = str(paths["held"])
    assert held_as_given in deny and os.path.realpath(held_as_given) in deny
    assert os.path.realpath(held_as_given) != held_as_given


def test_a_path_beneath_another_named_one_is_not_named_again(tmp_path: Path) -> None:
    # The common git directory is denied whole; its config files, protected on their own
    # in the registry, are not named again, so bubblewrap makes no placeholder for them.
    policy, paths = _policy(tmp_path)
    deny = _fs(policy)["denyWrite"]
    common = str(paths["common"])
    assert common in deny
    assert not [d for d in deny if d != common and Path(d).is_relative_to(common)]
    assert not [a for a in deny if any(a != b and Path(a).is_relative_to(b) for b in deny)]


def test_the_shared_temp_is_writable_and_claude_code_s_own_is_denied_both_ways(
    tmp_path: Path,
) -> None:
    paths = _layout(tmp_path)
    shared = tmp_path / "shared-tmp"
    claude = shared / "claude-501"
    claude.mkdir(parents=True)
    policy = sandbox_policy(
        _config(paths),
        home=str(paths["sdir"] / "home"),
        temp_dir=str(paths["temp"]),
        shared_temp=(str(shared),),
        claude_temp=(str(claude),),
    )
    fs = _fs(policy)
    assert str(shared) in fs["allowWrite"]
    assert str(claude) in fs["denyWrite"] and str(claude) in fs["denyRead"]


def test_a_run_directory_inside_the_shared_temp_keeps_its_sessions_denied(
    tmp_path: Path,
) -> None:
    # On a machine whose run directory sits under the shared /tmp, the run's sessions/
    # would be writable with it: it is named around the session's own home instead.
    paths = _layout(tmp_path)
    other = paths["run"] / "sessions" / "s0"
    other.mkdir()
    policy = sandbox_policy(
        _config(paths),
        home=str(paths["sdir"] / "home"),
        temp_dir=str(paths["temp"]),
        shared_temp=(str(tmp_path),),
    )
    deny = _fs(policy)["denyWrite"]
    for denied in (other, paths["sdir"] / "state", paths["sdir"] / "config"):
        assert any(Path(denied).is_relative_to(d) for d in deny), denied
    home = paths["sdir"] / "home"
    assert not any(home.is_relative_to(d) for d in deny)
