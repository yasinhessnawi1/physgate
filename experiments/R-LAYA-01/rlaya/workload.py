"""The workload — R-TM-01's generator, seeds and splits, reused exactly.

CRITERIA §5: *"R-TM-01's generator, seeds and splits, **reused exactly**: Train,
Test-ID, Test-OOD-A (`attempt == 3`), Test-OOD-B (unseen domain, with the
retrained arm for OOD-B as R-TM-01 defined it)."*

and §4 R1: *"Every arm sees the same samples, labels, seeds and splits, from
R-TM-01's generator, reused unmodified."*

--------------------------------------------------------------------------
The test-split fence
--------------------------------------------------------------------------
R4 and standards I-5 say the out-of-distribution sets are read once, at
measurement. That is enforced here rather than requested: `splits()` builds
**Train only** unless it is called with `allow_test=True`, which step 4's
measurement passes and nothing else may. A step-2 script that tried to look at
Test-ID would have to edit this file to do it, and that edit would be in the
diff.

`train_only()` goes further and never constructs a test split at all, not even
in memory: it reproduces `build_all(seed)["train"]` by drawing from a fresh
generator, which is byte-identical because `build_all` draws Train first.
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, Tuple

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import generator_b as G  # noqa: E402  (vendored, unmodified)

SEEDS = [0, 1, 2, 3, 4]        # R-TM-01 run_b.py SEEDS; CRITERIA §3 "five seeds"
CAL_N = 500                    # CRITERIA §3 "a 500-sample slice of Train only"
ROUTE_THRESHOLD = 0.8          # ARCH-131; CRITERIA §6 "at the ARCH-131 routing threshold of 0.8"
TRAIN_N = 8000                 # generator_b.build_all
TM_SEED_OFFSET = 1000          # R-TM-01: tmu hangs on internal seed 0, so 1000 + data seed

TEST_KEYS = ("test_id", "test_id_nofw", "ood_a", "ood_b")


def train_only(seed: int):
    """Exactly ``build_all(seed)["train"]``, constructing no test split.

    ``build_all`` draws Train first from a fresh ``default_rng(seed)``, so the
    same call on a fresh generator reproduces it exactly. Returns the generator's
    own 5-tuple ``(X, y, y_clean, raw, terms)``.
    """
    rng = np.random.default_rng(seed)
    out = G.make_split(TRAIN_N, rng, attempts=(1, 2))
    assert len(out[1]) == TRAIN_N
    return out


def train_nofw_only(seed: int):
    """``build_all(seed)["train_nofw"]``, the OOD-B arm's training split.

    R-TM-01 retrains on Train with the firmware domain dropped, and measures
    OOD-B (firmware only) against that model. This is a Train-side object: it is
    a filter of Train and contains no test sample. Reproduced here without
    constructing Test-ID or either OOD set.
    """
    return G._drop_fw(train_only(seed))


def draw_fingerprint(seed: int) -> Dict[str, str]:
    """A checksum of the Train draw, so R1 can be checked and not assumed.

    R1 requires every arm to see the same samples, labels and splits. The arms
    deliberately run in different environments — arm T needs numpy 2.4.6 under
    Python 3.11, the Laya arms need numpy 2.5.3 under 3.12 — and numpy's
    stream-compatibility policy says a `default_rng` stream is stable across
    versions. Standards §9 says a claim about a library is verified by running
    it, with the version. So every arm computes this and the driver refuses to
    report a number if two arms disagree.
    """
    import hashlib

    X, y, y_clean, raw, terms = train_only(seed)
    h = {}
    h["X"] = hashlib.sha256(np.ascontiguousarray(X, dtype=np.uint8)).hexdigest()
    h["y"] = hashlib.sha256(np.ascontiguousarray(y, dtype=np.uint32)).hexdigest()
    h["y_clean"] = hashlib.sha256(np.ascontiguousarray(y_clean, dtype=np.uint32)).hexdigest()
    raw_bytes = b"".join(
        np.ascontiguousarray([str(v) for v in raw[k]], dtype="U16").tobytes()
        for k in sorted(raw)
    )
    h["raw"] = hashlib.sha256(raw_bytes).hexdigest()
    h["n"] = str(len(y))
    h["sum_y"] = str(int(y.sum()))
    return h


def calibration_slice(n: int = CAL_N) -> slice:
    """The §3 temperature slice: the first 500 rows of Train.

    §3 says the slice is *"drawn once with a fixed seed and identical for every
    arm"*. It does not name a seed. The generator's own draw is the fixed seed
    that is actually available — Train is drawn by ``default_rng(seed)`` — and
    taking its first 500 rows is what R-TM-01 itself did (``run_b.py``:
    ``CAL_N = 500``, ``ytr[:CAL_N]``). Inventing a second seed here would be
    choosing a number the criteria do not name; reusing R-TM-01's convention
    keeps arm T comparable to the run being rerun.

    The slice is an index range, so it is identical for every arm by
    construction: there is no per-arm draw to go wrong.
    """
    return slice(0, n)


def splits(seed: int, *, allow_test: bool = False) -> Dict[str, Tuple[Any, ...]]:
    """Every split for ``seed``. Refuses the test splits unless asked.

    ``allow_test=True`` is passed by step 4's measurement and by nothing else.
    """
    if not allow_test:
        raise RuntimeError(
            "workload.splits() builds the test splits. R4 and standards I-5 say "
            "they are read once, at measurement. Use train_only()/train_nofw_only() "
            "for fitting; pass allow_test=True only from the step-4 measurement."
        )
    return G.build_all(seed)
