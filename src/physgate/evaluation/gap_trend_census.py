"""The published gap trend's names, bound and parser, as the Evidence page's route is handed them.

On the evaluation's side, so the command's composition root reaches the gaps through it and
imports nothing of the gaps itself; the route's own module imports nothing of them either.
"""

from __future__ import annotations

from physgate.evaluation.evidence import TrendCensus
from physgate.evaluation.gaps import published

#: What the route over each role's published gap trend reads with.
TREND = TrendCensus(
    roles=published.ROLES,
    name=published.published_name,
    most=published.MOST_PUBLISHED_BYTES,
    parse=published.read_published,
    refused=published.GapsError,
)
