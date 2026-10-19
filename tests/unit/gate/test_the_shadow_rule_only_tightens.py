"""The short-word clause only adds to what the write-time rule refused: nothing refused is written.

The rule as it stood (a name shadows a relation's quantity when its flat spelling is within
one insertion or deletion of the quantity's for a name of five characters or fewer, two for
a longer one) is written again here, independently, as the reference. The rule now adds one
clause, for a short quantity (``mass``) only: within one edit by Levenshtein. Over a corpus
of every catalogued name, the practice vocabulary's uncatalogued names, the names the delta
review probed and ten thousand seeded near-spellings of the catalogue's names:

- every name the reference refuses, the rule refuses (no refusal lost);
- for a name longer than five characters, the rule and the reference agree exactly (the
  bound and the metric are unchanged there);
- every addition is a name of five characters or fewer one edit from ``mass``;
- both spellings of the rule give identical pairs.
"""

from __future__ import annotations

import random

import pytest

from physgate.gate.catalogue import QUANTITIES, RELATION_NAMES, shadowing_names
from physgate.state.vocabulary import shadowing_quantity_names

PRACTICE_VOCABULARY = (
    "board_length",
    "board_thickness",
    "board_width",
    "charge_capacity",
    "clock_frequency",
    "counts_per_motor_revolution",
    "counts_per_wheel_revolution",
    "logic_voltage",
    "mass_without_battery",
    "max_duty_cycle",
    "max_input_voltage",
    "max_supply_voltage",
    "motor_current_draw",
    "motor_power_draw",
    "motor_voltage_limit",
    "no_load_current",
    "overall_height",
    "track_width",
    "wheel_diameter",
)
PROBED = (
    "breakdown_voltage",
    "clamping_voltage",
    "mains_voltage",
    "soldering_temperature",
    "color_temperature",
    "delta_temperature",
    "max_supply_voltage_drop",
    "wheel_diameter_tolerance",
    "pulse_width",
    "pulse_length",
    "servo_position",
    "encoder_position",
    "throttle_position",
    "word_length",
    "bandwidth",
    "line_height",
    "eddy_current",
    "counter_current",
    "spring_force",
    "braking_torque",
    "boost_voltage",
    "motor_current",
    "pack_mass",
    "discharge_power",
    "mount_moment",
    "idle_current",
    "max",
    "mask",
    "mess",
    "moss",
    "mas",
    "maas",
    "masss",
    "dry_mass",
    "stall_currnt",
    "currentlimit",
    "supported_mas",
    "supportedmass",
    "logic_votage",
    "zeta",
    "alpha_q",
    "motor_voltage_maximum",
    "battery_voltage",
    "coil_voltage",
    "pack_mass_fraction",
    "rated_voltage_ratio",
    "stall_current_limit",
    "current_limit_margin",
    "voltage_divider_ratio",
    "loop_rate",
    "specific_power",
    "reduction_ratio",
    "winding_resistance",
    "stored_energy",
    "masskg",
    "amasss",
    "massss",
    "m",
    "ma",
    "mass_kg",
)
LETTERS = "abcdefghijklmnopqrstuvwxyz"


def _lcs(a: str, b: str) -> int:
    rows = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i, ca in enumerate(a, 1):
        for j, cb in enumerate(b, 1):
            rows[i][j] = rows[i - 1][j - 1] + 1 if ca == cb else max(rows[i - 1][j], rows[i][j - 1])
    return rows[-1][-1]


def reference_refused(name: str) -> bool:
    """The rule as it stood before the short-word clause, written again on its own."""
    if name in QUANTITIES:
        return False
    flat = name.replace("_", "")
    bound = 1 if len(flat) <= 5 else 2
    for quantity in RELATION_NAMES:
        q = quantity.replace("_", "")
        if abs(len(flat) - len(q)) <= bound and len(flat) + len(q) - 2 * _lcs(flat, q) <= bound:
            return True
    return False


def near_spellings(count: int, seed: int = 11) -> list[str]:
    """``count`` seeded misspellings of the catalogue's and the relations' names, and noise."""
    rng = random.Random(seed)
    bases = sorted(set(QUANTITIES) | set(RELATION_NAMES))
    out: list[str] = []
    while len(out) < count:
        if rng.random() < 0.1:
            out.append("".join(rng.choice(LETTERS) for _ in range(rng.randint(1, 8))))
            continue
        word = list(rng.choice(bases))
        for _ in range(rng.randint(1, 3)):
            k = rng.randrange(len(word)) if word else 0
            move = rng.choice(("insert", "delete", "substitute", "swap", "underscore"))
            if move == "insert":
                word.insert(k, rng.choice(LETTERS))
            elif move == "delete" and word:
                del word[k]
            elif move == "substitute" and word:
                word[k] = rng.choice(LETTERS)
            elif move == "swap" and len(word) > 1 and k + 1 < len(word):
                word[k], word[k + 1] = word[k + 1], word[k]
            elif move == "underscore":
                word = [c for c in word if c != "_"] if "_" in word else [*word[:k], "_", *word[k:]]
        if word:
            out.append("".join(word))
    return out


Corpus = tuple[list[str], dict[str, str], set[str]]


@pytest.fixture(scope="module")
def judged() -> Corpus:
    """(the corpus, the pairs the rule gives, the names the reference refuses)."""
    generated = near_spellings(10_000)
    assert len(generated) == 10_000
    names = sorted(set(QUANTITIES) | set(PRACTICE_VOCABULARY) | set(PROBED) | set(generated))
    return names, dict(shadowing_names(names)), {n for n in names if reference_refused(n)}


def test_the_corpus_is_what_the_docstring_says(judged: Corpus) -> None:
    names, _, refused = judged
    assert len(names) > 8_000 and set(QUANTITIES) <= set(names) and "mess" in names
    assert len(refused) > 100, "the reference refuses enough of the corpus to mean something"


def test_no_name_the_rule_refused_is_written_now(judged: Corpus) -> None:
    names, now, refused = judged
    lost = [n for n in names if n in refused and n not in now]
    assert lost == []


def test_for_a_name_longer_than_five_characters_the_rule_is_unchanged(judged: Corpus) -> None:
    names, now, refused = judged
    changed = [n for n in names if len(n.replace("_", "")) > 5 and (n in refused) != (n in now)]
    assert changed == []


def test_every_addition_is_a_short_name_one_edit_from_mass(judged: Corpus) -> None:
    names, now, refused = judged
    added = sorted(n for n in names if n in now and n not in refused)
    assert added, "the short-word clause reaches the corpus"
    for name in added:
        flat = name.replace("_", "")
        assert len(flat) <= 5 and now[name] == "mass", name
        # One substitution, insertion or deletion from "mass".
        assert len(flat) in (3, 4, 5)
        assert sum(1 for a, b in zip(flat, "mass", strict=False) if a != b) <= 1 + abs(
            len(flat) - 4
        )
    assert {"mess", "moss", "mask"} <= set(added)
    assert all(n not in now for n in ("max", "dry_mass", "mass_without_battery"))


def test_both_spellings_give_identical_pairs_over_the_corpus(judged: Corpus) -> None:
    names, now, _ = judged
    assert tuple(now.items()) == shadowing_quantity_names(names)
