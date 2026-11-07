"""The engine catalogue: the engines the desktop app's engine step offers, read once at start.

The file is the checkout's own ``desktop/onboarding/engines.json``, the one the desktop shell
compiles into itself. The server reads it once, when the command starts and before it listens,
and keeps the bytes' parse, digest and length in memory; the route that serves it reads nothing
at request time. So no request may read in the checkout, and the guard's request-time rule
needs no slot for it. The UI is served only from a source checkout, so the file is always where
the server can look for it.

**The read is held to fixed checks, and a failed check never stops the server.** A malformed
catalogue must not take the operator UI down for one file: the result is then ``refused``, with
a sentence, and only the screen's engine section shows the error. The checks, in order:

1. The path is built from fixed parts and judged by the allowlist's own refusal test, the one
   every request's reads are held to: a path that reaches the held-out tier or an answer key,
   or lies in an evaluation corpus, is refused before anything is opened.
2. It is reached by a walk of descriptors from the checkout: the checkout's own directory, held
   to the identity it had when the read began, then each folder below it opened relative to the
   last and never through a link, then the file itself, never through a link and without
   waiting (a pipe planted at the path would otherwise hang the start). No swap of a name above
   the file can redirect the read.
3. What was opened must be a regular file with one name on disk (a second name could be a
   refused file's), no larger than ``MAX_BYTES``, and the very file the path was judged as.
4. The bytes are strict UTF-8 and strict JSON: a repeated key, ``NaN`` and the infinities are
   refused, since the standard parser accepts all three, and the top level is an object holding
   an ``engines`` list. Nothing else of its shape is checked here: the screen's guard reads each
   field it draws on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from physgate.ui.exceptions import UIError
from physgate.ui.paths import Allowlist

#: Where the catalogue lies in the checkout, as the answer names it: relative, never absolute.
CATALOGUE_FILE = "desktop/onboarding/engines.json"

#: The folders walked below the checkout, and the file's own name.
_FOLDERS = ("desktop", "onboarding")
_NAME = "engines.json"

#: The largest catalogue read, in bytes. Today's file is 2,243.
MAX_BYTES = 64 * 1024

State = Literal["read", "absent", "refused"]


@dataclass(frozen=True)
class EngineCatalogue:
    """What the start-time read found: the parse with its digest and length, or why not.

    ``read`` carries ``sha256``, ``length`` and ``value``; ``refused`` carries ``reason``;
    ``absent`` carries nothing. Any other combination is refused when the record is made.
    """

    state: State
    sha256: str | None = None
    length: int | None = None
    value: object = None
    reason: str | None = None

    def __post_init__(self) -> None:
        """Refuse a record whose fields do not fit its state.

        Raises:
            UIError: the fields present are not the ones the state carries.
        """
        read = self.sha256 is not None and self.length is not None and self.value is not None
        fits = {
            "read": read and self.reason is None,
            "absent": not read and self.value is None and self.reason is None,
            "refused": self.sha256 is None
            and self.length is None
            and self.value is None
            and self.reason is not None,
        }
        if not fits.get(self.state, False):
            msg = "an engine catalogue record's fields do not fit its state"
            raise UIError(msg, state=str(self.state))


#: The catalogue of a server that has none: no checkout, or no file in it.
ABSENT = EngineCatalogue(state="absent")


def load(harness: Path | None, refused: Allowlist) -> EngineCatalogue:
    """Not built yet: every checkout reads as listing no engines."""
    return ABSENT
