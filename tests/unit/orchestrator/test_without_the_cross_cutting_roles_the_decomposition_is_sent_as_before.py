"""Without sizing or integration among a run's roles, the one call is sent exactly as before.

The plan's form grows only for a run that has the integration role, and the prompt
only for a run that has sizing or integration. A run with neither sends the
decomposition the bytes it was sent before either role was planned for: the same
prompt and the same schema the binary holds the answer to. Recorded runs, and the
experiments that compare against them, stay comparable with every run made since.

The digests below are of the prompt and the schema as the code sent them before the
two roles were planned for, with what every run has been sent since: the store's pattern
on an interface node's id in the schema, and the sentence giving that form in the
prompt; and in the prompt, the gate's quantity names, generated from its catalogue, and who
writes interface nodes; and since 03.11.2026, where the gate has a bound and what forms each of its
relations, generated from the tables and the catalogue it loads; and since the catalogue widening
of 04.11.2026, its new names and kinds. A change to either for such a run is a change to what
every ordinary run sends, and turns this red.
"""

from __future__ import annotations

import hashlib

import pytest

from physgate import roles
from physgate.orchestrator.decompose import (
    INTERFACE_WRITER_SENTENCE,
    Plan,
    bounds_sentence,
    catalogue_sentence,
    interface_writer_sentence,
    plan_model,
    plan_schema,
    prompt_for,
    relations_sentence,
)

#: The bytes pinned here are the prompt with no law in the table: a promoted law adds its
#: own paragraph, which the law prompt's tests pin against the table in this checkout.
pytestmark = pytest.mark.usefixtures("no_law_table")

BRIEF = "Build a robot."

#: The schema every run was sent before the two roles were planned for.
SCHEMA_LENGTH = 3807
SCHEMA_SHA256 = "fae5d012d4633b0f2650310ffbe62ad712a16bf7764dc7757e54aa72b21f3357"

#: The prompt for ``BRIEF`` and each set of roles, as it is sent since the catalogue widening
#: (04.11.2026): the catalogue sentence's five new names (torque_constant, motor_resistance,
#: update_rate, sensitivity_peak, gain_margin) and its four new kind labels (resistance, extent,
#: torque constant, modulus), bore_diameter moved from the lengths to the extents, and, since the
#: check round, the sentence after the groups saying what the gate reads of a name with added
#: words; every other byte as before
#: (test_the_widened_catalogue_adds_its_names_to_the_prompt_and_nothing_else); and, since
#: 12.11.2026, the one sentence on how a unit is spelt, after the words that ask for a unit
#: (test_the_decomposition_prompt_states_how_a_unit_is_spelt). Before that sentence:
#: c14dba963d6c..., ad94ba0d6bbe... and d713661a9904.... At 470b3f34,
#: before that sentence: ca0317a59ce7..., 8abeae4b5f23... and 44175ad46745...; before the
#: widening, since 03.11.2026: dd56ee830053..., eefd8ba42c14... and a0d391892072..., in this order;
#: before 03.11.2026: 748902966f06..., 95fe568607b0... and 2f9c1d0dbb40....
#: Since the law library's rows (07.11.2026), the catalogue sentence also holds their twelve names
#: and two kind labels (charge capacity, duration), and every other byte is as above
#: (test_the_law_library_s_names_reach_the_prompt_and_nothing_else). Before those rows:
#: c14dba963d6c..., ad94ba0d6bbe... and d713661a9904..., in this order. Since check 4 gained the
#: peak headroom (07.11.2026), the relations sentence holds its statement too. With the rows and the
#: peak headroom, before the sentence on how a unit is spelt: 56526c8ddda3..., f93071084230... and
#: f8040260bc86..., in this order; with the rows alone: 48f1f778de09..., 777b1e121b63... and
#: 44c5f7c626eb..., in this order.
PROMPT_SHA256 = {
    ("control", "firmware"): "9e215ce9d86e89f78f1629d5ab75c483d1b91d1def95c44fbd6a1f4dfa88cff3",
    ("electrical",): "c55157063c415fa00cd4eda9b452e8591e08132059e8b60c16520dd56b56b6e3",
    (
        "control",
        "electrical",
        "firmware",
        "mechanical",
    ): "a3a311ee147b95a9cdad1a4578369b72b8fbb8d406dec257929c9e016c2c4544",
}

#: The prompt for ``BRIEF`` and the control and firmware roles, as it was sent before.
PROMPT = (
    "Decompose the design brief below into modules, one per role that has work to do, and "
    "the interface nodes between them.\n\n"
    "Roles available: control, firmware.\n\n"
    "For each module give a short lowercase name, its role, a directory of its own under "
    "modules/ that no other module's directory contains, and a specification an implementer "
    'can work from. For each interface give one graph node of kind "interface", owned by '
    "the role that produces it, with every quantity as a value, a unit, a source and the role "
    "that wrote it. A unit is spelt as named units with small integer powers, joined by `*` "
    "and `/`, with at most one bracketed denominator, itself a product of named units, and no "
    "numbers: `V/(rad/s)` is refused, and is written `V*s/rad`. "
    "Each node's id is two or more parts joined by dots, each of lowercase "
    "letters, digits and underscores only, the first beginning with a letter, such as "
    '"pump.flow_rate".\n\n'
    # The catalogue's names, from the catalogue: a copy here would hold the test to a list the
    # catalogue no longer keeps. The digests above hold the bytes.
    f"{catalogue_sentence()}\n\n"
    # Where the gate has a bound, and what forms each relation: from what the gate loads.
    f"{bounds_sentence()}\n\n"
    f"{relations_sentence()}\n\n"
    f"{INTERFACE_WRITER_SENTENCE}\n\n"
    "Answer by calling StructuredOutput once.\n\n"
    "Brief:\nBuild a robot.\n"
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register with sizing in it, as it ships."""
    monkeypatch.setitem(roles.ROLES, roles.SIZING.name, roles.SIZING)


@pytest.mark.parametrize("run_roles", sorted(PROMPT_SHA256), ids=", ".join)
def test_the_prompt_and_schema_are_byte_identical_without_the_cross_cutting_roles(
    run_roles: tuple[str, ...], sizing_registered: None
) -> None:
    schema = plan_schema(run_roles)
    assert (len(schema), _sha(schema)) == (SCHEMA_LENGTH, SCHEMA_SHA256)
    assert _sha(prompt_for(BRIEF, run_roles)) == PROMPT_SHA256[run_roles]
    assert _sha(prompt_for(BRIEF, tuple(reversed(run_roles)))) == PROMPT_SHA256[run_roles]
    assert plan_model(run_roles) is Plan


def test_the_prompt_without_the_cross_cutting_roles_reads_word_for_word_as_before(
    sizing_registered: None,
) -> None:
    assert prompt_for(BRIEF, ["firmware", "control"]) == PROMPT


def test_with_sizing_alone_the_schema_is_as_before_and_the_prompt_gains_one_sentence(
    sizing_registered: None,
) -> None:
    # Sizing is planned as an ordinary module, so the plan's form does not change; the
    # prompt says that it has one module at most, and that the interfaces it produces
    # follow a node of its own joined to them, in place of the sentence every other run is sent.
    run_roles = ("control", "firmware", "sizing")
    schema = plan_schema(run_roles)
    assert (len(schema), _sha(schema)) == (SCHEMA_LENGTH, SCHEMA_SHA256)
    assert plan_model(run_roles) is Plan
    prompt = prompt_for(BRIEF, run_roles)
    before = PROMPT.replace("control, firmware.", "control, firmware, sizing.").replace(
        INTERFACE_WRITER_SENTENCE, interface_writer_sentence("sizing")
    )
    added = [p for p in prompt.split("\n\n") if p not in before.split("\n\n")]
    assert len(added) == 1, added
    (sentence,) = added
    assert sentence.count(". ") == 0 and sentence.endswith(".")
    assert "sizing" in sentence and "at most one module" in sentence.casefold()
    assert prompt.replace(sentence + "\n\n", "") == before


def test_without_sizing_registered_a_role_of_that_name_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Sizing is found in the register by what it owns. In a register without it, nothing owns
    # the cross nodes, so a run cannot name it (the register refuses that run before its call),
    # and the prompt has no sentence for it.
    monkeypatch.delitem(roles.ROLES, roles.SIZING.name, raising=False)
    run_roles = ("control", "firmware", "sizing")
    assert roles.owners_of("cross_nodes") == ()
    prompt = prompt_for(BRIEF, run_roles)
    assert prompt == PROMPT.replace("control, firmware.", "control, firmware, sizing.")
