"""The sentinel's exclusion test is the prefix rule it replaced, case for case.

The rule is: a path is excluded if it equals an exclusion, or starts with one
followed by a separator. It ran once per exclusion for every entry of every
protected tree at every hook, so a root excluding hundreds of entries (an
environment's ``site-packages``, all but its startup files) made every walk
twenty times slower. The test is now set lookups on the path and its ancestors.
This holds it to the old rule over generated paths, relative and absolute,
with empty segments and trailing separators.
"""

from __future__ import annotations

import random

from physgate.hooks.snapshot import _excluded, _exclusions


def _prefix_rule(path: str, exclude: list[str]) -> bool:
    return any(path == e or path.startswith(e.rstrip("/") + "/") for e in exclude)


def test_the_set_test_agrees_with_the_prefix_rule_everywhere() -> None:
    rng = random.Random(1)
    parts = ["a", "b", "ab", "staging", "knowledge", "x.pth", "site-packages", ""]
    for _ in range(50_000):
        path = rng.choice(["/", ""]) + "/".join(rng.choice(parts) for _ in range(rng.randint(1, 5)))
        exclude = [
            rng.choice(["/", ""])
            + "/".join(rng.choice(parts) for _ in range(rng.randint(0, 4)))
            + rng.choice(["", "/", "//"])
            for _ in range(rng.randint(0, 4))
        ]
        assert _excluded(path, _exclusions(exclude)) == _prefix_rule(path, exclude), (
            path,
            exclude,
        )


def test_the_cases_that_matter() -> None:
    staging = _exclusions(["/w/knowledge/staging"])
    assert _excluded("/w/knowledge/staging", staging)
    assert _excluded("/w/knowledge/staging/c.md", staging)
    assert not _excluded("/w/knowledge/staging2/c.md", staging)
    assert not _excluded("/w/knowledge", staging)
    assert not _excluded("/anything", _exclusions([]))
