"""The register's two kinds of row: a domain ``Role`` and a ``CrossCuttingRole`` (ARCH-050/051).

A role here is a thin, named handle onto machinery that is already generic over
any role string: ownership is decided at the store (``state/store.py``'s
``write_node`` compares the acting role against a node's own ``owner_role``, a
field set once at creation, never a table this module populates) and the
reading set is decided by ``knowledge.loader`` from the role's name alone. This
module adds nothing to either — it exists so ARCH-050's and ARCH-051's tables
become one executable, tested fact per role, and so a later role has one
obvious place to be added, not a decision about where ownership or
reading-set logic should live.

**Two kinds, because a cross-cutting role has no domain.** A domain role works in
one of the architecture's domains. Sizing and integration work across them: sizing
alone writes the quantities that tie domains together, integration alone may declare
a module complete. Neither has a domain of its own, so neither is given one to fit a
type; a :class:`CrossCuttingRole` names what it owns instead. Both kinds read the
same way, from the role's name.

**No model string lives here, and that is deliberate.** A pinned model is an
explicit, recorded parameter of a run (``RunConfig.models``, keyed by role
name), never a constant a role definition could freeze outside of it — the same
discipline a flag's value or a seed is held to. A role's "model" is simply
``config.models.roles[role.name]`` at dispatch time; nothing here needs to know
what that string is.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from physgate.knowledge import loader
from physgate.state.schema import DomainKind

#: The same safe, lower-case directory-name pattern ``knowledge.loader`` holds a
#: role string to, repeated here so a malformed role fails at construction
#: rather than only when something later resolves it to a path.
_RoleName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
_ArchId = Annotated[str, StringConstraints(pattern=r"^ARCH-[0-9]{3}$")]

#: What a cross-cutting role owns, alone, across every domain:
#: - ``cross_nodes``: the nodes that carry a quantity more than one domain depends on,
#:   interface nodes excepted (those are fixed when the work is decomposed);
#: - ``completion``: the declaration that a module is complete.
CrossCuttingDuty = Literal["cross_nodes", "completion"]


class _Reads(BaseModel):
    """What every registered role shares: a name, and the reading set that name resolves to."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: _RoleName

    def always_loaded(self, *, root: Path = loader.DEFAULT_ROOT) -> tuple[Path, ...]:
        """The always-loaded set (ARCH-023): cross's standards, then this role's own pair."""
        return loader.always_loaded(self.name, root=root)

    def required_reading(
        self,
        module_spec: Path,
        *,
        interfaces: tuple[Path, ...] = (),
        root: Path = loader.DEFAULT_ROOT,
    ) -> tuple[Path, ...]:
        """The required-reading set (ARCH-020): always-loaded, the module spec, interfaces."""
        return loader.required_reading(self.name, module_spec, interfaces=interfaces, root=root)


class Role(_Reads):
    """One domain role the loop can dispatch (ARCH-050).

    ``name`` is what ``dispatch.py`` calls ``assigned_role``, what
    ``knowledge.loader`` resolves a reading set from, and what a node's
    ``owner_role`` must equal for this role to write it — one string, read by
    three different generic mechanisms, not three names kept in step by hand.
    """

    #: The architecture's own domain vocabulary (``state.schema.DomainKind``).
    domain: DomainKind
    #: Where this row is specified, so a reader can find the acceptance test.
    architecture: _ArchId


class CrossCuttingRole(_Reads):
    """One cross-cutting role (ARCH-051): no domain, and one duty it alone holds.

    The register refuses a second role owning the same duty, so "alone" is a
    property of the register, not a promise each row makes for itself.
    """

    #: Where this row is specified, so a reader can find the acceptance test.
    architecture: _ArchId
    #: The one thing this role owns across every domain.
    owns: CrossCuttingDuty

    @field_validator("name")
    @classmethod
    def _not_the_shared_standards(cls, name: str) -> str:
        # ``cross`` names the standards every role reads, not a role: the loader gives it
        # that one file and no skill file of its own.
        if name == loader.CROSS:
            msg = "'cross' is the standards every role reads, not a role's name"
            raise ValueError(msg)
        return name


#: A row of the role register: either kind.
RegisteredRole = Role | CrossCuttingRole
