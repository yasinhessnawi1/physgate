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

One flag is not an arm a run is measured under. ``os_layer_absent: allow`` is
for development only, and it can never appear in a measured run: the evaluation
refuses every reportable run that names it, whatever the OS layer where it runs.
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

#: Whether a run acts on a person's queue decisions. Spelled out for the type checker, as
#: the gate mode is; a test holds it equal to the register's entry.
QueueDecisions = Literal["act", "record"]

QUEUE_DECISIONS = Flag(
    name="queue_decisions",
    values=("act", "record"),
    meanings={
        "act": (
            "a person's bound decision on a queue item is taken into the run where no attempt "
            "is in progress and acted on in code: an approve merges, a reject retries, fixes "
            "once or ends the subtask"
        ),
        "record": (
            "decisions are recorded in the queue's decisions file and nothing in the run acts "
            "on them; every run recorded before the switch existed reads as this, and every "
            "evaluation run uses it, so no measured outcome depends on a decision"
        ),
    },
    architecture="ARCH-133",
)

#: Whether a run's role sessions may run where the OS layer is absent. A development switch,
#: not an ablation arm: ``allow`` can never appear in a measured run, because the evaluation
#: refuses a reportable run that names it. Spelled out for the type checker, as the others are;
#: a test holds it equal to the register's entry.
OsLayerAbsent = Literal["refuse", "allow"]

OS_LAYER_ABSENT = Flag(
    name="os_layer_absent",
    values=("refuse", "allow"),
    meanings={
        "refuse": (
            "role sessions run only inside the OS layer: a run whose layer is absent is refused "
            "at its configuration, and at every run and resume, before any session starts; every "
            "run recorded before the switch existed reads as this"
        ),
        "allow": (
            "for development only: where the layer is absent, role sessions run with the text "
            "hooks alone, said on standard error and on every run's and resume's OS-layer line; "
            "a run that acts on queue decisions is refused all the same; never in a measured "
            "run, since the evaluation refuses a reportable run that names it"
        ),
    },
    architecture="ARCH-091",
)

#: Whether the plan is reviewed before anything is dispatched. Spelled out for the type checker, as
#: the others are; a test holds it equal to the register's entry.
DesignReview = Literal["off", "observe"]

DESIGN_REVIEW = Flag(
    name="design_review",
    values=("off", "observe"),
    meanings={
        "off": (
            "the plan is not reviewed: nothing is asked of a design reviewer and nothing about a "
            "review is recorded; every run recorded before the switch existed reads as this"
        ),
        "observe": (
            "the design reviewer, on a model other than the decomposition's, judges the plan "
            "after the one call and before anything is dispatched; what it came to is recorded "
            "in the run's opening and the run proceeds whatever it says, so the verdict is "
            "measured without changing the run; every reportable run uses it"
        ),
    },
    architecture="ARCH-060",
)

#: Every ablation flag, in the order the architecture lists the switches.
REGISTER: tuple[Flag, ...] = (GATE_MODE, QUEUE_DECISIONS, OS_LAYER_ABSENT, DESIGN_REVIEW)
