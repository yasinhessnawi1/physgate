"""A fixed partition of the scoring tests into shards, and the proof that it is complete.

The scoring tests run in their own environment and, on one runner, took between 11 and 18
minutes on identical code. CI therefore runs them in shards, one job each. A shard is a set
of whole test files: the sorted list of every file pytest would collect under
``tests/scoring``, dealt out by position, file ``i`` going to shard ``i % count``. The deal is
deterministic, depends on nothing but the file names, and cannot leave a file out or put it in
two shards, because every file is dealt exactly once.

    scoring_shard.py FILES INDEX COUNT   print the files of shard INDEX (0-based) of COUNT
    scoring_shard.py VERIFY COUNT        fail unless the shards are disjoint and their union
                                         is every test file under tests/scoring
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCORING = ROOT / "tests" / "scoring"


def test_files() -> list[str]:
    """Every file pytest collects under tests/scoring, by the default collection patterns."""
    found = {
        path.relative_to(ROOT).as_posix()
        for pattern in ("test_*.py", "*_test.py")
        for path in SCORING.rglob(pattern)
    }
    return sorted(found)


def shard(files: list[str], index: int, count: int) -> list[str]:
    """The files dealt to shard ``index`` of ``count``."""
    return [name for position, name in enumerate(files) if position % count == index]


def verify(count: int) -> None:
    """Fail unless the shards are disjoint and together hold every test file."""
    files = test_files()
    if not files:
        raise SystemExit("no scoring test file was found")
    dealt = [name for index in range(count) for name in shard(files, index, count)]
    if len(dealt) != len(set(dealt)):
        raise SystemExit("a test file is in two shards")
    if set(dealt) != set(files):
        raise SystemExit("a test file is in no shard")
    sizes = ", ".join(str(len(shard(files, index, count))) for index in range(count))
    print(f"{len(files)} scoring test files, {count} shards of {sizes}: a complete partition")


def main(argv: list[str]) -> None:
    """Run the command named on the command line."""
    if len(argv) == 4 and argv[1] == "FILES":
        index, count = int(argv[2]), int(argv[3])
        if not 0 <= index < count:
            raise SystemExit("INDEX must be at least 0 and below COUNT")
        selected = shard(test_files(), index, count)
        if not selected:
            raise SystemExit("this shard holds no file")
        print("\n".join(selected))
    elif len(argv) == 3 and argv[1] == "VERIFY":
        verify(int(argv[2]))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
