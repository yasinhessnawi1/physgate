"""The published tier status's names, bound, parser and sentences, as its route is handed them.

On the evaluation's side, so the command's composition root reaches the tiers through it and
imports nothing of the tiers itself; the route's own module imports nothing of them either.
"""

from __future__ import annotations

from physgate.evaluation.evidence import TiersCensus
from physgate.evaluation.tiers import published

#: What the route over each role's published tier status reads with.
TIERS = TiersCensus(
    roles=published.ROLES,
    name=published.published_name,
    most=published.MOST_STATUS_BYTES,
    parse=published.read_published_status,
    refused=published.TierStatusError,
    said=published.refusal_sentence,
)
