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

#: The shortest run of a canary's characters taken as the canary shown. A canary is 32
#: random hex characters; a given 16-character run of one turns up by chance about once
#: in 10**19 positions. So a canary printed in two halves, or a partial read that shows
#: at least this much of it, is found.
PART = 16

_SQUEEZE = re.compile(r"\\[nrt]|\s")


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
    text = data.decode(errors="replace")
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
