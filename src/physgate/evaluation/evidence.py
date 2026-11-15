"""The Evidence screen's read routes, registered beside the operator UI's own."""

from __future__ import annotations

from physgate.ui.routes import Route

#: Every route this module serves, registered by the command's composition root.
ROUTES: tuple[Route, ...] = ()
