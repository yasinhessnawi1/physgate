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
of 04.11.2026, its new names and kinds; and since 16.11.2026, the paragraph saying a plan states
interfaces and criteria, never a solution's law or coefficients; and since 18.11.2026, the
paragraph saying how one acceptance criterion is written, and the sentence in the first
paragraph saying which quantities go on an interface node. A change to either for such a run is a
change to what every ordinary run sends, and turns this red.
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
#: (test_the_decomposition_prompt_states_how_a_unit_is_spelt); and, since 16.11.2026, the
#: paragraph after the words that ask for the modules and interfaces, saying a specification
#: states interfaces and criteria and never a solution's law or coefficients
#: (test_the_plan_states_interfaces_and_criteria_never_a_solution_s_law), reworded on
#: 17.11.2026 (a test for what the brief fixes, physical properties on an interface, the
#: designer's node wherever one module implements another's design, named in both
#: specifications); and, since 18.11.2026, the paragraph after it saying each acceptance
#: criterion is one statement of one thing with its verification method named
#: (test_every_acceptance_criterion_is_one_statement_with_its_verification_method); and, since
#: 18.11.2026, the sentence in the first of those paragraphs saying a quantity is on an
#: interface node only where another module's specification reads it, and is named in each
#: reader's specification (test_an_interface_quantity_is_read_by_a_module_besides_its_producer);
#: and, since 20.11.2026, the sentence ending the criterion paragraph saying a criterion is
#: written only against what the run's environment can measure (a simulator only where it
#: provides one, where the brief connects no board), and that each specification states its
#: limits, timeouts and fault behaviour
#: (test_a_criterion_is_written_against_an_instrument_the_run_has).
#: Before the instrument sentence: 11fc062c365c..., ccd58c178193... and 591a7d65fb70....
#: Before that sentence: 6672229b67f4..., 6219833c8874... and b85194b2c03a....
#: Before the criterion paragraph: 38485dfa3eae..., c6bbc8f4ddd1... and 06b330e281cc....
#: Before the rewording: 7394c68115d3..., 044c69c7b621... and 0e879c749f64....
#: Before that paragraph: cd9d3713e8dd..., 66e80cd16451... and 6fd51bcf6f3a.... Before the unit
#: sentence:
#: c14dba963d6c..., ad94ba0d6bbe... and d713661a9904.... At 470b3f34,
#: before that sentence: ca0317a59ce7..., 8abeae4b5f23... and 44175ad46745...; before the
#: widening, since 03.11.2026: dd56ee830053..., eefd8ba42c14... and a0d391892072..., in this order;
#: before 03.11.2026: 748902966f06..., 95fe568607b0... and 2f9c1d0dbb40....
PROMPT_SHA256 = {
    ("control", "firmware"): "5ad250714df63f68716e1e35bc776bfbb2e8588a4cb0f876fb1d55e12ac279c0",
    ("electrical",): "5b92ffb708ee324bad1485199ca5bad97f8892d776ca32a565f8f704e84d01e9",
    (
        "control",
        "electrical",
        "firmware",
        "mechanical",
    ): "cd26dec5624c7d59e13aac11be5fc95e471cf56a9c2f1bb08d6fb810273a091e",
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
    "A specification states its module's interfaces and acceptance criteria, never the internal "
    "law, structure or coefficients of a solution, unless the brief fixes them. The brief fixes "
    "a method only where one of its requirements, in its own words, says the design shall use, "
    "run or contain it; a program or document the brief cites as the source of a number, a part "
    "or a condition is a source of those only. An interface node holds what both sides must "
    "agree on before either works (the signals that cross, with their units and rates; the "
    "limits both sides hold to; and the physical properties one side gives the other, such as a "
    "mass or a motor constant), never a solution's tuned parameters. A quantity goes on an "
    "interface node only where the specification of at least one module other than the one that "
    "produces it reads it by name; a quantity that only its own module uses stays in that "
    "module's specification, off every interface node; and each quantity on an interface node is "
    "named, as the node names it, in the specification of every module that reads it. "
    "Where one module implements what another designs, such as firmware running the control law "
    "that was analysed, the "
    "designing module comes before the implementing module in the plan and writes its design on "
    "a node of its own, named in both specifications; the implementing module's acceptance "
    "criteria compare its implementation with that node as merged, and where the node is not "
    "merged when it starts, it reports that and implements no design of its own.\n\n"
    'Write each acceptance criterion as one statement of one thing, in the form "The <module> '
    'shall <verb> <what>, <threshold with its unit and tolerance>, verified by <method>.", '
    "where the method is one of analysis, demonstration, inspection or test, named by that word "
    "in the criterion; a criterion that sets no figure has no threshold, and each criterion "
    "names the brief requirement it traces to or says it is derived and why. A requirement that "
    "holds several figures or conditions (a value and its agreement with another quantity, a "
    "value and a rule for the rest of the module, two margins, a figure and a setting) becomes "
    "one criterion for each, so that each is met or unmet on its own. A goal is written with "
    '"should", outside the acceptance criteria. Write each criterion only against what the '
    "run's environment can measure. No board is connected unless the brief says so; without "
    "one, behaviour on the target is checked in a simulator only where the run's environment "
    "provides one, and otherwise the criterion is written against what can be measured (that "
    "the code compiles, its size, static checks, tests of its logic on the host) and the "
    "specification states that behaviour on the target is not measured in this run. Each "
    "module's specification states, with a value or the node that will carry it, every limit, "
    "timeout and fault behaviour the module must implement.\n\n"
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
