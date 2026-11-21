"""The numbers "as written" are the validated body's own terms', mapped by identity.

A mode held at 1 is set aside on exact decimals read from the answer text. The text is read twice,
once into floats (the law the loop is built from) and once into decimals; the decimals are only
useful if each belongs to the term it was written for. A number that is zero as a float and not
as a decimal (``1e-400``) is a term removed in one pass and kept in the other, and a position taken
from the second would give the next term another's number: two wheel-speed terms then read as
cancelling, the state as fed by no wheel speed, and a law that does not restore the wheels as
stable. So a number that underflows, or overflows, is refused by name wherever a number of the law
can stand; which terms are removed is decided once; and each written number is found by its line's
name and the term's own place in the text, never by position in the body that is scored.

A law whose lone zero-weight term reads a state taken out is judged as the law it is, and a held
state that is fed by a signal and read by the command is flagged by name, on the record and on
every row, so such answers are a class of their own.
"""

from __future__ import annotations

import copy
import importlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

helpers: Any = importlib.import_module("test_a_sampled_law_is_scored_as_the_named_structures_are")
scope: Any = importlib.import_module("test_a_law_s_scope_flags_and_held_modes_reach_the_score")

#: The radius the draft plant's nominal wheels have, as the gains in these laws are scaled to it.
RADIUS = 0.04
#: Said in the reason of a refusal by its name.
UNDERFLOWS = "number_underflows"
OVERFLOWS = "number_overflows"


def _m(value: object, unit: str) -> dict[str, object]:
    return {"value": value, "unit": unit}


def _reviewer_law(kz: float = 0.002, tiny: object = 0.0) -> dict[str, Any]:
    """The third review's law: a state fed twice by the wheel speed (1 and then -0.5), read.

    ``z_now = previous.z + [a term out of scope, weight ``tiny``] + 1·kv·wheel_speed
    - 0.5·kv·wheel_speed``: the state integrates half the wheel speed, so the wheels are not
    restored. The command is the good gains with a wheel-angle gain, and ``kz`` times the state.
    """
    controller = helpers._law(
        [
            *helpers._no_travel_terms(),
            {"sign": 1, "coefficients": ["distance_gain"], "of": "wheel_angle"},
            {"sign": 1, "coefficients": ["kz"], "of": "previous.z"},
        ],
        {
            **helpers._good_coefficients(RADIUS),
            "kz": _m(kz, "1"),
            "kv": _m(1.0, "s/rad"),
            "tiny": _m(tiny, "1"),
        },
        [{"name": "z", "unit": "1", "next": "z_now"}],
        [
            {
                "name": "z_now",
                "unit": "1",
                "terms": [
                    {"sign": 1, "of": "previous.z"},
                    {"sign": 1, "number": 1, "coefficients": ["tiny"], "of": "tilt*tilt_rate"},
                    {"sign": 1, "number": 1, "coefficients": ["kv"], "of": "wheel_speed"},
                    {"sign": -1, "number": 0.5, "coefficients": ["kv"], "of": "wheel_speed"},
                ],
            }
        ],
    )
    return controller  # type: ignore[no-any-return]


def _text(controller: dict[str, Any], **spellings: str) -> bytes:
    """The answer's text with each ``name=spelling`` written exactly as given.

    ``name`` is a coefficient (its ``value``), ``period`` (the controller's) or ``number``: the
    number of the third term of the line ``z_now`` (the first wheel-speed term, 1).
    """
    raw: str = helpers._answer(controller, 3).decode()
    for name, spelling in spellings.items():
        if name == "number":
            first = raw.index('"number": 1,')
            at = raw.index('"number": 1,', first + 1)
            raw = raw[:at] + f'"number": {spelling},' + raw[at + len('"number": 1,') :]
            continue
        pattern = re.compile(rf'("{name}": {{"value": )[^,]+(,)')
        raw, count = pattern.subn(rf"\g<1>{spelling}\g<2>", raw, count=1)
        assert count == 1, name
    return raw.encode()


def _record_of_text(tmp_path: Path, raw: bytes) -> dict[str, Any]:
    directory = tmp_path / f"answer_{len(list(tmp_path.iterdir()))}"
    directory.mkdir()
    scenario, root = helpers._scenario(directory, json.loads(json.dumps(helpers.SPECS)))
    path = root / "answer.json"
    path.write_bytes(raw)
    try:
        return scenario.record(path)  # type: ignore[no-any-return]
    except Exception as exc:  # noqa: BLE001 - an exception out of the scorer is the finding
        pytest.fail(f"{type(exc).__name__} escaped the scorer: {exc}")


def _rows(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {r["name"]: r for r in record["specs"]}


def _never_stable(record: dict[str, Any]) -> None:
    """Whatever else it ended as, the scorer gave this answer no stable verdict."""
    assert record["outcome"] != "pass", record
    for row in record["specs"]:
        if row["name"] in ("pm", "up"):
            assert row["verdict"] != "pass", row


# ── the third review's law ────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("kz", [0.002, 0.0005])
def test_the_reviewer_s_law_with_a_number_that_underflows_is_refused_never_stable(
    tmp_path: Path, kz: float
) -> None:
    record = _record_of_text(tmp_path, _text(_reviewer_law(kz), tiny="1e-400"))
    assert record["outcome"] == "fail"
    assert record["answer_valid"] is False
    assert UNDERFLOWS in record["reason"]
    assert "tiny" in record["reason"]
    _never_stable(record)


@pytest.mark.parametrize("kz", [0.002, 0.0005, -0.002, 0.01])
@pytest.mark.parametrize("zero", ["0.0", "0", "-0.0", "0e0", "0.0e-5", "0E+3"])
def test_the_same_law_with_its_zero_spelled_honestly_is_unstable_whatever_the_spelling(
    tmp_path: Path, kz: float, zero: str
) -> None:
    record = _record_of_text(tmp_path, _text(_reviewer_law(kz), tiny=zero))
    assert record["outcome"] == "fail"
    assert record["answer_valid"] is True
    rows = _rows(record)
    assert rows["pm"]["verdict"] == "fail"
    assert "unstable" in rows["pm"]["reason"]
    assert record["held_modes"] == []
    assert [s["term"] for s in record["set_aside"]] == [2]


def test_the_same_law_with_no_term_out_of_scope_at_all_gives_the_same_verdict(
    tmp_path: Path,
) -> None:
    with_term = _record_of_text(tmp_path, _text(_reviewer_law(0.002), tiny="0.0"))
    plain = _reviewer_law(0.002)
    terms = plain["lines"][0]["terms"]
    del terms[1]
    without = _record_of_text(tmp_path, helpers._answer(plain, 3))
    assert without["set_aside"] == []
    assert with_term["specs"] == without["specs"]
    assert with_term["outcome"] == without["outcome"] == "fail"


@pytest.mark.parametrize(
    "kwargs",
    [{"kv": "1e-400"}, {"tiny": "1e-400"}, {"number": "1e-400"}, {"period": "1e-400"}],
    ids=["coefficient", "coefficient_of_a_term_out_of_scope", "term_number", "period"],
)
def test_a_number_that_underflows_is_refused_by_name_in_every_place_a_number_can_stand(
    tmp_path: Path, kwargs: dict[str, str]
) -> None:
    record = _record_of_text(tmp_path, _text(_reviewer_law(0.002), **kwargs))
    assert record["outcome"] == "fail"
    assert record["answer_valid"] is False
    assert UNDERFLOWS in record["reason"], record["reason"]
    _never_stable(record)


@pytest.mark.parametrize(
    "kwargs",
    [{"kv": "1e999"}, {"tiny": "1e999"}, {"period": "1e999"}, {"kv": "-1e999"}],
    ids=["coefficient", "out_of_scope_coefficient", "period", "negative"],
)
def test_a_number_that_is_infinite_as_a_float_is_refused_by_name(
    tmp_path: Path, kwargs: dict[str, str]
) -> None:
    record = _record_of_text(tmp_path, _text(_reviewer_law(0.002), **kwargs))
    assert record["outcome"] == "fail"
    assert record["answer_valid"] is False
    assert OVERFLOWS in record["reason"], record["reason"]


def test_a_term_s_number_that_is_infinite_as_a_float_is_refused_by_name(tmp_path: Path) -> None:
    record = _record_of_text(tmp_path, _text(_reviewer_law(0.002), number="1e999"))
    assert record["outcome"] == "fail"
    assert OVERFLOWS in record["reason"], record["reason"]


def test_an_analysed_law_with_a_number_that_underflows_is_refused_too(tmp_path: Path) -> None:
    document = json.loads(helpers._answer(helpers._recorded_controller(), 3))
    document["analysed_controller"] = _reviewer_law(0.002)
    raw = json.dumps(document).replace('"tiny": {"value": 0.0,', '"tiny": {"value": 1e-400,')
    record = _record_of_text(tmp_path, raw.encode())
    assert record["outcome"] == "fail"
    assert UNDERFLOWS in record["reason"]


def test_a_number_that_underflows_in_a_named_structure_is_read_as_ever(tmp_path: Path) -> None:
    """Only a sampled law's own numbers are held to this: a named structure is read as ever."""
    raw = helpers._answer(helpers._feedback(), 3).decode()
    old = '"distance_gain": {"value": '
    at = raw.index(old) + len(old)
    end = raw.index(",", at)
    record = _record_of_text(tmp_path, (raw[:at] + "1e-400" + raw[end:]).encode())
    assert record["answer_valid"] is True, record.get("reason")
    assert UNDERFLOWS not in str(record.get("reason"))


# ── the honest numbers of a law with a term out of scope are what they were written as ──────


def _held_law_with_dead_term_first(dead_first: bool) -> dict[str, Any]:
    """A stable law with a state held at 1 by ``0.9`` and ``0.1`` of itself, read by the command.

    A term of weight 0 and out of scope stands first in the state's line when ``dead_first``, so
    the positions of the others in the text are not those they have in the law scored.
    """
    controller = scope._stable_with([], [{"sign": 1, "coefficients": ["kz"], "of": "previous.z"}])
    controller["coefficients"]["kz"] = helpers._m(0.01, "1/rad")
    controller["coefficients"]["pole"] = helpers._m(0.9, "1")
    controller["coefficients"]["rest"] = helpers._m(0.1, "1")
    controller["coefficients"]["off"] = helpers._m(0.0, "1")
    terms = [
        {"sign": 1, "coefficients": ["pole"], "of": "previous.z"},
        {"sign": 1, "coefficients": ["rest"], "of": "previous.z"},
    ]
    dead = {"sign": 1, "coefficients": ["off"], "of": "tilt*tilt_rate"}
    controller["lines"][0]["terms"] = [dead, *terms] if dead_first else terms
    return controller  # type: ignore[no-any-return]


def test_a_dead_term_before_the_others_changes_nothing_the_law_is_judged_on(
    tmp_path: Path,
) -> None:
    plain = _record_of_text(tmp_path, helpers._answer(_held_law_with_dead_term_first(False), 3))
    shifted = _record_of_text(tmp_path, helpers._answer(_held_law_with_dead_term_first(True), 3))
    assert plain["held_modes"] != []
    assert shifted["held_modes"] == plain["held_modes"]
    assert shifted["specs"] == plain["specs"]
    assert shifted["outcome"] == plain["outcome"]
    assert [s["line"] for s in shifted["set_aside"]] == ["z_now"]


def test_a_dead_term_before_the_others_keeps_each_number_with_its_own_term(
    tmp_path: Path,
) -> None:
    """17 digits: ``0.9`` and ``0.10000000000000001`` do not sum to 1, as the text wrote them."""
    controller = _held_law_with_dead_term_first(True)
    raw = helpers._answer(controller, 3).decode()
    old = '"rest": {"value": 0.1,'
    assert raw.count(old) == 1
    record = _record_of_text(
        tmp_path, raw.replace(old, '"rest": {"value": 0.10000000000000001,').encode()
    )
    assert record["held_modes"] == []
    assert _rows(record)["pm"]["verdict"] == "fail"


# ── a lone term of weight zero that reads a state taken out ─────────────────────────────────────


def _lone_zero_reader(lone: bool = True) -> dict[str, Any]:
    """The good law, a state ``zz`` fed by a term out of scope and weightless, and ``mm``.

    ``mm = zero·previous.zz`` is read by the command; ``zz_now`` holds only a term out of scope
    whose coefficient is 0, so nothing live reads ``zz`` and it is taken out with its line.
    ``mm`` then has nothing to read: alone in its line when ``lone``, beside a real term if not.
    """
    mm_terms: list[dict[str, Any]] = [{"sign": 1, "coefficients": ["zero"], "of": "previous.zz"}]
    if not lone:
        mm_terms.append({"sign": 1, "coefficients": ["k_mm"], "of": "tilt"})
    controller = helpers._recorded_controller()
    controller["coefficients"]["zero"] = helpers._m(0.0, "1")
    controller["coefficients"]["k_mm"] = helpers._m(0.0125, "1/rad")
    controller["coefficients"]["kk"] = helpers._m(0.3, "1")
    controller["memory"].append({"name": "zz", "unit": "1", "next": "zz_now"})
    zz_now = {
        "name": "zz_now",
        "unit": "1",
        "terms": [{"sign": 1, "coefficients": ["zero"], "of": "tilt*tilt_rate"}],
    }
    mm = {"name": "mm", "unit": "1" if lone else "1", "terms": mm_terms}
    controller["lines"] = [zz_now, mm, *controller["lines"]]
    command = next(x for x in controller["lines"] if x["name"] == "command")
    command["terms"].append({"sign": 1, "coefficients": ["kk"], "of": "line.mm"})
    return controller  # type: ignore[no-any-return]


def test_a_lone_term_of_weight_zero_reading_a_state_taken_out_is_judged_as_the_law_it_is(
    tmp_path: Path,
) -> None:
    plain = _record_of_text(tmp_path, helpers._answer(helpers._recorded_controller(), 3))
    record = _record_of_text(tmp_path, helpers._answer(_lone_zero_reader(), 3))
    assert record["answer_valid"] is True, record.get("reason")
    assert record["outcome"] == plain["outcome"]
    assert _rows(plain)["pm"]["verdict"] == "pass"
    assert [r["verdict"] for r in record["specs"]] == [r["verdict"] for r in plain["specs"]]
    assert "zz_now" in {s["line"] for s in record["set_aside"]}


def test_a_lone_term_of_weight_zero_reading_a_state_taken_out_leaves_an_unstable_law_unstable(
    tmp_path: Path,
) -> None:
    controller = _lone_zero_reader()
    controller["coefficients"]["k_theta"]["value"] = 1.0  # the wrong sign: it falls over
    record = _record_of_text(tmp_path, helpers._answer(controller, 3))
    assert record["answer_valid"] is True
    assert record["outcome"] == "fail"
    assert _rows(record)["pm"]["verdict"] == "fail"
    assert "unstable" in _rows(record)["pm"]["reason"]


def test_a_term_of_weight_zero_reading_a_state_taken_out_beside_a_real_term_is_dropped(
    tmp_path: Path,
) -> None:
    record = _record_of_text(tmp_path, helpers._answer(_lone_zero_reader(lone=False), 3))
    assert record["answer_valid"] is True, record.get("reason")
    assert _rows(record)["pm"]["verdict"] == "pass"


# ── a held state that a signal feeds and the command reads is a class of its own ──────────────

FLAG = "held_state_fed_by_reference_or_bias_and_read"


def _reading(of: str, *, reads: bool = True) -> dict[str, Any]:
    """The good law with a held state ``z`` fed by ``of`` and, if ``reads``, read by the command."""
    feed = (
        {"sign": 1, "coefficients": ["period"], "of": of}
        if of == "tilt_rate"
        else {"sign": 1, "of": of}
    )
    read = [{"sign": 1, "coefficients": ["kz"], "of": "previous.z"}] if reads else []
    controller = scope._stable_with([feed], read)
    controller["coefficients"]["kz"] = helpers._m(0.01, "1/rad")
    return controller  # type: ignore[no-any-return]


@pytest.mark.parametrize("fed_by", ["wheel_reference", "tilt_rate", "tilt"])
def test_a_held_state_the_command_reads_and_a_signal_feeds_is_flagged_by_name(
    tmp_path: Path, fed_by: str
) -> None:
    record = _record_of_text(tmp_path, helpers._answer(_reading(fed_by), 3))
    assert record["held_modes"][0]["read_by_the_command"] is True
    for holder in (record, *record["specs"]):
        assert holder.get("held_state_flags") == [FLAG], holder.get("name")


@pytest.mark.parametrize("fed_by", ["wheel_reference", "tilt_rate", "tilt"])
def test_a_held_state_nothing_reads_is_not_flagged(tmp_path: Path, fed_by: str) -> None:
    record = _record_of_text(tmp_path, helpers._answer(_reading(fed_by, reads=False), 3))
    assert record["held_modes"][0]["read_by_the_command"] is False
    for holder in (record, *record["specs"]):
        assert holder.get("held_state_flags") == []


def test_a_held_state_nothing_feeds_is_not_flagged_though_the_command_reads_it(
    tmp_path: Path,
) -> None:
    controller = scope._stable_with([], [{"sign": 1, "coefficients": ["kz"], "of": "previous.z"}])
    controller["coefficients"]["kz"] = helpers._m(0.01, "1/rad")
    record = _record_of_text(tmp_path, helpers._answer(controller, 3))
    (mode,) = record["held_modes"]
    assert mode["read_by_the_command"] is True
    assert mode["fed_by_signals"] == []
    for holder in (record, *record["specs"]):
        assert holder.get("held_state_flags") == []


def test_the_recorded_design_is_not_flagged_and_a_flagged_answer_is_not_otherwise_different(
    tmp_path: Path,
) -> None:
    recorded = _record_of_text(tmp_path, helpers._answer(helpers._recorded_controller(), 3))
    for holder in (recorded, *recorded["specs"]):
        assert holder.get("held_state_flags") == []
    flagged = _record_of_text(tmp_path, helpers._answer(_reading("wheel_reference"), 3))
    assert _rows(flagged)["pm"]["verdict"] == "pass"  # the flag is a class, not a verdict


def test_the_flag_is_not_on_an_answer_of_a_named_structure(tmp_path: Path) -> None:
    record = _record_of_text(tmp_path, helpers._answer(helpers._feedback(), 3))
    assert "held_state_flags" not in record
    assert all("held_state_flags" not in row for row in record["specs"])


def test_a_flag_the_answer_states_for_itself_is_not_taken(tmp_path: Path) -> None:
    controller = copy.deepcopy(helpers._recorded_controller())
    controller["held_state_flags"] = [FLAG]
    record = _record_of_text(tmp_path, helpers._answer(controller, 3))
    assert record["answer_valid"] is False


# ── a refusal for scope speaks for a valid answer, failing or not; a dead term is no ground ───


@pytest.mark.parametrize("weight", [1e-9, 1e-300, 5e-324, 3.0])
def test_a_valid_but_unstable_law_with_one_live_term_out_of_scope_of_any_weight_is_unscored(
    tmp_path: Path, weight: float
) -> None:
    """The docstring's truth: a law with a live term the scorer cannot take is not judged."""
    controller = scope._unstable(helpers._recorded_controller())
    plain = _record_of_text(tmp_path, helpers._answer(controller, 3))
    assert plain["outcome"] == "fail"
    controller["coefficients"]["w"] = helpers._m(weight, "1/rad")
    scope._command(controller)["terms"].append(
        {"sign": 1, "coefficients": ["w"], "of": "accelerometer_tilt"}
    )
    record = _record_of_text(tmp_path, helpers._answer(controller, 3))
    assert record["answer_valid"] is False
    assert record["refusal"]["name"] == "out_of_scope"
    assert record["outcome"] == "unscored"


def test_the_same_term_with_weight_zero_is_dead_and_the_unstable_law_is_a_fail(
    tmp_path: Path,
) -> None:
    controller = scope._unstable(helpers._recorded_controller())
    controller["coefficients"]["w"] = helpers._m(0.0, "1/rad")
    scope._command(controller)["terms"].append(
        {"sign": 1, "coefficients": ["w"], "of": "accelerometer_tilt"}
    )
    record = _record_of_text(tmp_path, helpers._answer(controller, 3))
    assert record["outcome"] == "fail"
    assert "refusal" not in record


# ── the scorer does not proceed with numbers that do not correspond to the law it scores ──────


def test_numbers_that_do_not_correspond_to_the_law_end_the_score_unscored_by_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A constructed mismatch: the numbers of every term of the text, though one was taken out."""
    from physgate.evaluation.whole import law as law_module

    real = law_module.written_from
    monkeypatch.setattr(law_module, "written_from", lambda document, origin=None: real(document))
    record = _record_of_text(tmp_path, _text(_reviewer_law(0.002), tiny="0.0"))
    assert record["answer_valid"] is True
    assert record["refusal"]["name"] == "written_numbers_do_not_match"
    assert record["outcome"] == "unscored"
    assert record["specs"] == []
    _never_stable(record)


def test_the_same_law_is_judged_when_the_numbers_correspond(tmp_path: Path) -> None:
    record = _record_of_text(tmp_path, _text(_reviewer_law(0.002), tiny="0.0"))
    assert "refusal" not in record
    assert len(record["specs"]) == len(helpers.SPECS)
