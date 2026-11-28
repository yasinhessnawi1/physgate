"""A run halted on a refused credential is set aside only after its resume was refused, and once.

A session's credential is refused: the run halts and the round waits for a person. The person
replaces the credential and the round resumes the run on it. Only where the command refuses that
resume, given with the person's word that the credential was replaced, may the person set the run's
directory aside for a fresh draw of the plan: so no person chooses between a resume and a fresh
plan by how the run was going. Each refused resume of such a run writes a line on the round's
ledger (which run, with the word or not, the command's status and words, when), and the
set-aside's own line names the one it rests on. A resume that was taken is no refused one, though
the run then halted on a refused credential again; a refused resume without the word opens
nothing. A resume refused while the run's secret was not set in the environment opens nothing
either, so nobody reaches a fresh plan by unsetting a variable: each refused resume's line says
whether the secret was there, and a line that does not say so (written before lines said it)
counts for nothing. A trial has at most one such set-aside across its draws. A restart that names
a trial whose run stands at the limit, or mid-way, sets nothing aside.

The environment is the one the command reads its secret from: each row starts with neither
secret variable set, and a row that tries a resume with the secret there sets a stand-in.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import round_rig
from round_rig import SCORED, Killed, make_rig

from physgate.evaluation.harness_round import RoundError, run_round
from physgate.orchestrator.credentials import SECRET_VARIABLE, Credential, fingerprint

FIRST = "the-first-token"
SECOND = "the-replacement-token"


@pytest.fixture(autouse=True)
def _no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in SECRET_VARIABLE.values():
        monkeypatch.delenv(variable, raising=False)


def _secret_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(SECRET_VARIABLE["subscription"], SECOND)


def _scorer(_task: Any, _answer: Path) -> dict[str, Any]:  # noqa: ANN401
    return dict(SCORED)


def _ledger(rig: round_rig.Rig) -> list[dict[str, Any]]:
    place = next((rig.made.store / "control" / "withheld" / "harness").iterdir())
    return [json.loads(x) for x in (place / "ledger.jsonl").read_text().splitlines()]


def _kinds(rig: round_rig.Rig) -> list[str]:
    return [x["kind"] for x in _ledger(rig)]


def _print(credential: str) -> str:
    return fingerprint(Credential(mode="subscription", secret=credential))


def _halted(
    tmp_path: Path, refused: set[int] | None = None
) -> tuple[round_rig.Rig, round_rig.StandInDriver]:
    """A round whose first session's credential was refused: it waits for a person."""
    rig = make_rig(tmp_path, account={"name": "run-seat-1", "token_sha256_prefix": _print(FIRST)})
    driver = rig.driver(refused_credential=refused or {1}, secret=FIRST)
    status, summary = run_round(
        rig.inputs(trials=1), driver=driver, scorer=_scorer, sleep=lambda _s: None
    )
    assert (status, summary["waiting"]["why"]) == ("waiting_for_a_person", "credential_refused")
    return rig, driver


def _again(rig: round_rig.Rig, driver: round_rig.StandInDriver, **words: Any) -> Any:  # noqa: ANN401
    try:
        return run_round(
            rig.inputs(trials=1),
            driver=driver,
            scorer=_scorer,
            resume=True,
            sleep=lambda _s: None,
            **words,
        )[0]
    except RoundError as exc:
        return "refused:" + str(exc.context.get("refused_because"))


def _refused_resume(rig: round_rig.Rig, driver: round_rig.StandInDriver, **words: Any) -> None:  # noqa: ANN401
    """The round's resume of the halted run, refused by the command."""
    driver.refused_drives = {len(driver.drives) + 1}
    assert _again(rig, driver, **words) == "refused:resume_refused"


def test_a_set_aside_with_no_resume_tried_is_refused_and_writes_nothing(tmp_path: Path) -> None:
    rig, driver = _halted(tmp_path)
    before = _ledger(rig)
    assert _again(rig, driver, set_aside=0) == "refused:set_aside_without_a_refused_resume"
    assert _ledger(rig) == before
    assert len(driver.decomposed) == 1, "no fresh draw of the plan"


def test_a_refused_resume_writes_its_line_and_without_the_word_opens_no_set_aside(
    tmp_path: Path,
) -> None:
    rig, driver = _halted(tmp_path)
    driver.secret = SECOND  # another secret and no word: the command refuses, as it always did
    driver.refused_drives = set()
    assert _again(rig, driver) == "refused:resume_refused"
    (line,) = [x for x in _ledger(rig) if x["kind"] == "resume_refused"]
    assert (line["attempt"], line["credential_replaced"], line["status"]) == (1, False, 2)
    assert line["why"], "the command's own words"
    assert _again(rig, driver, set_aside=0) == "refused:set_aside_without_a_refused_resume"


def test_a_resume_taken_on_the_replaced_credential_is_no_refused_one_though_it_halts_again(
    tmp_path: Path,
) -> None:
    rig, driver = _halted(tmp_path, refused={1, 2})
    driver.secret = SECOND
    status = _again(rig, driver, credential_replaced=True)
    assert status == "waiting_for_a_person"
    assert "resume_refused" not in _kinds(rig)
    assert _again(rig, driver, set_aside=0) == "refused:set_aside_without_a_refused_resume"


def test_a_trial_has_one_set_aside_on_a_refused_credential_across_its_draws(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, driver = _halted(tmp_path)
    _secret_set(monkeypatch)
    _refused_resume(rig, driver, credential_replaced=True)
    driver.secret = None  # the fresh draw records the parameters' fingerprint (see the rig)
    driver.refused_credential.add(2)  # the fresh draw's session meets a refused credential too
    assert _again(rig, driver, set_aside=0) == "waiting_for_a_person"
    assert [x["attempt"] for x in _ledger(rig) if x["kind"] == "credential"] == [1]
    _refused_resume(rig, driver, credential_replaced=True)
    assert [x["attempt"] for x in _ledger(rig) if x["kind"] == "resume_refused"] == [1, 2]
    before = _ledger(rig)
    assert _again(rig, driver, set_aside=0) == "refused:set_aside_spent"
    assert _ledger(rig) == before
    assert len(driver.decomposed) == 2, "no third draw of the plan"


def test_a_resume_refused_while_the_run_s_secret_was_not_set_opens_no_set_aside(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, driver = _halted(tmp_path)
    # The secret's variable unset, the resume with the word: the command refuses it.
    _refused_resume(rig, driver, credential_replaced=True)
    (line,) = [x for x in _ledger(rig) if x["kind"] == "resume_refused"]
    assert (line["credential_replaced"], line.get("secret_present")) == (True, False)
    # The secret put back: that refusal still opens nothing, and nothing is written.
    _secret_set(monkeypatch)
    before = _ledger(rig)
    assert _again(rig, driver, set_aside=0) == "refused:set_aside_without_a_refused_resume"
    assert _ledger(rig) == before
    assert len(driver.decomposed) == 1, "no fresh draw of the plan"
    # A resume with the word refused while the secret is there is one the set-aside rests on.
    _refused_resume(rig, driver, credential_replaced=True)
    lines = [x for x in _ledger(rig) if x["kind"] == "resume_refused"]
    assert [x.get("secret_present") for x in lines] == [False, True]
    driver.secret = None  # the fresh draw records the parameters' fingerprint (see the rig)
    assert _again(rig, driver, set_aside=0) == "done"
    (closed,) = [x for x in _ledger(rig) if x["kind"] == "credential"]
    assert closed["after_refused_resume"].get("secret_present") is True
    assert closed["after_refused_resume"]["at"] == lines[1]["at"]


def test_a_refused_resume_s_line_that_does_not_say_whether_the_secret_was_set_opens_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig, driver = _halted(tmp_path)
    _secret_set(monkeypatch)
    _refused_resume(rig, driver, credential_replaced=True)
    # The line as it was written before lines said whether the secret was there.
    place = next((rig.made.store / "control" / "withheld" / "harness").iterdir())
    ledger = place / "ledger.jsonl"
    lines = [json.loads(x) for x in ledger.read_text().splitlines()]
    for x in lines:
        if x["kind"] == "resume_refused":
            x.pop("secret_present", None)
    ledger.write_text("".join(json.dumps(x, sort_keys=True) + "\n" for x in lines))
    try:
        run_round(
            rig.inputs(trials=1),
            driver=driver,
            scorer=_scorer,
            resume=True,
            sleep=lambda _s: None,
            set_aside=0,
        )
    except RoundError as exc:
        refused: object = exc
    else:
        refused = None
    assert isinstance(refused, RoundError), refused
    assert refused.context["refused_because"] == "set_aside_without_a_refused_resume"
    assert "again" in str(refused), "the refusal says to run the resume again"
    assert len(driver.decomposed) == 1, "no fresh draw of the plan"


def test_a_restart_naming_a_trial_whose_run_stands_at_the_limit_sets_nothing_aside(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver(limited={1})
    status, _summary = run_round(
        rig.inputs(trials=1), driver=driver, scorer=_scorer, sleep=lambda _s: None
    )
    assert status == "waiting_for_limit"
    before = _ledger(rig)
    assert _again(rig, driver, set_aside=0) == "refused:set_aside_not_waiting"
    assert _ledger(rig) == before


def test_a_restart_naming_a_trial_whose_run_stands_mid_way_sets_nothing_aside(
    tmp_path: Path,
) -> None:
    rig = make_rig(tmp_path)
    driver = rig.driver(killed_in_drive={1})
    with pytest.raises(Killed):
        run_round(rig.inputs(trials=1), driver=driver, scorer=_scorer, sleep=lambda _s: None)
    before = _ledger(rig)
    assert _again(rig, driver, set_aside=0) == "refused:set_aside_not_waiting"
    assert _ledger(rig) == before
