"""The parts code adds no way into the evaluation, and its reader reaches no reviewer.

The product does not depend on the thesis's evaluation: evaluation may feed a part's decision
only through the one public function every decision goes through, and the parts code must not
reach back into it. Read over the source by its syntax tree, so the check needs nothing imported:

- no module the parts feature added or changed imports the evaluation package, by any spelling
  (absolute, relative, ``from physgate import evaluation``, or a module name in a string, the
  form a dynamic import takes);
- the one exception is the command line's three imports of the fault instrument's configuration
  names, which it held before the parts feature; any other import of the evaluation there fails,
  and so does the exception once those three are gone, so it cannot outlive its reason;
- the parts reader imports nothing from the reviewers, whose modules reach the evaluation.

Imports the evaluation reaches through other modules (the reviewers' text folding) are older than
this feature and are not judged here.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path
from typing import NamedTuple

import pytest

import physgate

SRC = Path(physgate.__file__).parent
EVALUATION = "physgate.evaluation"

#: Every product module the parts feature added or changed, by its path under the package. The
#: evaluation's own modules it changed (to class the switch on a run) are the evaluation.
MODULES = (
    "flags.py",
    "hooks/graph.py",
    "orchestrator/apply.py",
    "orchestrator/change_sets.py",
    "orchestrator/cli.py",
    "orchestrator/decisions.py",
    "orchestrator/decompose.py",
    "orchestrator/design_rounds.py",
    "orchestrator/dispatch.py",
    "orchestrator/dispute.py",
    "orchestrator/escalation.py",
    "orchestrator/escalation_state.py",
    "orchestrator/events.py",
    "orchestrator/loop.py",
    "orchestrator/parts.py",
    "orchestrator/parts_reading.py",
    "orchestrator/parts_write.py",
    "orchestrator/plan.py",
    "orchestrator/ports.py",
    "orchestrator/protocols.py",
    "orchestrator/queue.py",
    "orchestrator/record.py",
    "orchestrator/repair.py",
    "orchestrator/replay.py",
    "orchestrator/run_config.py",
    "reviewers/packet.py",
    "reviewers/plan_packet.py",
    "state/__init__.py",
    "state/divergence.py",
    "state/schema.py",
    "state/store.py",
    "ui/actions.py",
)

#: The command line's imports of the evaluation, held before the parts feature: each statement
#: as its module and its ``(name, alias)`` pairs.
CLI_HELD = frozenset(
    {
        ("physgate.evaluation.inject.runner", (("CONFIG_NAME", "INSTRUMENT_CONFIG_NAME"),)),
        (
            "physgate.evaluation.inject.runner",
            (("CONTROLS_DIRNAME", "INSTRUMENT_CONTROLS_DIRNAME"),),
        ),
        ("physgate.evaluation.inject.runner", (("InstrumentConfig", None),)),
    }
)

PARTS = "orchestrator/parts.py"


def _package_of(relative: str) -> list[str]:
    parts = ["physgate", *Path(relative).with_suffix("").parts]
    return parts[:-1]


def _absolute(relative: str, node: ast.ImportFrom) -> str:
    """The module an ``import from`` names, a relative one resolved against ``relative``."""
    if not node.level:
        return node.module or ""
    base = _package_of(relative)
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def _within(module: str, package: str) -> bool:
    return module == package or module.startswith(package + ".")


class Imported(NamedTuple):
    """One import: its line, the module, its ``(name, alias)`` pairs, and how it was read.

    ``as_name`` marks a name of an ``import from`` read as a module, the form
    ``from physgate import evaluation`` takes.
    """

    line: int
    module: str
    names: tuple[tuple[str, str | None], ...]
    as_name: bool


def imports_of(relative: str, source: str) -> list[Imported]:
    """Every import in ``source``, and each name of an ``import from`` as a module too."""
    found: list[Imported] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found += [Imported(node.lineno, alias.name, (), False) for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = _absolute(relative, node)
            names = tuple((alias.name, alias.asname) for alias in node.names)
            found.append(Imported(node.lineno, module, names, False))
            found += [Imported(node.lineno, f"{module}.{name}", (), True) for name, _ in names]
    return found


def evaluation_imports(relative: str, source: str) -> list[Imported]:
    """Each import of the evaluation package in ``source``, by any spelling, each statement once."""
    return [
        one
        for one in imports_of(relative, source)
        if _within(one.module, EVALUATION)
        and not (one.as_name and _within(one.module.rsplit(".", 1)[0], EVALUATION))
    ]


def named_in_strings(source: str) -> list[int]:
    """The lines of every string that names the evaluation package: a dynamic import's form."""
    return [
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _within(node.value.strip(), EVALUATION)
    ]


def violations_in(relative: str, source: str) -> list[str]:
    """Every way the module at ``relative`` with ``source`` reaches the evaluation."""
    found: list[str] = []
    held = evaluation_imports(relative, source)
    if relative == "orchestrator/cli.py":
        statements = [(one.module, one.names) for one in held if one.names]
        found += [f"{relative}:{one.line}: imports {one.module}" for one in held if not one.names]
        for module, names in statements:
            if (module, names) not in CLI_HELD:
                found.append(f"{relative}: imports {names} from {module}")
        if Counter(statements) != Counter(CLI_HELD):
            found.append(f"{relative}: the evaluation imports it may keep are not the held three")
    else:
        found += [f"{relative}:{one.line}: imports {one.module}" for one in held]
    found += [f"{relative}:{line}: names the evaluation" for line in named_in_strings(source)]
    return found


# --- the rule over the source -----------------------------------------------------------------


@pytest.mark.parametrize("relative", MODULES)
def test_no_module_the_parts_feature_changed_imports_the_evaluation(relative: str) -> None:
    path = SRC / relative
    assert path.is_file(), f"{relative} is not in the package"
    assert violations_in(relative, path.read_text()) == []


def test_the_parts_reader_imports_nothing_from_the_reviewers() -> None:
    path = SRC / PARTS
    assert path.is_file(), f"{PARTS} is not in the package"
    reached = [
        f"{one.line}: {one.module}"
        for one in imports_of(PARTS, path.read_text())
        if _within(one.module, "physgate.reviewers")
    ]
    assert reached == []


def test_every_parts_module_of_the_orchestrator_is_on_the_list() -> None:
    present = {f"orchestrator/{path.name}" for path in (SRC / "orchestrator").glob("parts*.py")}
    assert present <= set(MODULES)
    assert PARTS in present, f"{PARTS} is not in the package"


# --- the check catches what it is for ---------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "import physgate.evaluation\n",
        "import physgate.evaluation.inject.corpus as corpus\n",
        "from physgate.evaluation.observe import cli\n",
        "from physgate import evaluation\n",
        "from ..evaluation import gaps\n",
        "from .. import evaluation\n",
        "import importlib\nimportlib.import_module('physgate.evaluation.tiers')\n",
    ],
    ids=["import", "import as", "from", "from package", "relative", "relative package", "dynamic"],
)
def test_each_spelling_of_an_import_of_the_evaluation_is_caught(source: str) -> None:
    assert violations_in("orchestrator/parts.py", source) != []


@pytest.mark.parametrize(
    "source",
    [
        "from physgate.orchestrator.replay import RunState\n",
        "from .plan import MAX_COMPONENTS\n",
        "import physgate.evaluations_elsewhere\n",
        "NOTE = 'the evaluation feeds decisions'\n",
    ],
    ids=["product", "relative product", "a longer name", "prose"],
)
def test_an_import_of_the_product_is_not_caught(source: str) -> None:
    assert violations_in("orchestrator/parts.py", source) == []


def _cli_with(extra: str) -> str:
    held = (SRC / "orchestrator/cli.py").read_text()
    return held + extra


def test_the_command_line_keeps_exactly_its_three_held_imports() -> None:
    assert violations_in("orchestrator/cli.py", _cli_with("")) == []


@pytest.mark.parametrize(
    "extra",
    [
        "from physgate.evaluation.inject.runner import run_instrument\n",
        "from physgate.evaluation.inject.runner import InstrumentConfig as Other\n",
        "import physgate.evaluation.tiers\n",
        "from physgate.evaluation.inject.runner import InstrumentConfig\n",
    ],
    ids=["another name", "another alias", "another module", "a held import twice"],
)
def test_a_further_import_of_the_evaluation_in_the_command_line_is_caught(extra: str) -> None:
    assert violations_in("orchestrator/cli.py", _cli_with(extra)) != []


def test_the_command_line_s_exception_ends_once_its_held_imports_are_gone() -> None:
    source = "\n".join(
        line
        for line in (SRC / "orchestrator/cli.py").read_text().splitlines()
        if "physgate.evaluation" not in line
    )
    assert violations_in("orchestrator/cli.py", source) != []


def test_the_parts_reader_reaching_a_reviewer_is_caught() -> None:
    caught = [
        one.module
        for one in imports_of(PARTS, "from ..reviewers.places import telltales\n")
        if _within(one.module, "physgate.reviewers")
    ]
    assert caught != []
