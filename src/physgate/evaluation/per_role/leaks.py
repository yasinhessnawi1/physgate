"""The leak rule: whether a text states a non-trivial number of a task's good reference answer.

The tier's validator holds a task's brief to it (:func:`.validate.brief_leaks`): no number of the
good reference other than 0, 1 or -1 may appear among the brief's numbers. Kept apart from the
validator, which runs the scorer, so that the same rule can be held, in the harness's own
environment, to what a session is now given for the task (:mod:`physgate.evaluation.tiers.issued`)
by the count-only values check.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from physgate.evaluation.per_role.answer import read_lti_tf
from physgate.evaluation.tiers.task import LoadedTask

NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
#: The numbers of a reference that tell nothing of it, wherever they appear.
TRIVIAL = (0.0, 1.0, -1.0)


def text_leaks(text: str, loaded: LoadedTask) -> bool:
    """Whether ``text`` states a non-trivial number of ``loaded``'s good reference.

    Raises:
        TaskFormatError: the good reference's answer cannot be read.
    """
    good = next(ref for ref in loaded.references if ref.fails is None)
    answer = read_lti_tf(Path(good.answer_path))
    numbers = [float(answer.gain.value), *answer.num_values(), *answer.den_values()]
    told = [float(x) for x in NUMBER.findall(text)]
    return any(
        math.isclose(n, t, rel_tol=1e-9, abs_tol=0.0)
        for n in numbers
        if n not in TRIVIAL
        for t in told
    )


__all__ = ["NUMBER", "TRIVIAL", "text_leaks"]
