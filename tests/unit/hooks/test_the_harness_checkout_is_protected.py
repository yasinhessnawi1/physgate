"""The checkout the orchestrator runs from is out of reach of a session in another worktree.

A role session runs in the target repository's worktree. The orchestrator's own
checkout is somewhere else, and holds what judges that session: the physics
gate's source, the curated library and its bounds tables, the frozen
experiments. Before this, nothing named that checkout, so a session could write
it by absolute path and the run noticed nothing (found live with a scripted
session, zero tokens). Now the whole checkout is refused before a write, and the
trees a run trusts are also put back after one by the sentinel.

The bypass suite (``tests/integration/hooks``) proves it against the real binary
through the tool, shell and interpreter paths; this is the fast, direct check of
the configuration and the matcher.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from hook_helpers import event, volume_is_case_insensitive

from physgate.hooks.config import HookInput, ProtectedRoot
from physgate.hooks.paths import pre_tool_use, protection, read_refused
from physgate.hooks.reasons import (
    HARNESS_REASON,
    SENTINEL_APART_REASON,
    WITHHELD_REASON,
    WITHHELD_WHOLE_REASON,
)
from physgate.hooks.settings import (
    HARNESS_REVERTED,
    InstallRequest,
    build_config,
    current_installation,
)


def _harness(tmp: Path) -> Path:
    harness = tmp / "harness"
    for rel in (
        "src/physgate/gate/runner.py",
        "knowledge/control/standards.md",
        "knowledge/control/skill.md",
        "knowledge/electrical/skill.md",
        "knowledge/electrical/bounds.toml",
        "knowledge/staging/candidate.md",
        "experiments/R-XX-01/CRITERIA.md",
        "experiments/R-XX-01/RESULT.md",
        "experiments/R-XX-01/runs/metrics.csv",
        "experiments/R-YY-02/criteria.md",
        "README.md",
        ".venv/lib/python3.12/site-packages/x.pth",
    ):
        path = harness / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("bytes\n")
    return harness


def _request(tmp: Path, **overrides: Any) -> InstallRequest:  # noqa: ANN401 - test fields
    worktree = tmp / "worktree"
    worktree.mkdir(exist_ok=True)
    fields: dict[str, Any] = {
        "profile": "role",
        "role": "control",
        "worktree": str(worktree),
        "own_branch": "subtask/c1",
        "store_root": str(tmp / "store"),
        "state_dir": str(tmp / "state"),
        "target_dir": str(tmp / "session"),
        "claude_config_dir": str(tmp / "claude-config"),
        "user_home": str(tmp / "home"),
        "token_ceiling": 4000,
    }
    fields.update(overrides)
    return InstallRequest(**fields)


def _roots(config: Any) -> dict[str, tuple[str, str, tuple[str, ...]]]:  # noqa: ANN401 - test helper
    return {r.path: (r.reason, r.watch, tuple(r.exceptions)) for r in config.protected_roots}


def test_the_whole_checkout_is_refused_and_its_trusted_trees_are_put_back(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    config = build_config(_request(tmp_path, harness_root=str(harness)), current_installation())
    roots = _roots(config)
    assert roots[str(harness)] == (HARNESS_REASON, "none", ())
    for name in HARNESS_REVERTED:
        assert roots[str(harness / name)] == (HARNESS_REASON, "revert", ())
    for rel in (
        "experiments/R-XX-01/CRITERIA.md",
        "experiments/R-XX-01/RESULT.md",
        "experiments/R-YY-02/criteria.md",
    ):
        assert roots[str(harness / rel)] == (HARNESS_REASON, "revert", ()), rel
    # Put back by name, never the whole experiment directory: measured at 214 MB
    # copied at every session's start on the main checkout.
    assert str(harness / "experiments") not in roots
    assert str(harness / "experiments/R-XX-01") not in roots
    assert str(harness / ".venv") not in roots


@pytest.mark.parametrize(
    "rel",
    [
        "src/physgate/gate/runner.py",
        "src/physgate/gate/check_new.py",
        "knowledge/control/standards.md",
        "knowledge/control/planted.md",
        "knowledge/electrical/bounds.toml",
        # The harness's own staging is not an exception for a session elsewhere:
        # that session's staging is in its own worktree.
        "knowledge/staging/candidate.md",
        "experiments/R-XX-01/RESULT.md",
        "experiments/R-XX-01/runs/metrics.csv",
        "README.md",
        ".venv/lib/python3.12/site-packages/x.pth",
        "a/path/that/does/not/exist/yet.py",
    ],
)
def test_every_write_into_the_checkout_is_refused(tmp_path: Path, rel: str) -> None:
    harness = _harness(tmp_path)
    worktree = tmp_path / "worktree"
    config = build_config(_request(tmp_path, harness_root=str(harness)), current_installation())
    assert protection(str(harness / rel), str(worktree), config, writing=True) == HARNESS_REASON


#: Every place in the checkout a file tool could aim a read at: the role's own skill and
#: standards (what an arm without the skill must not reach through the harness's copy),
#: another role's, the gate's source, a frozen record, an untrusted file, the orchestrator's
#: environment, and a path that does not exist yet.
READ_TARGETS = [
    "knowledge/control/skill.md",
    "knowledge/control/standards.md",
    "knowledge/electrical/skill.md",
    "knowledge/electrical/bounds.toml",
    "src/physgate/gate/runner.py",
    "experiments/R-XX-01/RESULT.md",
    "README.md",
    ".venv/lib/python3.12/site-packages/x.pth",
    "a/path/that/does/not/exist/yet.md",
]


def _arm_request(tmp: Path, profile: str, hooks: str, harness: Path) -> InstallRequest:
    if profile == "baseline":
        # The raw agent names its own session directory, as its arm installs it.
        return _request(
            tmp,
            profile="baseline",
            role=None,
            own_branch=None,
            sessions_root=str(tmp / "sdir"),
            harness_root=str(harness),
        )
    return _request(tmp, hooks=hooks, harness_root=str(harness))


@pytest.mark.parametrize("rel", READ_TARGETS)
@pytest.mark.parametrize(
    ("profile", "hooks"), [("role", "on"), ("role", "off"), ("baseline", "on")]
)
def test_every_read_of_the_checkout_by_a_file_tool_is_refused_under_every_arm(
    tmp_path: Path, rel: str, profile: str, hooks: str
) -> None:
    harness = _harness(tmp_path)
    config = build_config(_arm_request(tmp_path, profile, hooks, harness), current_installation())
    reason = protection(str(harness / rel), str(tmp_path / "worktree"), config, writing=False)
    assert reason == HARNESS_REASON, (
        f"a file tool may read {rel} in the harness checkout; every read there is refused"
    )


def test_the_read_tool_is_refused_the_harness_s_skill_file_naming_the_checkout(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    config = build_config(_request(tmp_path, harness_root=str(harness)), current_installation())
    target = str(harness / "knowledge/control/skill.md")
    call = event(cwd=str(tmp_path / "worktree"), tool_name="Read", tool_input={"file_path": target})
    decision = pre_tool_use(HookInput.model_validate(call), config)
    assert not decision.allow, "the Read tool may read the harness's own copy of the role's skill"
    assert HARNESS_REASON in decision.reason


def test_a_case_variant_or_a_link_into_the_checkout_is_refused_a_read(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    worktree = tmp_path / "worktree"
    config = build_config(_request(tmp_path, harness_root=str(harness)), current_installation())
    link = worktree / "library"
    link.symlink_to(harness / "knowledge")
    via_link = protection(str(link / "control/skill.md"), str(worktree), config, writing=False)
    assert via_link == HARNESS_REASON, "a link in the worktree reads the harness's library"
    if volume_is_case_insensitive(tmp_path):
        variant = str(harness / "KNOWLEDGE/Control/SKILL.md")
        assert protection(variant, str(worktree), config, writing=False) == HARNESS_REASON, (
            "a case variant reads the harness's library"
        )


def test_the_sentinel_still_keeps_the_checkout_s_trusted_bytes_to_put_them_back(
    tmp_path: Path,
) -> None:
    # Refused to every tool for what the library would teach a session, not because its bytes
    # are a secret: the sentinel keeps them in the hooks' own state, which nothing of the
    # session reads, so that it can put a changed trusted file back. Sealed, a tampered gate
    # source or standards file would stay as the session left it.
    harness = _harness(tmp_path)
    config = build_config(_request(tmp_path, harness_root=str(harness)), current_installation())
    for rel in ("src/physgate/gate/runner.py", "knowledge/control/standards.md"):
        assert not read_refused(str(harness / rel), config), (
            f"the sentinel would seal {rel} and could not put the harness's file back"
        )


def test_without_a_harness_nothing_changes(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with_none = _roots(build_config(_request(tmp_path), current_installation()))
    assert not [p for p in with_none if p.startswith(str(harness))]


def test_a_worktree_inside_the_checkout_is_refused_at_install(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    inside = harness / "runs" / "worktree"
    inside.mkdir(parents=True)
    with pytest.raises(ValueError, match="contains the worktree"):
        build_config(
            _request(tmp_path, worktree=str(inside), harness_root=str(harness)),
            current_installation(),
        )


def test_the_orchestrators_startup_files_are_watched_and_nothing_else_in_its_environment(
    tmp_path: Path,
) -> None:
    from physgate.hooks.settings import _startup_watch

    harness = _harness(tmp_path)
    site = harness / ".venv/lib/python3.12/site-packages"
    for rel in ("_editable.pth", "typing_extensions.py", "pkg/__init__.py", "big.so"):
        (site / rel).parent.mkdir(parents=True, exist_ok=True)
        (site / rel).write_text("x\n")
    config = build_config(
        _request(tmp_path, harness_root=str(harness), harness_site_packages=(str(site),)),
        current_installation(),
    )
    reason, watch, exceptions = _roots(config)[str(site)]
    assert (reason, watch) == (HARNESS_REASON, "revert")
    assert exceptions == _startup_watch(site)
    assert {Path(e).name for e in exceptions} == {"typing_extensions.py", "pkg", "big.so"}
    # A new startup file of any name, and an existing one, are refused before a write.
    for rel in ("zz_new.pth", "sitecustomize.py", "usercustomize.py", "x.pth"):
        assert protection(str(site / rel), str(tmp_path / "worktree"), config, writing=True)


#: The roots whose files the sentinel keeps no byte of (sealed), each as a root of its own nested
#: inside the harness checkout: what the harness's own exemption from sealing must never shadow.
SEALING = [
    pytest.param(WITHHELD_REASON, "revert", id="a withheld record"),
    pytest.param(SENTINEL_APART_REASON, "none", id="the sentinel's place apart"),
    pytest.param(WITHHELD_WHOLE_REASON, "none", id="a root withheld whole"),
]


@pytest.mark.parametrize(("reason", "watch"), SEALING)
def test_a_sealing_root_inside_the_checkout_keeps_its_own_reason_whichever_is_listed_first(
    tmp_path: Path, reason: str, watch: str
) -> None:
    # Built by hand, past the installer, which refuses such a nesting: the matcher alone must
    # hold, whatever order the roots come in.
    harness = _harness(tmp_path)
    nested = harness / "run" / "records"
    nested.mkdir(parents=True)
    (nested / "record.json").write_text("{}\n")
    config = build_config(_request(tmp_path, harness_root=str(harness)), current_installation())
    sealing = ProtectedRoot(path=str(nested), reason=reason, watch=watch, reads="denied")  # type: ignore[arg-type]
    roots = [r for r in config.protected_roots if r.path == str(harness)]
    for order in ((*roots, sealing), (sealing, *roots)):
        ordered = config.model_copy(update={"protected_roots": order})
        target = str(nested / "record.json")
        assert protection(target, str(tmp_path / "worktree"), ordered, writing=False) == reason, (
            "the harness checkout's reason shadows a sealing root nested inside it"
        )
        assert read_refused(target, ordered), (
            "the sentinel keeps the bytes of a sealed file because it lies in the harness checkout"
        )


@pytest.mark.parametrize(
    "field",
    ["withheld", "sentinel_apart", "withheld_whole", "sessions_root"],
)
def test_a_run_place_inside_the_checkout_is_refused_at_install(tmp_path: Path, field: str) -> None:
    harness = _harness(tmp_path)
    inside = str(harness / "runs" / "r1" / field)
    value: object = (inside,) if field in ("withheld", "withheld_whole") else inside
    extra: dict[str, Any] = {"own_place": str(tmp_path)} if field == "withheld_whole" else {}
    with pytest.raises(ValueError, match="inside the harness checkout"):
        build_config(
            _request(tmp_path, harness_root=str(harness), **{field: value}, **extra),
            current_installation(),
        )


def _shell_decision(config: Any, cwd: str, command: str) -> Any:  # noqa: ANN401
    from physgate.hooks import shell_paths  # noqa: PLC0415

    call = event(cwd=cwd, tool_name="Bash", tool_input={"command": command})
    return shell_paths.pre_tool_use(HookInput.model_validate(call), config)


def _layered(tmp: Path, harness: Path, *, layer: bool) -> Any:  # noqa: ANN401
    # Where the layer runs the dispatcher names the session's own temporary directory for it;
    # where it does not, a temporary directory of the session's own all the same.
    temp = str(tmp / "pg-1")
    fields = {"os_layer_temp_dir": temp} if layer else {"temp_dir": temp}
    return build_config(_request(tmp, harness_root=str(harness), **fields), current_installation())


def test_without_the_os_layer_a_command_s_read_of_the_checkout_is_refused(tmp_path: Path) -> None:
    # Nothing else stands behind the hooks there: a run recorded with the layer absent, or a
    # platform without one, has the parser and the sentinel only.
    harness = _harness(tmp_path)
    config = _layered(tmp_path, harness, layer=False)
    cwd = str(tmp_path / "worktree")
    for command in (
        f"cat {harness}/knowledge/control/skill.md",
        f"grep -r . {harness}/knowledge/control",
        f"cd {harness}/knowledge && cat control/standards.md",
    ):
        decision = _shell_decision(config, cwd, command)
        assert not decision.allow, f"without the OS layer a command reads the checkout: {command}"
        assert HARNESS_REASON in decision.reason


def test_inside_the_os_layer_a_command_s_read_of_the_checkout_is_left_to_the_layer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A session's search path names the binary's directory first, which may lie in the checkout
    # (the pinned binary installed from its lockfile does): a command that expands it names the
    # checkout without reading anything there, and must still run. Inside the layer, which denies
    # the command's reads in the checkout, the hooks leave a read to it, as before; they refuse
    # every write there.
    harness = _harness(tmp_path)
    binary_dir = harness / "tests" / "rig" / "node_modules" / ".bin"
    binary_dir.mkdir(parents=True)
    monkeypatch.setenv("PATH", f"{binary_dir}:/usr/bin:/bin")
    config = _layered(tmp_path, harness, layer=True)
    cwd = str(tmp_path / "worktree")
    for command in ("echo $PATH > modules/path.txt", f"cat {harness}/knowledge/control/skill.md"):
        decision = _shell_decision(config, cwd, command)
        assert decision.allow, (
            f"inside the layer a command naming the checkout is refused: {command}"
        )
    assert not _shell_decision(config, cwd, f"echo x > {harness}/README.md").allow


@pytest.mark.parametrize("layer", [False, True], ids=["without the layer", "inside the layer"])
def test_the_file_tools_are_refused_the_checkout_with_or_without_the_layer(
    tmp_path: Path, layer: bool
) -> None:
    harness = _harness(tmp_path)
    config = _layered(tmp_path, harness, layer=layer)
    target = str(harness / "knowledge/control/skill.md")
    assert protection(target, str(tmp_path / "worktree"), config, writing=False) == HARNESS_REASON
