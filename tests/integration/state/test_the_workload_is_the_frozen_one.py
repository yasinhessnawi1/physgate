"""The workload this suite replays is the workload the frozen numbers came from.

The regression criterion compares the promoted store against numbers published by
a pre-registered experiment. That comparison means nothing unless the operations
being replayed are the ones that produced those numbers, and the copy of the
generator in this directory had to be adapted to pass the three gates.

Three proofs, in increasing strength:

1. **The operations are byte-identical.** Both generators are asked for all five
   seeds and the full workload is hashed — nodes, operations, payload sets,
   the deepest node and the mandated counts.
2. **The code is identical.** Both files are parsed and compared as syntax trees
   with annotations removed from each, which no reformatting and no comment can
   survive. See ``frozen_equivalence.py``; that module is the one to read
   sceptically, because everything here rests on it.
3. **The scoring is identical.** The adapted harness is run against the frozen
   store and the frozen generator, and every number it produces that is not a
   clock is compared with the same run under the frozen harness.

The first two run in the default suite. The third replays ten full workloads and
is marked as the slower kind.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from frozen_equivalence import normalised

HERE = Path(__file__).resolve().parent
FROZEN = HERE.parents[2] / "experiments" / "R-OP-01" / "src"
SEEDS = (1, 2, 3, 4, 5)

#: The rename and the redirect, named rather than hidden. The comparison
#: discounts exactly these and nothing else.
RENAMES = {"Failure": "FailureError"}
IMPORT_REDIRECTS = {"canonical_json": "physgate.state.protocol"}

#: Recorded when the adaptation was made, so a change to either side is visible
#: as a changed number and not only as a failed comparison.
EXPECTED_WORKLOAD_DIGEST = {
    1: "7921c7c0c06f920e70089e6d2defef85cf0f436a07dcf25ea7ad63da63577f1f",
    2: "6a6315925d087c5968c800f534da624f605b1218edce8c2f079f99528646e2d0",
    3: "4b68f4da22957b60c921c28f9258c8b93940f08b1d20549b5da04e3bc1e60740",
    4: "869de43b7ed6b3cdd60b5a1cfc38f19f76b1880c3bbe1f2fc6f2635f3e5b0319",
    5: "17dc452a1b5db97fd62b20944ddec69bc1e6a6088065265616bbb1e76e609389",
}
OPERATIONS_PER_SEED = 1230

DUMP_WORKLOAD = """
import dataclasses, hashlib, json, sys
import generator
w = generator.build(int(sys.argv[1]))
blob = {
    "seed": w.seed,
    "nodes": w.nodes,
    "deepest_node_id": w.deepest_node_id,
    "counts": w.counts,
    "legal_payloads": w.legal_payloads,
    "ops": [dataclasses.asdict(o) for o in w.ops],
}
text = json.dumps(blob, sort_keys=True, separators=(",", ":"), default=str)
print(hashlib.sha256(text.encode()).hexdigest(), len(w.ops))
"""

SCORE_WITH_THE_FROZEN_STORE = """
import hashlib, json, shutil, sys, tempfile
from pathlib import Path
import generator, harness
from baseline_store import BaselineStore
root = Path(tempfile.mkdtemp())
try:
    work = generator.build(int(sys.argv[1]))
    store = BaselineStore(root)
    m = harness.run(store, work)
    store.close()
    scored = {
        "seed": m["seed"], "deepest_node": m["deepest_node"],
        "closure_size": m["closure_size"], "workload_counts": m["workload_counts"],
        "c1": m["c1"], "failures": m["failures"], "failure_count": m["failure_count"],
        "n_diff": m["c2_diff_ms"]["n"], "n_traverse": m["c3_traverse_ms"]["n"],
        "n_write": m["write_ms"]["n"], "n_rollback": m["rollback_ms"]["n"],
    }
    text = json.dumps(scored, sort_keys=True, separators=(",", ":"))
    print(hashlib.sha256(text.encode()).hexdigest(), m["failure_count"],
          m["c1"]["legal_accepted"])
finally:
    shutil.rmtree(root, ignore_errors=True)
"""


def run_in(directory: Path, source: str, *args: str) -> list[str]:
    """Run ``source`` in a fresh interpreter whose imports resolve in ``directory``."""
    result = subprocess.run(
        [sys.executable, "-c", source, *args],
        cwd=directory,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.split()


def test_the_frozen_tree_is_where_we_think_it_is() -> None:
    for name in ("generator.py", "harness.py", "protocol.py", "baseline_store.py"):
        assert (FROZEN / name).is_file(), FROZEN / name


# --- proof 1: the operations are byte-identical ------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_the_adapted_generator_emits_the_frozen_operation_sequence(seed: int) -> None:
    frozen = run_in(FROZEN, DUMP_WORKLOAD, str(seed))
    adapted = run_in(HERE, DUMP_WORKLOAD, str(seed))

    assert frozen[0] == EXPECTED_WORKLOAD_DIGEST[seed], "the frozen side moved"
    assert adapted[0] == frozen[0], "the adapted generator produces a different workload"
    assert int(frozen[1]) == OPERATIONS_PER_SEED
    assert int(adapted[1]) == OPERATIONS_PER_SEED


# --- proof 2: the code is identical ------------------------------------------


def test_the_adapted_generator_is_the_frozen_generator() -> None:
    assert normalised(HERE / "generator.py") == normalised(FROZEN / "generator.py")


def test_the_adapted_harness_is_the_frozen_harness() -> None:
    # The redirect is applied to both sides: it says "treat this symbol as coming
    # from the same place", which is a statement about the comparison and not a
    # change made to either file.
    assert normalised(HERE / "harness.py", import_redirects=IMPORT_REDIRECTS) == normalised(
        FROZEN / "harness.py", renames=RENAMES, import_redirects=IMPORT_REDIRECTS
    )


def test_the_comparison_notices_a_changed_constant() -> None:
    """The normaliser is the thing everything else rests on, so it is tested too."""
    original = (FROZEN / "generator.py").read_text()
    assert "N_CROSS_ROLE = 150" in original
    tampered = original.replace("N_CROSS_ROLE = 150", "N_CROSS_ROLE = 149", 1)
    assert _differs_from_frozen_generator(tampered)


def test_the_comparison_notices_an_inverted_condition() -> None:
    original = (FROZEN / "generator.py").read_text()
    assert "if nid in seen or nid not in nodes:" in original
    tampered = original.replace(
        "if nid in seen or nid not in nodes:", "if nid not in seen or nid in nodes:", 1
    )
    assert _differs_from_frozen_generator(tampered)


def test_the_comparison_notices_a_reordered_statement() -> None:
    original = (FROZEN / "harness.py").read_text()
    assert '        wanted_reason = op.expect.split(":", 1)[1]\n' in original
    tampered = original.replace(
        '            wanted_reason = op.expect.split(":", 1)[1]\n            if result.accepted:\n',
        "            if result.accepted:\n"
        '                wanted_reason = op.expect.split(":", 1)[1]\n',
        1,
    )
    assert tampered != original
    assert _differs_from_frozen_harness(tampered)


def test_the_import_redirect_does_not_hide_a_different_function() -> None:
    """The redirect discounts where a symbol comes from, never which symbol it is.

    This is the first thing to doubt about it, so it is the first thing tested:
    a redirect that also let the symbol change would let this comparison approve
    a harness that scores with something else entirely.
    """
    original = (FROZEN / "harness.py").read_text()
    assert "canonical_json(store.read_node(op.node_id))" in original
    swapped = original.replace(
        "canonical_json(store.read_node(op.node_id))",
        "repr(store.read_node(op.node_id))",
        1,
    )
    assert _differs_from_frozen_harness(swapped)


def test_the_import_redirect_does_not_hide_a_different_imported_name() -> None:
    original = (FROZEN / "harness.py").read_text()
    renamed_import = original.replace(
        "from protocol import canonical_json",
        "from protocol import canonical_json as _cj\ncanonical_json = _cj",
        1,
    )
    assert _differs_from_frozen_harness(renamed_import)


def test_the_comparison_ignores_reformatting_and_comments(tmp_path: Path) -> None:
    """The two things it is meant to ignore, shown to be ignored."""
    original = (FROZEN / "generator.py").read_text()
    noisy = "# a comment that changes nothing\n" + original.replace(
        "N_NODES = 200", "N_NODES = (\n    200\n)", 1
    )
    candidate = tmp_path / "generator.py"
    candidate.write_text(noisy)
    assert normalised(candidate) == normalised(FROZEN / "generator.py")


def _differs_from_frozen_generator(source: str) -> bool:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp) / "generator.py"
        candidate.write_text(source)
        return normalised(candidate) != normalised(FROZEN / "generator.py")


def _differs_from_frozen_harness(source: str) -> bool:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        candidate = Path(tmp) / "harness.py"
        candidate.write_text(source)
        return normalised(candidate, renames=RENAMES) != normalised(
            FROZEN / "harness.py", renames=RENAMES
        )


# --- proof 3: the scoring is identical ---------------------------------------


@pytest.mark.integration
@pytest.mark.parametrize("seed", SEEDS)
def test_the_adapted_harness_scores_the_frozen_workload_identically(
    seed: int, tmp_path: Path
) -> None:
    """Both runs use the frozen store and the frozen generator, so only the harness differs."""
    mixed = tmp_path / "frozen_with_the_adapted_harness"
    shutil.copytree(FROZEN, mixed)
    shutil.copy(HERE / "harness.py", mixed / "harness.py")
    # The adapted harness takes this from the promoted package; give the copy the
    # frozen spelling back so this run touches nothing but the harness itself.
    text = (mixed / "harness.py").read_text()
    (mixed / "harness.py").write_text(
        text.replace(
            "from physgate.state.protocol import canonical_json",
            "from protocol import canonical_json",
            1,
        )
    )

    frozen = run_in(FROZEN, SCORE_WITH_THE_FROZEN_STORE, str(seed))
    adapted = run_in(mixed, SCORE_WITH_THE_FROZEN_STORE, str(seed))

    assert adapted[0] == frozen[0], "the adapted harness scores differently"
    assert int(frozen[1]) == 0, "the frozen run itself must be clean"
    assert int(frozen[2]) == 780


@pytest.mark.integration
def test_the_frozen_tree_was_not_touched_by_any_of_this() -> None:
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", str(FROZEN.parent.parent)],
        cwd=HERE,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "", result.stdout
