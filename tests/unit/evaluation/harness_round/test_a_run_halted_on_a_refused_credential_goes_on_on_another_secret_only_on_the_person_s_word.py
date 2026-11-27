"""A run halted on a refused credential goes on on another secret only on a person's word.

A session's credential is refused: the run halts, and the round stops waiting for a person (exit
77), spending nothing. The person replaces the credential with another secret (a token that
expired or was revoked has no other fix). Started again with no word, the command still refuses
the run on a credential that is not the one it draws on, as it always did, and the round stops on
that refusal. Started again with the round's ``credential_replaced`` word, the trial's halted run
is resumed with the command's own ``--credential-replaced``: the run's resume line records both
fingerprints and who said it, the run goes on to its end on the new secret, and the round's record
names the replacement for the trial. The word is refused where the round stands at no refused
credential, and the command refuses it for a run halted on anything else. A person may instead set
the halted run's directory aside: it is named on a ``credential`` line as the person's act, and
the trial is decomposed afresh, spending none of its one more go.

The driver holds each drive to the run's account exactly as the command does, by the command's
own functions (``round_rig.StandInDriver.secret``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import round_rig
from round_rig import SCORED, make_rig

import physgate.orchestrator.cli as orchestrator_cli
from physgate.evaluation.harness_round import RoundError, run_round
from physgate.orchestrator.credentials import Credential, fingerprint
from physgate.orchestrator.events import Halted, Resumed, read_events
from physgate.orchestrator.exceptions import RunConfigError, RunStateError
from physgate.orchestrator.run_config import (
    account_in_effect,
    load_run_config,
    require_same_account,
)

FIRST = "the-first-token"
SECOND = "the-replacement-token"


def _scorer(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _ledger(rig: round_rig.Rig) -> list[dict[str, Any]]:
    place = next((rig.made.store / "control" / "withheld" / "harness").iterdir())
    return [json.loads(x) for x in (place / "ledger.jsonl").read_text().splitlines()]


def _record(rig: round_rig.Rig) -> dict[str, Any]:
    place = next((rig.made.store / "control" / "withheld" / "harness").iterdir())
    record: dict[str, Any] = json.loads((place / "round.json").read_text())
    return record


def _print(credential: str) -> str:
    return fingerprint(Credential(mode="subscription", secret=credential))


def _halted(tmp_path: Path) -> tuple[round_rig.Rig, round_rig.StandInDriver]:
    """A round whose first session's credential was refused: it waits for a person."""
    rig = make_rig(tmp_path, account={"name": "run-seat-1", "token_sha256_prefix": _print(FIRST)})
    driver = rig.driver(refused_credential={1}, secret=FIRST)
    status, summary = run_round(
        rig.inputs(trials=1), driver=driver, scorer=_scorer, sleep=lambda _s: None
    )
    assert status == "waiting_for_a_person"
    assert summary["waiting"]["why"] == "credential_refused"
    return rig, driver


def _again(rig: round_rig.Rig, driver: round_rig.StandInDriver, **words: Any) -> Any:  # noqa: ANN401
    return run_round(
        rig.inputs(trials=1),
        driver=driver,
        scorer=_scorer,
        resume=True,
        sleep=lambda _s: None,
        **words,
    )


def test_another_secret_without_the_word_is_refused_as_it_always_was(tmp_path: Path) -> None:
    rig, driver = _halted(tmp_path)
    driver.secret = SECOND
    with pytest.raises(RoundError) as raised:
        _again(rig, driver)
    assert raised.value.context["refused_because"] == "resume_refused"


def test_another_secret_with_the_word_goes_on_and_both_fingerprints_are_recorded(
    tmp_path: Path,
) -> None:
    rig, driver = _halted(tmp_path)
    driver.secret = SECOND
    status, _summary = _again(rig, driver, credential_replaced=True)
    assert status == "done"
    (assembled,) = [x for x in _ledger(rig) if x["kind"] == "assembled"]
    assert assembled["outcome"] == "pass" and assembled["harness_total"] is not None
    run_dir = Path(assembled["run_dir"])
    events = read_events(run_dir / "events.jsonl")
    (word,) = [e.credential_replaced for e in events if isinstance(e, Resumed)]
    assert word is not None
    assert (word.was, word.now) == (_print(FIRST), _print(SECOND))
    assert word.by
    # From that line on the run draws on the new secret: a later resume on it needs no word.
    config = load_run_config(run_dir / "run.json")
    assert account_in_effect(config, events) == _print(SECOND)
    require_same_account(
        config, Credential(mode="subscription", secret=SECOND), in_effect=_print(SECOND)
    )
    (trial,) = _record(rig)["trials"]
    assert trial["credential_replaced"] == [word.model_dump(mode="json")]


def test_the_same_secret_put_right_goes_on_with_no_word_and_records_no_replacement(
    tmp_path: Path,
) -> None:
    rig, driver = _halted(tmp_path)
    status, _summary = _again(rig, driver)
    assert status == "done"
    (trial,) = _record(rig)["trials"]
    assert trial["credential_replaced"] == []


def test_the_word_for_a_round_that_stands_at_no_refused_credential_is_refused(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver(limited={1})
    status, _summary = run_round(
        rig.inputs(trials=1), driver=driver, scorer=_scorer, sleep=lambda _s: None
    )
    assert status == "waiting_for_limit"
    with pytest.raises(RoundError) as raised:
        _again(rig, driver, credential_replaced=True)
    assert raised.value.context["refused_because"] == "credential_replaced_not_waiting"
    with pytest.raises(RoundError) as fresh:
        run_round(
            rig.inputs(trials=1, out=tmp_path / "fresh"),
            driver=driver,
            scorer=_scorer,
            credential_replaced=True,
        )
    assert fresh.value.context["refused_because"] == "credential_replaced_not_waiting"


def test_the_command_refuses_the_word_for_a_run_halted_on_anything_else(tmp_path: Path) -> None:
    rig = make_rig(tmp_path, account={"name": "run-seat-1", "token_sha256_prefix": _print(FIRST)})
    driver = rig.driver(limited={1}, secret=FIRST)
    run_round(rig.inputs(trials=1), driver=driver, scorer=_scorer, sleep=lambda _s: None)
    (placed,) = [x for x in _ledger(rig) if x["kind"] == "placed"]
    run_dir = Path(placed["run_dir"])
    halts = [e.reason for e in read_events(run_dir / "events.jsonl") if isinstance(e, Halted)]
    assert halts == ["usage_limit"]
    config = load_run_config(run_dir / "run.json")
    other = Credential(mode="subscription", secret=SECOND)
    with pytest.raises(RunStateError):
        orchestrator_cli._credential_replaced(run_dir, config, other, word=True)
    # Without the word, another secret is refused as it always was.
    assert orchestrator_cli._credential_replaced(run_dir, config, other, word=False) is None
    with pytest.raises(RunConfigError):
        require_same_account(config, other, in_effect=account_in_effect(config, []))


def test_a_person_may_set_the_halted_run_aside_and_the_trial_is_decomposed_afresh(
    tmp_path: Path,
) -> None:
    rig, driver = _halted(tmp_path)
    # The fresh decomposition records the secret it is made on, as the command's does; the
    # stand-in's records the parameters' fingerprint, so its drives are not held to it here.
    driver.secret = None
    status, _summary = _again(rig, driver, set_aside=0)
    assert status == "done"
    lines = _ledger(rig)
    (closed,) = [x for x in lines if x["kind"] == "credential"]
    assert (closed["attempt"], closed["by"], closed["from_run"]) == (1, "operator", True)
    assert not [x for x in lines if x["kind"] == "superseded"], "no attempt is spent"
    (assembled,) = [x for x in lines if x["kind"] == "assembled"]
    assert assembled["attempt"] == 2 and assembled["outcome"] == "pass"
    record = _record(rig)
    assert [x["by"] for x in record["credential_refused"]] == ["operator"]
