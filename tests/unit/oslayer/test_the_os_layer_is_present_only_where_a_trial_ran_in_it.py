"""Whether a session's shell commands can run inside the OS layer, judged from facts.

The judgement is a pure function of what was found on the machine, so every
reason a layer can be absent is tested here without that machine. A layer is
present only where a trial command really ran inside it, on a binary version the
layer is generated for; anything else is absent, with the reason in words an
operator can act on. Nothing here refuses a run: refusing is a policy outside
this module.
"""

from __future__ import annotations

import pytest

from physgate.oslayer.probe import (
    SANDBOX_VERSIONS,
    Absent,
    PlatformFacts,
    Present,
    Trial,
    judge,
)

OK = Trial(ran=True, detail=None)


def _facts(**overrides: object) -> PlatformFacts:
    base: dict[str, object] = {
        "system": "darwin",
        "claude_version": "2.1.301",
        "sandbox_exec": OK,
        "bwrap": None,
        "socat": None,
        "bwrap_trial": None,
        "mount_namespace": None,
    }
    base.update(overrides)
    return PlatformFacts.model_validate(base)


def _linux(**overrides: object) -> PlatformFacts:
    base: dict[str, object] = {
        "system": "linux",
        "sandbox_exec": None,
        "bwrap": "/usr/bin/bwrap",
        "socat": "/usr/bin/socat",
        "bwrap_trial": OK,
        "mount_namespace": OK,
    }
    base.update(overrides)
    return _facts(**base)


def test_macos_with_a_trial_that_ran_is_present() -> None:
    assert judge(_facts()) == Present(mechanism="seatbelt", claude_version="2.1.301")


def test_linux_with_both_programs_and_a_trial_that_ran_is_present() -> None:
    assert judge(_linux()) == Present(mechanism="bubblewrap", claude_version="2.1.301")


@pytest.mark.parametrize(
    ("facts", "reason"),
    [
        (_facts(system="windows", sandbox_exec=None), "native Windows"),
        (_facts(system="other", sandbox_exec=None), "not macOS or Linux"),
        (_facts(claude_version="2.1.283"), "predates"),
        (_facts(claude_version="2.1.272"), "predates"),
        (_facts(sandbox_exec=None), "sandbox-exec is missing"),
        (_facts(sandbox_exec=Trial(ran=False, detail="denied")), "could not run a trial"),
        (_linux(bwrap=None, bwrap_trial=None), "bubblewrap (bwrap) is not on"),
        (_linux(socat=None), "socat is not on"),
        (
            _linux(bwrap_trial=Trial(ran=False, detail="bwrap: Failed to make / slave")),
            "bubblewrap could not start",
        ),
    ],
    ids=[
        "windows",
        "other-system",
        "old-pin-283",
        "old-pin-272",
        "no-sandbox-exec",
        "seatbelt-trial-failed",
        "no-bwrap",
        "no-socat",
        "bwrap-trial-failed",
    ],
)
def test_every_other_state_is_absent_with_its_reason(facts: PlatformFacts, reason: str) -> None:
    state = judge(facts)
    assert isinstance(state, Absent)
    assert reason in state.reason


def test_windows_is_named_as_no_os_protection() -> None:
    state = judge(_facts(system="windows", sandbox_exec=None))
    assert isinstance(state, Absent) and state.no_os_protection
    assert not judge(_facts(sandbox_exec=None)).no_os_protection  # type: ignore[union-attr]


def test_a_failed_trial_keeps_what_the_program_said() -> None:
    said = "bwrap: Failed to make / slave: Permission denied"
    state = judge(_linux(bwrap_trial=Trial(ran=False, detail=said)))
    assert isinstance(state, Absent) and said in state.reason


def test_without_bwrap_the_reason_says_whether_installing_it_could_help() -> None:
    refused = Trial(ran=False, detail="unshare: cannot change root filesystem propagation")
    hopeless = judge(_linux(bwrap=None, bwrap_trial=None, mount_namespace=refused))
    assert isinstance(hopeless, Absent)
    assert "mounts in a user namespace are refused here" in hopeless.reason
    hopeful = judge(_linux(bwrap=None, bwrap_trial=None, mount_namespace=OK))
    assert isinstance(hopeful, Absent) and "refused here" not in hopeful.reason


def test_the_layer_is_generated_only_for_the_versions_its_rows_were_measured_on() -> None:
    assert frozenset({"2.1.301", "2.1.322"}) == SANDBOX_VERSIONS


@pytest.mark.parametrize("version", sorted({"2.1.301", "2.1.322"}))
def test_on_each_measured_version_a_trial_that_ran_is_a_present_layer(version: str) -> None:
    mac = judge(_facts(claude_version=version))
    assert mac == Present(mechanism="seatbelt", claude_version=version)
    linux = judge(_linux(claude_version=version))
    assert linux == Present(mechanism="bubblewrap", claude_version=version)


@pytest.mark.parametrize("version", ["2.1.302", "2.1.321", "2.1.323", "2.2.0", "3.0.0"])
def test_a_later_version_no_row_was_measured_on_is_absent_and_not_called_earlier(
    version: str,
) -> None:
    for facts in (_facts(claude_version=version), _linux(claude_version=version)):
        state = judge(facts)
        assert isinstance(state, Absent)
        assert "predates" not in state.reason
        assert "not measured on" in state.reason and version in state.reason
        assert "2.1.301" in state.reason and "2.1.322" in state.reason


@pytest.mark.parametrize("version", ["", "2.1", "latest", "2.1.x", "v2.1.322", "2.1.322 "])
def test_a_version_that_is_no_three_numbers_is_absent(version: str) -> None:
    state = judge(_facts(claude_version=version))
    assert isinstance(state, Absent)


def test_a_reason_is_bounded_whatever_a_program_printed() -> None:
    long = "x" * 10_000
    state = judge(_linux(bwrap_trial=Trial(ran=False, detail=long)))
    assert isinstance(state, Absent) and len(state.reason) <= 400


def test_a_probe_that_fails_is_never_a_present_layer(monkeypatch: pytest.MonkeyPatch) -> None:
    from physgate.oslayer import probe

    def failing(**_: object) -> PlatformFacts:
        msg = "the system would not say"
        raise OSError(msg)

    monkeypatch.setattr(probe, "gather_facts", failing)
    state = probe.judge_here(claude_version="2.1.301", search_path="/usr/bin")
    assert isinstance(state, Absent) and "the probe could not run" in state.reason
