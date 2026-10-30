r"""R-PG-03, CRITERIA.md §2.4 and §2.5 item 5: the authors' table, the reviewers' sheet, fresh-v1c.

Usage (from the checkout at the run commit, or at master for a trial)::

    python -I sheet_check.py table
    python -I sheet_check.py convert --into <new dir> [--reference <sheet>]
    python -I sheet_check.py corpus <corpus dir> --sheet-sha256 <"Sheet filled"'s digest>
    python -I sheet_check.py assemble-v1c --into <new sets dir> --work <new dir>
        [--reference <sheet>]

- ``table``: R-PG-02's authors' table held to ``29f9568c…``; the one edit (row R6.05's note,
  "answered" read as "responded") made by script and held to ``0573ef04…``; and the word-level
  diff of the two, which must show exactly one change.
- ``convert``: §2.4's call, fixed in the criteria, run on the edited table into ``--into``::

      parts_sheet_sources.py <the edited table> <sources.json> \
          --keep-values-from <R-PG-02's sources.json, bc1e5ec1…> --prose drop \
          --drop-prose-line-sha256 4c7844dc…

  for fresh-v2 (from R-PG-02's frozen table) and for ``fresh-v1c`` (from the tuning set's own
  table, which must be the same bytes, and the tuning set's sheet, ``bc1e5ec1…``). Prints the
  counts and the digest of each, and §2.4's outcome against the drafter's probe: ``recorded``
  (every count and the digest equal), ``digest differs`` (every count equal: the byte-level
  difference is printed against ``--reference``, a sheet at the probe's digest, which is then
  required), or ``not used`` (a count differs, or the converter refused: its printed reason is
  shown). The two sheets must be the same bytes.
- ``corpus``: §2.5 item 5 on one corpus: the converter re-run on the corpus's own table
  reproduces its ``sources.json``, and both equal "Sheet filled"'s digest.
- ``assemble-v1c``: ``fresh-v1c``'s two corpora (§6.4 item 10), split by R-PG-02's batches:
  ``a01``-``a20`` and ``a21``-``a40`` of the tuning set, held to its manifest, base and artefacts
  byte for byte, with the edited table as ``parts_sheet.md`` and the converted sheet as
  ``sources.json``; each loads under its new manifest and is complete at five per class.

Counts and digests only: no row, cell, prose line or node is printed.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402

#: The one edit (§2.4).
EDIT_ROW, EDIT_OLD, EDIT_NEW = "R6.05", "answered", "responded"
#: The tuning set's batches (§6.4 item 10): R-PG-02's two authoring batches.
BATCHES = {"fresh-v1c-a01-a20": (1, 20), "fresh-v1c-a21-a40": (21, 40)}
LABEL_V1C = (
    "fresh-v1c {batch}: the tuning set's base and artefacts {first} to {last} byte for byte, with "
    "the complete parts sheet converted from the edited authors' table"
)
#: The counts §2.4's probe recorded, by the names the converter prints them under or this script
#: counts them under.
COUNT_KEYS = tuple(common.PROBE_COUNTS)


class RefusedError(Exception):
    """A fact is not the one §2.4 states."""


def _cells(line: str) -> list[str]:
    """A table line's cells, as the converter reads them (an escaped pipe kept in its cell)."""
    inner = line.strip().removeprefix("|")
    inner = inner[:-1] if inner.endswith("|") and not inner.endswith("\\|") else inner
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", inner)]


def edit_table(table: bytes) -> bytes:
    """The table with §2.4's one edit made: the word in row R6.05's note, and nothing else.

    Raises:
        RefusedError: the row is not on exactly one line, has not seven cells, or the word is not in
            its note exactly once as a whole word and nowhere else in the table.
    """
    text = table.decode("utf-8")
    lines = text.split("\n")
    lead = re.compile(rf"^\|\s*{re.escape(EDIT_ROW)}\s*\|")
    where = [i for i, line in enumerate(lines) if lead.match(line)]
    if len(where) != 1:
        raise RefusedError(f"row {EDIT_ROW} is on {len(where)} lines of the table, not one")
    line = lines[where[0]]
    cells = _cells(line)
    if len(cells) != 7:
        raise RefusedError(f"row {EDIT_ROW} has {len(cells)} cells, not seven")
    word = re.compile(rf"\b{re.escape(EDIT_OLD)}\b")
    if len(word.findall(cells[6])) != 1 or len(word.findall(text)) != 1:
        raise RefusedError(
            f"the word is not in row {EDIT_ROW}'s note exactly once, and nowhere else"
        )
    lines[where[0]] = word.sub(EDIT_NEW, line, count=1)
    return "\n".join(lines).encode("utf-8")


def word_diff(before: bytes, after: bytes) -> list[dict[str, Any]]:
    """Every change between two texts read as words and punctuation, as counts of tokens."""
    split = re.compile(r"\w+|[^\w\s]")
    a, b = split.findall(before.decode()), split.findall(after.decode())
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag != "equal":
            out.append({"kind": tag, "removed": i2 - i1, "added": j2 - j1})
    return out


def table_facts(repo: Path, table_rel: str = common.R_PG_02_TABLE) -> tuple[bytes, dict[str, Any]]:
    """R-PG-02's table, its edit, and the diff, each held to §2.4.

    Raises:
        RefusedError: a digest or the diff is not §2.4's.
    """
    table = (repo / table_rel).read_bytes()
    if common.sha256_bytes(table) != common.TABLE_SHA256:
        raise RefusedError("the authors' table is not R-PG-02's (29f9568c…)")
    edited = edit_table(table)
    diff = word_diff(table, edited)
    facts = {
        "table_sha256": common.TABLE_SHA256,
        "edited_sha256": common.sha256_bytes(edited),
        "edited_bytes": len(edited),
        "word_level_changes": diff,
    }
    if facts["edited_sha256"] != common.EDITED_TABLE_SHA256:
        raise RefusedError("the edited table is not 0573ef04…")
    if diff != [{"kind": "replace", "removed": 1, "added": 1}]:
        raise RefusedError("the word-level diff does not show exactly one change of one word")
    return edited, facts


def converter_argv(repo: Path, table: Path, out: Path, keep: Path) -> list[str]:
    """§2.4's call, its file arguments filled in, and nothing else."""
    return [
        sys.executable,
        str(repo / common.CONVERTER),
        str(table),
        str(out),
        "--keep-values-from",
        str(keep),
        "--prose",
        "drop",
        "--drop-prose-line-sha256",
        common.DROP_LINE_SHA256,
    ]


def run_converter(repo: Path, table: Path, out: Path, keep: Path) -> dict[str, Any]:
    """§2.4's call: its exit, its printed counts, or its printed reason."""
    done = subprocess.run(
        converter_argv(repo, table, out, keep), capture_output=True, text=True, check=False
    )
    return {
        "exit": done.returncode,
        "printed": printed_counts(done.stdout),
        "reason": done.stderr.strip()[-600:],
    }


def printed_counts(stdout: str) -> dict[str, int]:
    """The converter's printed counts: each line is names and whole numbers, in turn."""
    found: dict[str, int] = {}
    for line in stdout.splitlines():
        words = line.split()
        for name, value in zip(words[::2], words[1::2], strict=False):
            if value.isdigit():
                found[name] = int(value)
    return found


def sheet_counts(sheet: bytes) -> dict[str, Any]:
    """The probe's measures of a converted sheet: rows, numbers, values, notes, telltales, size."""
    from physgate.evaluation.inject.corpus import telltales

    data = json.loads(sheet)
    rows = list(data["rows"].values())
    words = sum(len(telltales(str(r.get(k, "")))) for r in rows for k in ("given", "note"))
    return {
        "rows": len(rows),
        "rows_with_a_number": sum(r.get("value") is not None for r in rows),
        "rows_with_given": sum("given" in r for r in rows),
        "rows_with_given_only": sum(r.get("value") is None and "given" in r for r in rows),
        "rows_with_neither": sum(r.get("value") is None and "given" not in r for r in rows),
        "notes": sum("note" in r for r in rows),
        "telltale_words": words,
        "bytes": len(sheet),
        "sha256": common.sha256_bytes(sheet),
    }


def outcome(found: dict[str, Any]) -> str:
    """§2.4's procedure: recorded, digest differs, or not used."""
    if found.get("refused") is not None:
        return "not used"
    if any(found["counts"].get(k) != v for k, v in common.PROBE_COUNTS.items()):
        return "not used"
    if found["counts"]["sha256"] != common.PROBE_SHEET_SHA256:
        return "digest differs"
    return "recorded"


def byte_difference(a: bytes, b: bytes) -> dict[str, Any]:
    """Where two sheets differ, by line number and byte counts only."""
    la, lb = a.split(b"\n"), b.split(b"\n")
    differ = [i + 1 for i, (x, y) in enumerate(zip(la, lb, strict=False)) if x != y]
    return {
        "lines": [len(la), len(lb)],
        "lines_differing": differ[:50],
        "lines_differing_count": len(differ) + abs(len(la) - len(lb)),
        "bytes": [len(a), len(b)],
    }


def convert_one(
    repo: Path, table: bytes, keep: Path, into: Path, name: str
) -> tuple[bytes | None, dict[str, Any]]:
    """The call on one edited table into ``into/<name>``; its counts and outcome."""
    where = into / name
    where.mkdir(parents=True)
    table_path = where / common.TABLE_NAME
    table_path.write_bytes(table)
    out = where / common.SHEET_NAME
    ran = run_converter(repo, table_path, out, keep)
    found: dict[str, Any] = {"converter_exit": ran["exit"], "converter_printed": ran["printed"]}
    if ran["exit"] != 0 or not out.is_file():
        found["refused"] = ran["reason"] or f"exit {ran['exit']}"
        found["outcome"] = outcome(found)
        return None, found
    sheet = out.read_bytes()
    counts = sheet_counts(sheet)
    printed = ran["printed"]
    counts["prose_lines_dropped"] = printed.get("prose-dropped")
    # The converter's own counts, beside this script's: any disagreement is a refusal of the sheet.
    theirs = {
        "rows": printed.get("rows"),
        "rows_with_a_number": printed.get("number"),
        "rows_with_given": printed.get("given"),
        "rows_with_given_only": printed.get("given-only"),
        "rows_with_neither": printed.get("empty"),
        "notes": printed.get("notes"),
    }
    if any(counts[k] != v for k, v in theirs.items()):
        found["refused"] = "the converter's printed counts are not the sheet's own"
    found["counts"] = counts
    found["outcome"] = outcome(found)
    return sheet, found


def convert(repo: Path, into: Path, reference: Path | None = None) -> dict[str, Any]:
    """§2.4's call for fresh-v2 and for fresh-v1c, held to the probe and to each other.

    Raises:
        RefusedError: an input is not at its digest, or ``into`` exists.
    """
    if into.exists():
        raise RefusedError("the output directory exists: nothing is written over")
    edited, facts = table_facts(repo)
    tuning = repo / common.TUNING_SET
    keep = tuning / common.SHEET_NAME
    if common.sha256_file(tuning / "MANIFEST.json") != common.TUNING_SET_MANIFEST:
        raise RefusedError("the tuning set's manifest is not e76a4904…")
    if common.sha256_file(keep) != common.KEEP_FROM_SHA256:
        raise RefusedError("R-PG-02's sources.json is not bc1e5ec1…")
    own = (tuning / common.TABLE_NAME).read_bytes()
    if common.sha256_bytes(own) != common.TABLE_SHA256:
        raise RefusedError("the tuning set's table is not R-PG-02's (29f9568c…)")
    v1c_edited = edit_table(own)
    sheets: dict[str, bytes | None] = {}
    out: dict[str, Any] = {"table": facts}
    for name, table in (("fresh-v2", edited), ("fresh-v1c", v1c_edited)):
        sheets[name], out[name] = convert_one(repo, table, keep, into, name)
    out["fresh_v1c_table_is_fresh_v2_s"] = v1c_edited == edited
    out["fresh_v1c_sheet_is_fresh_v2_s"] = (
        sheets["fresh-v2"] is not None and sheets["fresh-v2"] == sheets["fresh-v1c"]
    )
    if reference is not None and sheets["fresh-v2"] is not None:
        ref = reference.read_bytes()
        if common.sha256_bytes(ref) != common.PROBE_SHEET_SHA256:
            raise RefusedError("the reference sheet is not at the probe's digest")
        out["byte_difference_from_the_probe"] = byte_difference(ref, sheets["fresh-v2"])
    out["holds"] = (
        out["fresh-v2"]["outcome"] in ("recorded", "digest differs")
        and out["fresh_v1c_sheet_is_fresh_v2_s"]
        and out["fresh_v1c_table_is_fresh_v2_s"]
    )
    if (
        out["fresh-v2"]["outcome"] == "digest differs"
        and "byte_difference_from_the_probe" not in out
    ):
        out["holds"] = False
        out["refused"] = (
            "the digest differs from the probe's: the byte-level difference is printed by script "
            "and published (§2.4), so name --reference, a sheet at the probe's digest"
        )
    return out


def corpus_check(repo: Path, corpus: Path, sheet_sha256: str, into: Path) -> dict[str, Any]:
    """§2.5 item 5: the converter on the corpus's table gives its sheet, at "Sheet filled"'s digest.

    Raises:
        RefusedError: the corpus's table is not the edited table.
    """
    table = (corpus / common.TABLE_NAME).read_bytes()
    if common.sha256_bytes(table) != common.EDITED_TABLE_SHA256:
        raise RefusedError("the corpus's table is not the edited authors' table (0573ef04…)")
    keep = repo / common.TUNING_SET / common.SHEET_NAME
    if common.sha256_file(keep) != common.KEEP_FROM_SHA256:
        raise RefusedError("R-PG-02's sources.json is not bc1e5ec1…")
    if into.exists():
        raise RefusedError("the output directory exists: nothing is written over")
    into.mkdir(parents=True)
    out = into / common.SHEET_NAME
    ran = run_converter(repo, corpus / common.TABLE_NAME, out, keep)
    found: dict[str, Any] = {"converter_exit": ran["exit"]}
    if ran["exit"] != 0:
        found.update(refused=ran["reason"], holds=False)
        return found
    again = common.sha256_file(out)
    have = common.sha256_file(corpus / common.SHEET_NAME)
    found.update(
        reproduced=again,
        corpus_sheet=have,
        filled=sheet_sha256,
        holds=again == have == sheet_sha256,
    )
    return found


def assemble_v1c(repo: Path, into: Path, sheet: bytes, edited: bytes) -> dict[str, Any]:
    """fresh-v1c's two corpora: the tuning set's batches with the complete sheet.

    Raises:
        RefusedError: the tuning set is not at its manifest, a corpus exists, or one does not load
            complete.
    """
    from physgate.evaluation.inject.corpus import (
        load_corpus,
        manifest_for,
        require_complete,
        write_manifest,
    )

    tuning = repo / common.TUNING_SET
    if common.sha256_file(tuning / "MANIFEST.json") != common.TUNING_SET_MANIFEST:
        raise RefusedError("the tuning set's manifest is not e76a4904…")
    source = load_corpus(tuning)  # every file held to its manifest
    out: dict[str, Any] = {}
    for name, (first, last) in BATCHES.items():
        where = into / name
        if where.exists():
            raise RefusedError(f"{name} exists: a corpus is never written over")
        ids = [f"a{k:02d}" for k in range(first, last + 1)]
        have = {a.id for a in source.artefacts}
        if not set(ids) <= have:
            raise RefusedError(f"the tuning set lacks a revision of {name}'s batch")
        (where / "artefacts").mkdir(parents=True)
        shutil.copyfile(tuning / "base.json", where / "base.json")
        for aid in ids:
            shutil.copyfile(
                tuning / "artefacts" / f"{aid}.json", where / "artefacts" / f"{aid}.json"
            )
        (where / common.TABLE_NAME).write_bytes(edited)
        (where / common.SHEET_NAME).write_bytes(sheet)
        label = LABEL_V1C.format(batch=name.removeprefix("fresh-v1c-"), first=ids[0], last=ids[-1])
        write_manifest(
            where, manifest_for(where, label=label, author_model=source.manifest.author_model)
        )
        corpus = load_corpus(where)
        require_complete(corpus, per_class=common.PER_CLASS_BATCH)
        out[name] = {
            "artefacts": len(corpus.artefacts),
            "manifest_sha256": corpus.manifest_sha256,
            "sheet_sha256": common.sha256_bytes(corpus.parts_sheet),
        }
    return out


def main(argv: list[str] | None = None) -> int:
    """One subcommand; counts and digests only; exit 0 only if it holds."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("table")
    c = sub.add_parser("convert")
    c.add_argument("--into", type=Path, required=True)
    c.add_argument("--reference", type=Path)
    k = sub.add_parser("corpus")
    k.add_argument("corpus", type=Path)
    k.add_argument("--sheet-sha256", required=True)
    k.add_argument("--into", type=Path, required=True)
    a = sub.add_parser("assemble-v1c")
    a.add_argument("--into", type=Path, required=True)
    a.add_argument("--work", type=Path, required=True)
    a.add_argument("--reference", type=Path)
    parser.add_argument("--repo", type=Path, default=common.REPO)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    try:
        if args.cmd == "table":
            _, facts = table_facts(repo)
            found: dict[str, Any] = {**facts, "holds": True}
        elif args.cmd == "convert":
            found = convert(repo, args.into, args.reference)
        elif args.cmd == "corpus":
            found = corpus_check(repo, args.corpus.resolve(), args.sheet_sha256, args.into)
        else:
            made = convert(repo, args.work, args.reference)
            if not made["holds"] or made["fresh-v1c"]["outcome"] not in (
                "recorded",
                "digest differs",
            ):
                print(json.dumps({"refused": "the sheet does not hold", **made}, sort_keys=True))
                return 1
            edited, _ = table_facts(repo)
            sheet = (args.work / "fresh-v1c" / common.SHEET_NAME).read_bytes()
            found = {"corpora": assemble_v1c(repo, args.into, sheet, edited), "holds": True}
    except RefusedError as exc:
        print(json.dumps({"refused": str(exc)}))
        return 1
    print(json.dumps(found, sort_keys=True))
    return 0 if found.get("holds") else 1


if __name__ == "__main__":
    sys.exit(main())
