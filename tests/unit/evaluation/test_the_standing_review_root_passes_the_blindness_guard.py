"""An artefact materialised under the standing review root passes the instrument's blindness guard.

Pinned so that a later rename of the root cannot bring back the collision in which
every reviewer-facing path under the old scratch root named the harness and was
refused. The guard itself is unchanged; the same artefact under the old root is
still refused, as a control.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from instrument_corpus import BASE_NODES, LABEL, MAGNITUDE_ARTEFACT

from physgate.evaluation.inject.corpus import Base, Patch, telltales
from physgate.evaluation.inject.exceptions import BlindnessError
from physgate.evaluation.inject.materialise import materialise, require_blind
from physgate.reviewers.places import STANDING_ROOT_NAME, require_review_root, review_dir

BASE = Base.model_validate_json(json.dumps({"label": LABEL, "nodes": list(BASE_NODES)}))
PATCH = Patch.model_validate_json(json.dumps(MAGNITUDE_ARTEFACT["injected"]))


@pytest.fixture
def neutral_base() -> Iterator[Path]:
    """A fresh directory whose own path names nothing, so only the root's name is under test.

    Not pytest's ``tmp_path``: that path carries the test's own name.
    """
    for _ in range(20):
        base = Path(tempfile.mkdtemp(prefix="pin"))
        if not telltales(str(base.resolve())):
            break
        shutil.rmtree(base)
    else:  # pragma: no cover - twenty random names all holding a word
        pytest.fail("no neutral temporary directory could be made")
    yield base.resolve()
    shutil.rmtree(base)


def test_an_artefact_under_the_standing_root_passes(neutral_base: Path) -> None:
    root = require_review_root(neutral_base / STANDING_ROOT_NAME)
    made = materialise(BASE, PATCH, review_dir(root, "r0123456789ab") / "read")
    require_blind(made, ("m1",))


def test_the_same_artefact_under_the_old_root_is_refused(neutral_base: Path) -> None:
    made = materialise(BASE, PATCH, neutral_base / "physgate-scratch" / "r0123456789ab")
    with pytest.raises(BlindnessError, match="paths"):
        require_blind(made, ("m1",))
