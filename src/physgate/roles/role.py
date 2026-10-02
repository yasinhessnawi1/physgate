"""``Role``: a domain role's name, its domain, and its reading set (ARCH-050).

A role here is a thin, named handle onto machinery that is already generic over
any role string: ownership is decided at the store (``state/store.py``'s
``write_node`` compares the acting role against a node's own ``owner_role``, a
field set once at creation, never a table this module populates) and the
reading set is decided by ``knowledge.loader`` from the role's name alone. This
class adds nothing to either — it exists so ARCH-050's table (name, domain,
first-slice description) becomes one executable, tested fact per role, and so a
later role (a reviewer pair, the mechanical and electrical rows) has one
obvious place to be added, not a decision about where ownership or
reading-set logic should live.

**No model string lives here, and that is deliberate.** A pinned model is an
explicit, recorded parameter of a run (``RunConfig.models``, keyed by role
name), never a constant a role definition could freeze outside of it — the same
discipline a flag's value or a seed is held to. A role's "model" is simply
``config.models.roles[role.name]`` at dispatch time; nothing here needs to know
what that string is.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

from physgate.knowledge import loader
from physgate.state.schema import DomainKind

#: The same safe, lower-case directory-name pattern ``knowledge.loader`` holds a
#: role string to, repeated here so a malformed ``Role`` fails at construction
#: rather than only when something later resolves it to a path.
_RoleName = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
_ArchId = Annotated[str, StringConstraints(pattern=r"^ARCH-[0-9]{3}$")]


class Role(BaseModel):
    """One domain role the loop can dispatch (ARCH-050/ARCH-051).

    ``name`` is what ``dispatch.py`` calls ``assigned_role``, what
    ``knowledge.loader`` resolves a reading set from, and what a node's
    ``owner_role`` must equal for this role to write it — one string, read by
    three different generic mechanisms, not three names kept in step by hand.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: _RoleName
    #: The architecture's own domain vocabulary (``state.schema.DomainKind``).
    #: Cross-cutting roles (sizing, integration, ...; ARCH-051) are not domain
    #: roles and are not modelled by this class.
    domain: DomainKind
    #: Where this row is specified, so a reader can find the acceptance test.
    architecture: _ArchId

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
