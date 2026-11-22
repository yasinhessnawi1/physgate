"""The exact count is made on the rest subspace: where the command stays zero at every update.

With the plant at rest and the command zero the plant stays at rest, so the state that matters is
the wheel angle ``beta`` (the travel, kept as it is) and the law's memory ``m``; one update is
``beta' = beta``, ``m' = B_w beta + A m`` and the command ``D_w beta + C m``. The rest subspace is
the largest part of that state on which the command is zero at every update, found exactly. On it
the eigenvalue 1 is counted by its algebraic multiplicity (a chain counts every link), and set
against the number of modes the set-aside rule sets aside; an eigenvalue of exactly -1 there is
counted too. The rows below fix the definition on laws whose counts are known by hand, and compare
it with an independent computation (the largest invariant subspace inside the command's kernel,
reached by iteration) on random small laws.
"""

from __future__ import annotations

import importlib
import random
from fractions import Fraction
from typing import Any

import pytest

modes: Any = importlib.import_module(
    "test_a_mode_is_set_aside_only_where_the_wheels_return_and_on_the_numbers_as_written"
)
_term = modes._term
_state = modes._state
HOLD = modes.HOLD


def _circle(
    memory: list[tuple[str, str]],
    lines: list[dict[str, Any]],
    command: list[Any],
    values: dict[str, float],
) -> Any:
    return modes._law().unit_circle(modes._body(memory, lines, command), values, period=0.01)


def _counts(circle: Any) -> tuple[int, int, int, int]:
    return circle.at_one, circle.algebraic_at_one, circle.set_aside, circle.at_minus_one


# ── known by hand ──


def test_the_reviewer_s_three_states_are_a_multiplicity_of_two_against_one_set_aside() -> None:
    """``u0' = 0.9 u0 + 0.1 u1 + k tilt``, ``u1' = 0.9 u1 + 0.1 u0``, ``v' = v + u0``: unread."""
    memory = [("u0", "u0_now"), ("u1", "u1_now"), ("v", "v_now")]
    lines = [
        _state("u0", _term("previous.u0", "a"), _term("previous.u1", "b"), _term("tilt", "k")),
        _state("u1", _term("previous.u1", "a"), _term("previous.u0", "b")),
        _state("v", _term("previous.v"), _term("previous.u0")),
    ]
    circle = _circle(memory, lines, HOLD, {"g": 0.3, "a": 0.9, "b": 0.1, "k": 100000.0})
    assert _counts(circle) == (1, 2, 1, 0)
    assert circle.unstable
    assert "multiplicity 2" in circle.reason()
    assert circle.as_record() == {
        "at_one_not_set_aside": 1,
        "algebraic_at_one": 2,
        "set_aside": 1,
        "at_minus_one": 0,
    }


@pytest.mark.parametrize("chain", [1, 2, 3])
def test_a_chain_of_integrators_counts_every_link_not_only_its_eigenvector(chain: int) -> None:
    """The geometric multiplicity is 1 whatever the length; the algebraic one is the length + 1."""
    memory = [("h", "h_now")] + [(f"c{i}", f"c{i}_now") for i in range(chain)]
    lines = [_state("h", _term("previous.h"), _term("tilt", "k"))]
    for i in range(chain):
        behind = "h" if i == 0 else f"c{i - 1}"
        lines.append(_state(f"c{i}", _term(f"previous.c{i}"), _term(f"previous.{behind}")))
    circle = _circle(memory, lines, HOLD, {"g": 0.3, "k": 2.0})
    assert _counts(circle) == (chain, chain + 1, 1, 0)
    assert circle.unstable


def test_a_head_set_aside_with_nothing_behind_it_is_no_count() -> None:
    memory = [("h", "h_now")]
    lines = [_state("h", _term("previous.h"), _term("tilt", "k"))]
    circle = _circle(memory, lines, HOLD, {"g": 0.3, "k": 2.0})
    assert _counts(circle) == (0, 1, 1, 0)
    assert not circle.unstable


def test_two_independent_set_aside_heads_are_a_multiplicity_of_two_and_two_set_aside() -> None:
    memory = [("h1", "h1_now"), ("h2", "h2_now")]
    lines = [
        _state("h1", _term("previous.h1"), _term("tilt", "k")),
        _state("h2", _term("previous.h2"), _term("tilt_rate", "k")),
    ]
    circle = _circle(memory, lines, HOLD, {"g": 0.3, "k": 2.0})
    assert _counts(circle) == (0, 2, 2, 0)


def test_a_state_integrating_the_wheel_angle_directly_is_a_count() -> None:
    memory = [("v", "v_now")]
    lines = [_state("v", _term("previous.v"), _term("wheel_angle", "w"))]
    circle = _circle(memory, lines, HOLD, {"g": 0.3, "w": 1.0})
    assert circle.at_one == 1
    assert circle.unstable


def test_a_chain_at_exactly_minus_one_counts_once_at_minus_one() -> None:
    memory = [("z1", "z1_now"), ("z2", "z2_now")]
    lines = [
        _state("z1", _term("previous.z1", "m")),
        _state("z2", _term("previous.z2", "m"), _term("previous.z1")),
    ]
    circle = _circle(memory, lines, HOLD, {"g": 0.3, "m": -1.0})
    assert (circle.at_one, circle.at_minus_one) == (0, 1)
    assert circle.unstable


def test_the_rest_subspace_is_the_invariant_part_of_the_command_s_kernel_not_the_kernel() -> None:
    """``x1' = x1 + x2``, ``x2' = x2``, the command reads ``x1`` and the wheel angle.

    The command is zero on a plane of states, but only the line with ``x2 = 0`` stays there
    (``x2`` drifts ``x1`` off the plane at the next update): the rest subspace is that line, the
    multiplicity of 1 on it is 1, and the one mode is set aside. Taking the whole plane would
    count a chain that the command's own reading takes out of the rest subspace.
    """
    memory = [("x1", "x1_now"), ("x2", "x2_now")]
    lines = [
        _state("x1", _term("previous.x1"), _term("previous.x2")),
        _state("x2", _term("previous.x2")),
    ]
    command = [*HOLD, _term("previous.x1", "c")]
    circle = _circle(memory, lines, command, {"g": 0.3, "c": 0.5})
    assert _counts(circle) == (0, 1, 1, 0)


def test_a_law_with_no_memory_that_reads_no_wheel_angle_is_the_travel_alone_at_one() -> None:
    circle = _circle([], [], [_term("tilt", "g")], {"g": 0.3})
    assert _counts(circle) == (1, 1, 0, 0)


# ── an independent computation: the largest invariant subspace inside the command's kernel ──


def _rref(rows: list[list[Fraction]]) -> tuple[list[list[Fraction]], list[int]]:
    work = [list(r) for r in rows]
    pivots: list[int] = []
    top = 0
    for col in range(len(work[0]) if work else 0):
        pick = next((r for r in range(top, len(work)) if work[r][col] != 0), None)
        if pick is None:
            continue
        work[top], work[pick] = work[pick], work[top]
        work[top] = [x / work[top][col] for x in work[top]]
        for r in range(len(work)):
            if r != top and work[r][col] != 0:
                work[r] = [a - work[r][col] * b for a, b in zip(work[r], work[top], strict=True)]
        pivots.append(col)
        top += 1
    return work, pivots


def _kernel(rows: list[list[Fraction]], width: int) -> list[list[Fraction]]:
    if not rows:
        return [[Fraction(int(i == j)) for j in range(width)] for i in range(width)]
    work, pivots = _rref(rows)
    out = []
    for free in (c for c in range(width) if c not in pivots):
        vector = [Fraction(0)] * width
        vector[free] = Fraction(1)
        for r, col in enumerate(pivots):
            vector[col] = -work[r][free]
        out.append(vector)
    return out


def _apply(matrix: list[list[Fraction]], vector: list[Fraction]) -> list[Fraction]:
    return [sum((a * b for a, b in zip(row, vector, strict=True)), Fraction(0)) for row in matrix]


def _oracle(update: list[list[Fraction]], command: list[Fraction]) -> tuple[int, int]:
    """(multiplicity of 1, count at -1) on the largest invariant part of the command's kernel."""
    size = len(update)
    space = _kernel([command], size)
    while True:
        # the vectors of ``space`` whose image stays in ``space``: no component off it
        if not space:
            return 0, 0
        off = _kernel([list(col) for col in space], size)  # w with w . b = 0 for each basis b
        conditions = [
            [sum((w[i] * _apply(update, b)[i] for i in range(size)), Fraction(0)) for b in space]
            for w in off
        ]
        coefficients = _kernel(conditions, len(space)) if conditions else _kernel([], len(space))
        smaller = [
            [sum((c[j] * space[j][i] for j in range(len(space))), Fraction(0)) for i in range(size)]
            for c in coefficients
        ]
        if len(smaller) == len(space):
            break
        space = smaller
    d = len(space)

    def nullity(shift: int, power: int) -> int:
        images = []
        for vector in space:
            image = list(vector)
            for _ in range(power):
                moved = _apply(update, image)
                image = [moved[i] + shift * image[i] for i in range(size)]
            images.append(image)
        _, pivots = _rref(images)
        return d - len(pivots)

    return nullity(-1, d), nullity(1, 1)


def _random_law(rng: random.Random) -> tuple[Any, list[Any], dict[str, float], Any, Any]:
    n = rng.choice([1, 2, 2, 3])
    values: dict[str, float] = {"g": rng.choice([0.0, 0.3, -0.5])}
    memory = [(f"s{i}", f"s{i}_now") for i in range(n)]
    lines = []
    for i in range(n):
        terms = []
        for j in range(n):
            pick = rng.choice([0, 0, 1, 1, -1, 0.5, 0.9, 0.1])
            if pick != 0:
                values[f"a{i}{j}"] = float(pick)
                terms.append(_term(f"previous.s{j}", f"a{i}{j}"))
        for sig in ("tilt", "wheel_angle"):
            if rng.random() < 0.3:
                values[f"b{i}{sig}"] = 1.0
                terms.append(_term(sig, f"b{i}{sig}"))
        if not terms:
            terms.append(_term("tilt", "off"))
            values["off"] = 0.0
        lines.append(_state(f"s{i}", *terms))
    command = []
    if values["g"] != 0.0:
        command.append(_term("wheel_angle", "g"))
    for j in range(n):
        if rng.random() < 0.35:
            values[f"c{j}"] = rng.choice([1.0, -1.0, 0.5])
            command.append(_term(f"previous.s{j}", f"c{j}"))
    if not command:
        values["g"] = 0.0
        command.append(_term("tilt", "g"))
    return memory, lines, values, command, n


def _exact_matrices(
    body: Any, values: dict[str, float]
) -> tuple[list[list[Fraction]], list[Fraction]]:
    law = modes._law()
    exact = {k: law.exact(v) for k, v in values.items()}
    rows, command, _ = law._rows(
        body,
        {**exact, "period": Fraction(1, 100)},
        lambda _line, _at, term: law.exact(term.sign) * law.exact(term.number),
    )
    n = len(body.memory)
    wheel = n + law.LOOP_SIGNALS.index("wheel_angle")
    update = [[Fraction(1)] + [Fraction(0)] * n]
    for row in rows:
        update.append([row[wheel], *row[:n]])
    return update, [command[wheel], *command[:n]]


def test_the_count_equals_an_independent_computation_on_random_small_laws() -> None:
    rng = random.Random(1586)
    seen: set[tuple[int, int]] = set()
    for _ in range(400):
        memory, lines, values, command, _n = _random_law(rng)
        body = modes._body(memory, lines, command)
        update, row = _exact_matrices(body, values)
        want = _oracle(update, row)
        circle = modes._law().unit_circle(body, values, period=0.01)
        assert (circle.algebraic_at_one, circle.at_minus_one) == want, (memory, lines, values)
        assert circle.at_one == circle.algebraic_at_one - circle.set_aside
        seen.add(want)
    assert {(0, 0), (1, 0), (2, 0)} <= seen, f"the random laws reach only {sorted(seen)}"
