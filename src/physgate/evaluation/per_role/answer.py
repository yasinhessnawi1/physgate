"""The answers an arm gives, by form, each validated before any scorer reads it.

An answer is untrusted input: it was written by the session under test. It is held to its
schema whole before a number in it is used, and a schema failure is scored as a failure of
the answer, never as a scorer error.

``lti_tf``: a continuous-time controller ``C(s) = gain * N(s) / D(s)``. The polynomial
coefficients are written highest power first. With ``s`` in 1/s, the coefficient of
``s**k`` carries the unit ``s**k`` (``s`` for ``k = 1``, ``1`` for ``k = 0``), so that every
term of each polynomial is dimensionless and the controller's own unit is the gain's. A
coefficient whose unit does not match its power is a schema error, as is a bare number.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from physgate.evaluation.per_role.exceptions import TaskFormatError
from physgate.evaluation.per_role.task import Measure

#: The largest answer file read: a controller is a few dozen numbers.
MAX_ANSWER_BYTES = 64 * 1024
#: The highest controller order accepted. Higher orders are numerically fragile in the
#: polynomial form and no task needs one.
MAX_ORDER = 10


def power_unit(power: int) -> str:
    """The unit the coefficient of ``s**power`` carries."""
    if power == 0:
        return "1"
    if power == 1:
        return "s"
    return f"s**{power}"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid", allow_inf_nan=False)


class LtiTf(_Frozen):
    """A proper continuous-time controller, as a gain and two polynomials in ``s``."""

    form: Literal["lti_tf"]
    gain: Measure
    num: tuple[Measure, ...] = Field(min_length=1, max_length=MAX_ORDER + 1)
    den: tuple[Measure, ...] = Field(min_length=1, max_length=MAX_ORDER + 1)

    @model_validator(mode="after")
    def _is_a_proper_controller(self) -> LtiTf:
        if len(self.num) > len(self.den):
            msg = "the controller is improper: its numerator has the higher degree"
            raise ValueError(msg)
        if self.den[0].value == 0:
            msg = "the denominator's leading coefficient is zero"
            raise ValueError(msg)
        for name, poly in (("numerator", self.num), ("denominator", self.den)):
            degree = len(poly) - 1
            for index, coefficient in enumerate(poly):
                expected = power_unit(degree - index)
                if coefficient.unit != expected:
                    msg = (
                        f"the {name}'s coefficient of s**{degree - index} is in "
                        f"{coefficient.unit!r}; it carries {expected!r}"
                    )
                    raise ValueError(msg)
        return self

    def num_values(self) -> list[float]:
        """The numerator's coefficients as plain numbers, highest power first."""
        return [float(c.value) for c in self.num]

    def den_values(self) -> list[float]:
        """The denominator's coefficients as plain numbers, highest power first."""
        return [float(c.value) for c in self.den]


def read_lti_tf(path: Path) -> LtiTf:
    """The controller at ``path``, or refused with the reason.

    Raises:
        TaskFormatError: it is missing, a link, too large, or not a controller.
    """
    if path.is_symlink() or not path.is_file():
        msg = "no answer file"
        raise TaskFormatError(msg, path=str(path))
    raw = path.read_bytes()
    if len(raw) > MAX_ANSWER_BYTES:
        msg = f"the answer is larger than any controller ({len(raw)} bytes)"
        raise TaskFormatError(msg, path=str(path))
    try:
        return LtiTf.model_validate_json(raw)
    except ValidationError as exc:
        msg = f"the answer is not a controller: {exc.errors()[0]['msg']}"
        raise TaskFormatError(msg, path=str(path)) from exc
