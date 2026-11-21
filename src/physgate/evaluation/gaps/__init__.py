"""The two gaps: visible minus held out, and validation minus held out, with their counts.

Evaluation-side machinery: it imports the product core, and no module outside the
evaluation imports it. The gap trend's one reader is :func:`read_gap_trend`.
"""

from physgate.evaluation.gaps.measure import GapLine, GapWeek, gap_weeks, read_gap_trend

__all__ = ["GapLine", "GapWeek", "gap_weeks", "read_gap_trend"]
