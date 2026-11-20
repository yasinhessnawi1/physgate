"""Which modules owe a person's standing sign-off before they are complete (ARCH-130).

ARCH-130 names standing sign-offs that a person gives through the approval queue, whatever a
reviewer said. Two of them belong to design roles: the stability margin of a control module and
the sizing of a mechanical module. A module owes one by its role, as its planning line names it,
and never by the names of the quantities it writes: a margin written under a name the gate's
catalogue does not know is still a control module's margin, and a gate records an unknown name as
unchecked rather than refusing it, so a rule by name could be stepped round by renaming.

The rule is a typed table here: one row per role that owes a sign-off, each with what the person
signs, the quantity names an item shows first, what to check, and the published sources the row
rests on. A run's first line carries the digest of the table's version, written by code and never
by a parameter: a switch that could leave the digest out would be a way to skip the sign-off.
Replay reads the rows of the version the line names, so a run keeps the rule it ran under when a
later version is added. A run recorded before the table existed names none and owes nothing.

The names an item shows are taken in the order the cited standards sections take them up, until a
sourced priority list replaces that order as a later version of the table.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from physgate.orchestrator.common import NonEmptyStr
from physgate.orchestrator.plan import QuantityName

#: What a module's sign-off is on: a control loop's stability margin, or a mechanical sizing.
SignOffKind = Literal["stability_margin", "sizing"]

_RoleName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]

#: The most names a row lists in its order of showing, and the most an item shows (ARCH-130).
MAX_LISTED = 8
SHOWN = 3


class SignOffRule(BaseModel):
    """One role that owes a sign-off: what is signed, what is shown first, and why."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    role: _RoleName
    owes: SignOffKind
    #: What the person signs, in the words an item and a refusal use.
    signs: NonEmptyStr
    #: The quantity names an item shows first, in this order; at most three of them are shown.
    shown: Annotated[tuple[QuantityName, ...], Field(min_length=1, max_length=MAX_LISTED)]
    #: What the person checks before signing, each sentence with the source it rests on.
    checks: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1, max_length=6)]
    #: The published sources the row rests on, each with its locator.
    sources: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _each_name_once(self) -> SignOffRule:
        if len(set(self.shown)) != len(self.shown):
            msg = "a row lists each name it shows once"
            raise ValueError(msg)
        return self


class SignOffRules(BaseModel):
    """One version of the table: its number and its rows, one per role at most."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    version: Annotated[int, Field(ge=1)]
    rules: Annotated[tuple[SignOffRule, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _one_row_per_role(self) -> SignOffRules:
        roles = [rule.role for rule in self.rules]
        if len(set(roles)) != len(roles):
            msg = "a version of the table gives a role one row at most"
            raise ValueError(msg)
        return self

    def rule_of(self, role: str) -> SignOffRule | None:
        """The row of ``role``, or ``None`` where the role owes no sign-off."""
        return next((rule for rule in self.rules if rule.role == role), None)


def rules_sha256(rules: SignOffRules) -> str:
    """The digest of a version of the table: sha256 of its canonical JSON."""
    canonical = json.dumps(
        rules.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


_CONTROL_SOURCES = (
    "ARCH-130: a control role's standing sign-off on stability margin",
    "knowledge/control/standards.md section 2, which cites K. J. Astrom and R. M. Murray, "
    "Feedback Systems, 2nd ed., Princeton University Press, 2021, section 10.3 'Stability "
    "Margins', p. 10-17",
    "M. G. Safonov and M. Athans, 'Gain and phase margin for multiloop LQG regulators', IEEE "
    "Transactions on Automatic Control 22(2), 1977, pp. 173-179, as section 2 cites it",
    "J. C. Doyle, 'Guaranteed margins for LQG regulators', IEEE Transactions on Automatic "
    "Control 23(4), 1978, pp. 756-757, as section 2 cites it",
    "S. Skogestad and I. Postlethwaite, Multivariable Feedback Control, 2nd ed., Wiley, 2005, "
    "section 9.2.2, as section 2 cites it",
)

_MECHANICAL_SOURCES = (
    "ARCH-130: a mechanical role's standing sign-off on sizing",
    "knowledge/mechanical/standards.md section 2, which cites NASA-STD-5001B section 3.2, "
    "NASA-STD-5020B section 4.4.1 and ECSS-E-ST-32-10C Rev.2 Corr.1 section 1",
    "knowledge/mechanical/standards.md section 11, which cites W. Moebs et al., University "
    "Physics Vol. 1, OpenStax, 2016, sections 9.6 and 10.5",
    "knowledge/mechanical/standards.md section 12, which cites the Pololu product 3073 page and "
    "OpenStax University Physics Vol. 1, section 6.2",
)

#: The first version of the table.
VERSION_1 = SignOffRules(
    version=1,
    rules=(
        SignOffRule(
            role="control",
            owes="stability_margin",
            signs="stability margin",
            shown=(
                "phase_margin",
                "gain_margin",
                "sensitivity_peak",
                "delay_margin",
                "gain_crossover_frequency",
                "sample_rate",
                "loop_gain",
                "step_peak",
            ),
            checks=(
                "Check that the margins were measured on the loop that runs, with any estimator "
                "and the sample delay in it, not on a full-state loop alone (control standards "
                "section 2, after Doyle 1978 and Skogestad and Postlethwaite section 9.2.2).",
                "Check that the stability margin is stated beside the gain and phase margins: "
                "good gain and phase margins alone do not keep the loop's Nyquist curve away "
                "from the critical point (control standards section 2, after Astrom and Murray "
                "section 10.3).",
                "A margin shown without the loop it was measured on is a reason to reject.",
            ),
            sources=_CONTROL_SOURCES,
        ),
        SignOffRule(
            role="mechanical",
            owes="sizing",
            signs="sizing",
            shown=(
                "torque_peak",
                "stall_torque",
                "mass",
                "supported_mass",
                "moment_of_inertia",
                "reaction_force",
                "load_force",
                "gear_ratio",
            ),
            checks=(
                "Check that each strength claim is a margin of safety against a stated factor, "
                "once for yield and once for ultimate (mechanical standards section 2, after "
                "NASA-STD-5001B section 3.2).",
                "Check that the drive torque is sized against the motor's usable torque and the "
                "traction limit, with its margin stated (mechanical standards section 12).",
                "Check that mass, centre of mass and inertia name the list and the method they "
                "come from (mechanical standards section 11).",
                "A factor that multiplies preload instead of the limit load is a reason to reject "
                "(mechanical standards section 2, after NASA-STD-5020B section 4.2.1).",
            ),
            sources=_MECHANICAL_SOURCES,
        ),
    ),
)

#: The version every run started now records.
CURRENT = VERSION_1
CURRENT_SHA256 = rules_sha256(CURRENT)

#: Every version a recorded run may name, by its digest: a run keeps the one it recorded.
VERSIONS: Mapping[str, SignOffRules] = MappingProxyType({rules_sha256(VERSION_1): VERSION_1})


def known_rules(digest: str) -> SignOffRules | None:
    """The version of the table ``digest`` names, or ``None`` if no version here has it."""
    return VERSIONS.get(digest)


@dataclass(frozen=True)
class RaisedSignOff:
    """A sign-off item on the record: the module it is about and the digest of what it shows."""

    item_id: str
    module: str
    values_sha256: str
