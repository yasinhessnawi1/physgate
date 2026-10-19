"""R-PG-02, R3, before the run: nothing that states an answer is readable where a reviewer runs.

Usage (from the repository root):

    uv run python -I r3_scan.py --checkout <dir> --root <review-root> [--root ...]
        --set <name>=<corpus-dir> [--set ...] [--place <dir> ...]

Read-only; prints one JSON line and exits 0 only if every check holds:

- each review root passes the reviewers' own check (no telltale word in its path, the
  substring "physgate" included, and not inside a git checkout), is new or empty, and neither
  contains nor lies inside another review root;
- no set, no other named place (the practice runs, the run directories, the installation,
  the dry run) and no checkout contains a review root or lies inside one;
- no file of the library a reviewer is shown (``knowledge/``) equals a file of any set, and
  none names a set's label or manifest digest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _nested(a: Path, b: Path) -> bool:
    return a == b or a in b.parents or b in a.parents


def scan(
    checkout: Path, roots: list[Path], sets: dict[str, Path], places: list[Path]
) -> dict[str, Any]:
    """Every R3 check over the named roots, sets and places; ``problems`` empty if all hold."""
    from physgate.evaluation.inject.corpus import load_corpus
    from physgate.reviewers.places import require_review_root

    problems: list[str] = []
    checkout, roots = checkout.resolve(), [r.expanduser().resolve() for r in roots]
    if not roots:
        problems.append("no review root named")
    for n, root in enumerate(roots):
        try:
            require_review_root(root)
        except Exception as exc:  # noqa: BLE001 - the reviewers' own refusal, reported whole
            problems.append(f"review root {root}: {exc}")
        if "physgate" in str(root).casefold():
            problems.append(f"review root {root} holds the substring 'physgate'")
        if root.exists() and any(root.iterdir()):
            problems.append(f"review root {root} exists and is not empty")
        for other in roots[n + 1 :]:
            if _nested(root, other):
                problems.append(f"review roots {root} and {other} contain one another")
    answers: set[str] = set()
    labels: list[str] = []
    files_per_set: dict[str, int] = {}
    named = {f"set {k}": v.resolve() for k, v in sets.items()}
    named.update({f"place {p}": p.expanduser().resolve() for p in places})
    named["checkout"] = checkout
    for name, place in named.items():
        for root in roots:
            if _nested(place, root):
                problems.append(f"{name} and the review root {root} contain one another")
    for name, directory in sets.items():
        corpus = load_corpus(directory.resolve())
        files = [p for p in directory.resolve().rglob("*") if p.is_file()]
        files_per_set[name] = len(files)
        answers |= {_sha(p) for p in files}
        labels += [corpus.manifest_sha256, corpus.manifest.label]
    shown = [p for p in (checkout / "knowledge").rglob("*") if p.is_file()]
    leaked = [str(p.relative_to(checkout)) for p in shown if _sha(p) in answers]
    if leaked:
        problems.append(f"library files equal to a set's files: {leaked[:5]}")
    for p in shown:
        text = p.read_text(errors="replace")
        if any(mark in text for mark in labels):
            problems.append(f"{p.relative_to(checkout)} names a set")
    return {
        "review_roots": [str(r) for r in roots],
        "sets": files_per_set,
        "places_checked": len(named),
        "library_files_checked": len(shown),
        "problems": problems,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checkout", required=True, type=Path)
    parser.add_argument("--root", action="append", default=[], type=Path)
    parser.add_argument("--set", action="append", default=[], dest="sets")
    parser.add_argument("--place", action="append", default=[], type=Path)
    args = parser.parse_args(argv)
    sets = {}
    for item in args.sets:
        name, sep, path = item.partition("=")
        if not sep or not name or not path:
            parser.error(f"--set takes <name>=<dir>, not {item!r}")
        sets[name] = Path(path).expanduser()
    try:
        out = scan(args.checkout, args.root, sets, args.place)
    except Exception as exc:  # noqa: BLE001 - a set that does not load is a refusal
        out = {"problems": [f"{type(exc).__name__}: {exc}"]}
    print(json.dumps(out, sort_keys=True))
    return 1 if out["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
