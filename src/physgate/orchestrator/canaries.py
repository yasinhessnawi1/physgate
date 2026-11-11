"""Whether a session's stream shows a canary: verbatim, or in a form a read can show it in.

A canary marks material no session may read (the held-out tier, reviewer rubrics). The
hooks refuse every read of that material they can judge; a read whose path is built
while the command runs is judged by nothing, and shows the canary in the session's own
stream, as a tool's output. Not always verbatim: a read printed in two halves, in
upper case, reversed, as hex or as base64, wrapped or not, shows the content with no
verbatim canary (measured on the real binary). Each of those forms is looked for, and
so is any run of :data:`PART` of a canary's characters, which a partial read shows.

**The limit, stated:** a read that shows less than :data:`PART` characters of a canary
(or a part of one encoded), or that uses the material without printing it (a count, a
comparison, a value carried into a computation), shows no canary in any form looked
for. So a hit proves the session displayed the marked material; no hit proves
nothing, and is never evidence of no exposure.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from typing import Literal

#: The shortest run of a canary's characters taken as the canary shown. A canary is 32
#: random hex characters; a given 16-character run of one turns up by chance about once
#: in 10**19 positions. So a canary printed in two halves, or a partial read that shows
#: at least this much of it, is found.
PART = 16

_SQUEEZE = re.compile(r"\\[nrt]|\s")

#: The characters a session can put inside a printed value that read back as nothing: the C0
#: and C1 controls, DEL, and the format characters 2.1.311 and later write as escapes (the soft
#: hyphen, the zero-width and direction marks, the direction embeddings and overrides, the word
#: joiner and invisible operators, the direction isolates, the byte order mark). In the raw
#: stream each is either itself (the earlier pins) or a JSON escape (2.1.311 and later, and the
#: C0 controls everywhere); a value split by them still reads as itself, so the scans read
#: through both forms.
_ESCAPE = (
    r"\\u(?:00[01][0-9a-fA-F]|007[fF]|00[89][0-9a-fA-F]|00[aA][dD]|200[b-fB-F]"
    r"|202[a-eA-E]|206[0-46-9]|[fF][eE][fF][fF])"
)
INVISIBLE = re.compile(
    _ESCAPE + "|[\x00-\x1f\x7f-\x9f\u00ad\u200b-\u200f\u202a-\u202e\u2060-\u2064"
    "\u2066-\u2069\ufeff]"
)
#: The same, over the stream's bytes: each character in its UTF-8 form, or its escape.
INVISIBLE_BYTES = re.compile(
    _ESCAPE.encode() + rb"|[\x00-\x1f\x7f]|\xc2[\x80-\x9f\xad]|\xe2\x80[\x8b-\x8f\xaa-\xae]"
    rb"|\xe2\x81[\xa0-\xa4\xa6-\xa9]|\xef\xbb\xbf"
)


def split_by_invisible(value: bytes) -> re.Pattern[bytes]:
    """``value`` as it reads in a raw stream with any invisible characters between its bytes."""
    between = b"(?:" + INVISIBLE_BYTES.pattern + b")*"
    return re.compile(between.join(re.escape(value[i : i + 1]) for i in range(len(value))))


def _base64_cores(canary: str) -> list[str]:
    """The base64 runs a canary always becomes, wherever it falls in the encoded bytes.

    Base64 encodes three bytes as four characters, so the canary's encoding depends on
    its offset modulo three; the groups at its two ends also hold neighbouring bytes,
    and are dropped.
    """
    cores = []
    for offset in range(3):
        encoded = base64.b64encode(b"\0" * offset + canary.encode()).decode()
        cores.append(encoded[4 if offset else 0 : -4])
    return cores


def canary_seen(data: bytes, live: frozenset[str]) -> str | None:
    """The first of ``live`` that ``data`` shows, in any form looked for, if any.

    ``data`` is a session's stream as the runtime wrote it: JSON lines, in which a tool's
    output is a JSON string, so a line break in the output is a backslash and an ``n``.
    """
    if not live:
        return None
    # Read through any invisible character, as itself or escaped: a canary printed with one
    # between its characters is the canary shown.
    text = INVISIBLE.sub("", data.decode(errors="replace"))
    squeezed = _SQUEEZE.sub("", text.replace("\\/", "/"))
    lowered = (text.lower(), squeezed.lower())
    for canary in sorted(live):
        plain = canary.lower()
        forms = (plain, plain[::-1], canary.encode().hex())
        if any(form in view for form in forms for view in lowered):
            return canary
        if any(core in view for core in _base64_cores(canary) for view in (text, squeezed)):
            return canary
        runs = {plain[i : i + PART] for i in range(len(plain) - PART + 1)}
        if any(run in view for run in runs for view in lowered):
            return canary
    return None


@dataclass(frozen=True)
class CanaryCheck:
    """Whether a text shows a held-out canary or a rubric's, in any form looked for.

    The text a person or a reviewer wrote for a role session (a note, a quoted verdict) is held
    to the same canaries as a session's own stream, with the same limit: a hit proves the text
    shows the marked material, and no hit proves nothing.
    """

    held_out: frozenset[str]
    review_material: frozenset[str]

    def seen(self, text: str) -> Literal["held_out", "review_material"] | None:
        """The held-out tier first, since its exposure is the one that is counted (ARCH-141)."""
        data = text.encode()
        if canary_seen(data, self.held_out) is not None:
            return "held_out"
        if canary_seen(data, self.review_material) is not None:
            return "review_material"
        return None
