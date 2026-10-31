"""The item views the operator UI's server rendered, and when: where a review time starts.

ARCH-130 measures how long a person takes to decide an item once it is shown, and a time counted
in the browser would be a number born in the interface. So the server that renders an item's view
stamps when, here, in memory only, under an id of its own making; the page sends that id back with
its decision, and never a time; the decision route takes the stamp from here into the decision's
own line. The stamp is the queue's own clock, the one the decision's time is written by.

A decision whose id the register does not hold has no review time, never zero: none sent, one this
server never made, one dropped as the oldest of too many, one made by a server since stopped, or
one for another run, item or item line than the decision names.
"""

from __future__ import annotations

import secrets
import threading
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from physgate.orchestrator import queue

#: The most views held at once; past it the oldest is dropped.
MAX_VIEWS = 4096

#: A view id as the server makes it: 16 random bytes, URL-safe, unpadded.
VIEW_ID_PATTERN = r"^[A-Za-z0-9_-]{22}$"


class ViewRegister:
    """Each rendered item view by its id: the run, the item, its line's digest, when shown."""

    def __init__(self, limit: int = MAX_VIEWS) -> None:
        """An empty register holding at most ``limit`` views."""
        self._limit = limit
        self._lock = threading.Lock()
        self._views: OrderedDict[str, tuple[Path, str, str, datetime]] = OrderedDict()

    def shown(self, run_dir: Path, item_id: str, item_sha256: str) -> str:
        """Record that the view of ``item_id``'s line ``item_sha256`` is shown now; its id."""
        view_id = secrets.token_urlsafe(16)
        with self._lock:
            self._views[view_id] = (run_dir, item_id, item_sha256, queue.utc_now())
            while len(self._views) > self._limit:
                self._views.popitem(last=False)
        return view_id

    def shown_at(
        self, view_id: str | None, run_dir: Path, item_id: str, item_sha256: str
    ) -> datetime | None:
        """When the view ``view_id`` was shown, if it is this run's view of this item line."""
        with self._lock:
            found = None if view_id is None else self._views.get(view_id)
        if found is None or found[:3] != (run_dir, item_id, item_sha256):
            return None
        return found[3]
