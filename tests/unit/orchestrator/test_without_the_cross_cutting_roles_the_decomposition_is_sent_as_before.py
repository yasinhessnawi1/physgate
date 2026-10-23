"""Without sizing or integration among a run's roles, the one call is sent exactly as before.

The plan's form grows only for a run that has the integration role, and the prompt
only for a run that has sizing or integration. A run with neither sends the
decomposition the bytes it was sent before either role was planned for: the same
prompt and the same schema the binary holds the answer to. Recorded runs, and the
experiments that compare against them, stay comparable with every run made since.

The digests below are of the prompt and the schema as the code sent them before the
two roles were planned for. A change to either for such a run is a change to what
every ordinary run sends, and turns this red.
"""

from __future__ import annotations

import hashlib

import pytest

from physgate import roles
from physgate.orchestrator.decompose import Plan, plan_model, plan_schema, prompt_for

BRIEF = "Build a robot."

#: The schema every run was sent before the two roles were planned for.
SCHEMA_LENGTH = 3761
SCHEMA_SHA256 = "106e1e35f5498b1c22c2fe33d6e3c06946a33aea7f2d7f0c9c7f3fc296080ebc"

#: The prompt for ``BRIEF`` and each set of roles, as it was sent before.
PROMPT_SHA256 = {
    ("control", "firmware"): "96ae5cfd3d70b553d89800fd4407a51fca4c47c470e278b64233fca69fb5d192",
    ("electrical",): "94e8db6b95490d1824ac687a5c4e88b78c826b2fab35ce09d9674c1cffea9420",
    (
        "control",
        "electrical",
        "firmware",
        "mechanical",
    ): "0f3fa7d3342d27c3ed6d6adf01550a3fa757bc0ad6f984b3ba3fee31576c2c44",
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
    "that wrote it.\n\n"
    "Answer by calling StructuredOutput once.\n\n"
    "Brief:\nBuild a robot.\n"
)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


@pytest.fixture
def sizing_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    """The register as it will stand once sizing ships."""
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
    # prompt says only that it has one module at most.
    run_roles = ("control", "firmware", "sizing")
    schema = plan_schema(run_roles)
    assert (len(schema), _sha(schema)) == (SCHEMA_LENGTH, SCHEMA_SHA256)
    assert plan_model(run_roles) is Plan
    prompt = prompt_for(BRIEF, run_roles)
    before = PROMPT.replace("control, firmware.", "control, firmware, sizing.")
    added = [p for p in prompt.split("\n\n") if p not in before.split("\n\n")]
    assert len(added) == 1, added
    (sentence,) = added
    assert sentence.count(". ") == 0 and sentence.endswith(".")
    assert "sizing" in sentence and "at most one module" in sentence.casefold()
    assert prompt.replace(sentence + "\n\n", "") == before


def test_without_sizing_registered_a_role_of_that_name_changes_nothing() -> None:
    # Sizing is found in the register by what it owns. Until it ships, nothing owns the
    # cross nodes, so a run cannot name it (the register refuses that run before its call),
    # and the prompt has no sentence for it.
    run_roles = ("control", "firmware", "sizing")
    assert roles.owners_of("cross_nodes") == ()
    prompt = prompt_for(BRIEF, run_roles)
    assert prompt == PROMPT.replace("control, firmware.", "control, firmware, sizing.")
