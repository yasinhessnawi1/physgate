"""The register of ablation flags: every switch a run can be measured with or without.

The architecture makes each major component switchable on its own, so that a
component's effect can be measured by running without it (ARCH-140). A flag
exists here or it does not exist: this register names each one, the values it
may take and what each value means.

**No flag has a default, and none is read from the environment.** Each run's
value is a required parameter of the run, recorded in its configuration file
before the first action. A value the run did not record is a condition nobody
chose and no reader can see, and an ablation that silently took a default would
report a number measured under a different arm than the one it names.

A flag is added here when the switch it names is built, and not before: an
entry that nothing reads is a switch that does nothing.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

_Text = Annotated[str, StringConstraints(min_length=1)]


class Flag(BaseModel):
    """One ablation switch: its name, the values it may take, and what each means."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
    values: tuple[_Text, ...]
    meanings: dict[_Text, _Text]
    architecture: Annotated[str, StringConstraints(pattern=r"^ARCH-[0-9]{3}$")]

    @model_validator(mode="after")
    def _every_value_has_one_meaning(self) -> Flag:
        if len(self.values) < 2 or len(set(self.values)) != len(self.values):
            msg = "a flag has at least two distinct values"
            raise ValueError(msg)
        if set(self.meanings) != set(self.values):
            msg = "every value of a flag, and nothing else, has a meaning"
            raise ValueError(msg)
        return self


#: The physics gate's three positions. The type is spelled out so the type
#: checker can use it; a test holds it equal to the register's entry.
GateMode = Literal["on", "off", "observe"]

GATE_MODE = Flag(
    name="gate_mode",
    values=("on", "off", "observe"),
    meanings={
        "on": "every check runs, and a blocking failure refuses the work before review",
        "off": "no check runs; the run records that the gate stage was skipped, and why",
        "observe": (
            "every check runs and every result is recorded, stamped as observed, and nothing "
            "is refused; the run that makes the gate's catches interpretable"
        ),
    },
    architecture="ARCH-140",
)

#: Every ablation flag, in the order the architecture lists the switches.
REGISTER: tuple[Flag, ...] = (GATE_MODE,)
