"""The operator UI's read routes over the curated library: what the next run from here reads.

Five reads, each over the library slot of the allowlist and nothing else:

- the listing: every role's standards, skill and bounds file, with its size, digest and state,
  the rubrics' promotion records, and how many promotions and staged candidates there are;
- one standards, skill or bounds file, with its text and every promotion line naming it;
- the staged candidates, without their content;
- one staged candidate with what promoting it would do: its effect, the destination's
  fingerprints now and after, and the changed lines;
- the bounds tables' ranges and envelopes, and the catalogue's energy-store classes.

**Nothing here writes, and nothing here promotes.** Promotion is a person's act at a terminal.
A staged candidate is found by promotion's own finder, and what promoting it would write comes
from promotion's own pure function, so the screen describes exactly the write the terminal
would make. Promotion's helpers that make directories are never called: the destination is read
here, read-only.

**The state of a file is chosen by its bytes, never by time.** The promotion log is appended,
but its timestamps are not in order. The promotion that wrote a file is the last line, in log
order, that names the file and whose digest equals the file's bytes now. A line that recorded no
digest never wrote anything that can be shown.

**What is never sent:** a canary (every promotion line is sent without one, whatever its kind);
any byte of the reviewers' folder (the allowlist withholds it; the rubrics are listed from the
promotion log alone); the target of a link (a link inside the library is refused, as the
library's own readers refuse it).

**How a file is read.** The path is built from the library and fixed names, never from a
request. It is judged by the allowlist (a refusal is a 403, or a row's error in a listing).
Every component below the library is then checked to be no link, the file to be a regular file,
and its identity recorded. It is opened by its full path without following a link, and the
opened file must be the one judged. So a file swapped between the judgement and the open is
refused. A swap of a directory above it is the same-user window every read route has: the
request's guard then refuses the open, and that refusal is answered as a 403 too, never a 500.
A file larger than the cap is refused with a sentence. A file or folder whose permissions refuse
the server is refused in those words, never as a swap. A refusal names a library file as the log
does (``knowledge/...``), never by its place on the machine.
"""

from __future__ import annotations

import difflib
import errno
import hashlib
import json
import os
import stat
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from physgate.gate.bounds_table import BOUNDS_NAME, Bounds, Envelope, Range, load_table
from physgate.gate.catalogue import STORE_CLASSES, catalogue_digest, kind_of
from physgate.gate.exceptions import GateError
from physgate.gate.laws import LawTable
from physgate.knowledge.exceptions import KnowledgeError, RoleNameError
from physgate.knowledge.loader import always_loaded
from physgate.knowledge.promote import (
    PROMOTIONS_NAME,
    SKILL_NAME,
    STANDARDS_NAME,
    find_staged,
    promotion_bytes,
)
from physgate.knowledge.staging import Candidate, Kind
from physgate.ui.exceptions import GuardRefusedError, NotFoundError, PathRefusedError, UIError
from physgate.ui.routes import PARAMETERS, Context, Handler, Response, json_response

#: The most bytes one library file may hold to be read here.
CAP = 1 << 20

#: The library files a role's folder may hold, by kind.
LIBRARY_FILES: Mapping[str, str] = {
    "standards": STANDARDS_NAME,
    "skill": SKILL_NAME,
    "bounds": BOUNDS_NAME,
}

#: The staged kinds listed here; rubric drafts lie in the reviewers' tree and are never listed.
STAGED_KINDS: tuple[Kind, ...] = ("standards", "skill", "antipattern")

#: Every kind promotion's finder probes, in its own order.
FINDER_KINDS: tuple[Kind, ...] = ("standards", "skill", "antipattern", "rubric")

#: The folder of staged candidates inside the library.
STAGING_DIR = "staging"

#: Promotion lines name their destination relative to the checkout, under this folder.
RECORDED_ROOT = "knowledge"

#: What a store class's rate is per: the field's own name says per hour.
PER_HOUR = "1/h"

#: How the changed lines show a carriage return that ends a line, so that a change of line
#: endings alone is seen (U+240D, the symbol for a carriage return).
CARRIAGE_RETURN = "\u240d"

#: The line a unified diff puts after a line that ends the file with no newline.
NO_NEWLINE = "\\ No newline at end of file"

#: The law table the screen's digest is taken with: none. The table is a file outside the roots a
#: request may read, so this digest is the catalogue's alone, which is what a gate result's digest
#: is while no law is in the table; a result's own digest also names the laws that judged it.
NO_LAWS = LawTable(laws={}, sha256="", path="")

#: How the request's guard ends its refusal of a read outside every root it may read.
GUARD_READ_REFUSAL = "outside the roots it may read"


# -- errors as sentences ---------------------------------------------------------------------


def _sentence(exc: ValidationError) -> str:
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"{where}: {first['msg']}" if where else str(first["msg"])


@contextmanager
def _as_sentences() -> Iterator[None]:
    """Turn the knowledge layer's, the schema's and the decoders' errors into refusals (422)."""
    try:
        yield
    except KnowledgeError as exc:
        raise UIError(str(exc), **exc.context) from None
    except ValidationError as exc:
        msg = "a record does not read as what it should be"
        raise UIError(msg, reason=_sentence(exc)) from None
    except UnicodeDecodeError:
        msg = "the file is not text this page can show (not UTF-8)"
        raise UIError(msg) from None


def _as_recorded(context: Context, error: UIError | GateError) -> None:
    """Name every library path in ``error``'s context as the log does, never absolutely."""
    library = context.allowlist.library
    if library is None:
        return
    where = str(library.path)
    error.context = {
        key: value.replace(where, RECORDED_ROOT) for key, value in error.context.items()
    }


def _route(handler: Callable[[Context, Mapping[str, str]], dict[str, Any]]) -> Handler:
    """A library handler: errors become sentences, the answer is JSON.

    Every path is judged before it is opened, so the request's guard refuses a read only when a
    folder above a judged file was swapped between the judgement and the open: a refusal (403).
    Any other guard refusal is this package's own fault, and is left to the server.
    """

    def run(context: Context, params: Mapping[str, str]) -> Response:
        try:
            with _as_sentences():
                return json_response(handler(context, params))
        except GuardRefusedError as exc:
            if not str(exc).endswith(GUARD_READ_REFUSAL):
                raise
            msg = "the library changed while it was read"
            raise PathRefusedError(msg) from None
        except (UIError, GateError) as exc:
            _as_recorded(context, exc)
            raise

    run.__name__ = run.__qualname__ = handler.__name__
    run.__doc__ = handler.__doc__
    return run


# -- reading one file ------------------------------------------------------------------------


def _library(context: Context) -> Path:
    library = context.allowlist.library
    if library is None:
        msg = "this server reads no library"
        raise NotFoundError(msg)
    return library.path


def _recorded(library: Path, path: Path) -> str:
    """``path`` as the promotion log names it: relative to the checkout, under ``knowledge``."""
    return "/".join((RECORDED_ROOT, *path.relative_to(library).parts))


def _unreadable(exc: OSError, shown: str, *, listing: bool = False) -> PathRefusedError:
    """The operating system's refusal to read or list ``shown``, in words."""
    if exc.errno in (errno.EACCES, errno.EPERM):
        if listing:
            msg = "the server is not permitted to list this folder"
        else:
            msg = "the server is not permitted to read this file, or a folder it lies in"
        return PathRefusedError(msg, path=shown)
    msg = "the server could not list this folder" if listing else "the server could not read this"
    return PathRefusedError(msg, path=shown, reason=os.strerror(exc.errno or 0))


def _open_file(path: str) -> int:
    """Open a judged file for reading, never through a link: a test seam, as the walk's are."""
    return os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)


def _read(context: Context, library: Path, path: Path) -> bytes | None:
    """The bytes of ``path`` inside the library, or ``None`` if it is not there.

    Raises:
        PathRefusedError: the allowlist refuses it; it, or a folder on the way below the
            library, is a link; it is not a regular file; or it changed while it was read.
        UIError: it holds more than the cap.
    """
    shown = _recorded(library, path)
    context.allowlist.resolve(path)
    current = library
    for name in path.relative_to(library).parts:
        current = current / name
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise _unreadable(exc, shown) from None
        if stat.S_ISLNK(st.st_mode):
            msg = "a link inside the library is not read, so where it points is never shown"
            raise PathRefusedError(msg, path=shown)
        if current != path and not stat.S_ISDIR(st.st_mode):
            return None
    if not stat.S_ISREG(st.st_mode):
        msg = "this is not a regular file, so it is not read"
        raise PathRefusedError(msg, path=shown)
    try:
        fd = _open_file(str(path))
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            msg = "a link inside the library is not read, so where it points is never shown"
            raise PathRefusedError(msg, path=shown) from None
        if exc.errno in (errno.EACCES, errno.EPERM):
            raise _unreadable(exc, shown) from None
        msg = "the file changed while it was read"
        raise PathRefusedError(msg, path=shown, reason=os.strerror(exc.errno or 0)) from None
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
            st.st_dev,
            st.st_ino,
        ):
            msg = "the file changed while it was read"
            raise PathRefusedError(msg, path=shown)
        chunks: list[bytes] = []
        size = 0
        while size <= CAP:
            chunk = os.read(fd, min(1 << 16, CAP + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
    finally:
        os.close(fd)
    if size > CAP:
        msg = f"the file is larger than this page reads ({CAP} bytes)"
        raise UIError(msg, path=shown)
    return b"".join(chunks)


def _fingerprint(data: bytes) -> dict[str, Any]:
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


# -- the promotion log -----------------------------------------------------------------------


def _promotions(context: Context, library: Path) -> list[dict[str, Any]]:
    """Every promotion line in log order, each without its canary.

    Raises:
        PathRefusedError: the log is refused.
        UIError: a line that is not a JSON record, named by its number.
    """
    data = _read(context, library, library / PROMOTIONS_NAME)
    if data is None:
        return []
    lines: list[dict[str, Any]] = []
    for number, raw in enumerate(data.decode("utf-8").splitlines(), start=1):
        if not raw:
            continue
        try:
            record = json.loads(raw)
        except (json.JSONDecodeError, RecursionError):
            # A line nested deeper than the parser goes is as unreadable as a torn one.
            record = None
        if not isinstance(record, dict):
            msg = "the promotion log has a line this version cannot read"
            raise UIError(msg, line=str(number))
        lines.append({key: value for key, value in record.items() if key != "canary"})
    return lines


def _names(line: Mapping[str, Any], recorded: str) -> bool:
    return line.get("destination") == recorded


def _wrote(lines: list[dict[str, Any]], sha256: str) -> int | None:
    """The index of the last line, in log order, whose digest is ``sha256``."""
    found = None
    for index, line in enumerate(lines):
        if line.get("sha256") == sha256:
            found = index
    return found


def _state(history: list[dict[str, Any]], wrote: int | None) -> str:
    if not history:
        return "never-promoted"
    if wrote is not None:
        return "matches"
    if all(isinstance(line.get("sha256"), str) for line in history):
        return "differs"
    return "no-digest"


# -- the roles -------------------------------------------------------------------------------


def _is_role(name: str) -> bool:
    """A role by the knowledge layer's own rule, and one a request can name."""
    if PARAMETERS["role"].fullmatch(name) is None:
        return False
    try:
        always_loaded(name)
    except RoleNameError:
        return False
    return True


def _roles(context: Context, library: Path) -> list[str]:
    """The role folders of the library, in name order.

    A name the allowlist refuses (a corpus) and a folder that is a link are left out, as the run
    listing leaves out a refused run. So is a folder holding none of the library's files.
    """
    roles = []
    try:
        names = os.listdir(library)
    except OSError as exc:
        raise _unreadable(exc, RECORDED_ROOT, listing=True) from None
    for name in sorted(names):
        if not _is_role(name):
            continue
        folder = library / name
        try:
            context.allowlist.resolve(folder)
        except PathRefusedError:
            continue
        try:
            st = os.lstat(folder)
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise _unreadable(exc, _recorded(library, folder)) from None
        if not stat.S_ISDIR(st.st_mode):
            continue
        if any(os.path.lexists(folder / file) for file in LIBRARY_FILES.values()):
            roles.append(name)
    return roles


# -- L1: the listing -------------------------------------------------------------------------


@_route
def listing(context: Context, params: Mapping[str, str]) -> dict[str, Any]:
    """Every library file with its state, the rubrics' records, and the counts."""
    library = _library(context)
    lines = _promotions(context, library)
    documents: list[dict[str, Any]] = []
    for role in _roles(context, library):
        for kind, name in LIBRARY_FILES.items():
            path = library / role / name
            row: dict[str, Any] = {"kind": kind, "role": role, "path": _recorded(library, path)}
            try:
                data = _read(context, library, path)
            except (PathRefusedError, UIError) as exc:
                documents.append({**row, "error": str(exc)})
                continue
            if data is None:
                continue
            history = [line for line in lines if _names(line, row["path"])]
            wrote = _wrote(history, hashlib.sha256(data).hexdigest())
            documents.append(
                {
                    **row,
                    **_fingerprint(data),
                    "promotion": None if wrote is None else history[wrote],
                    "state": _state(history, wrote),
                }
            )
    rubrics: dict[str, dict[str, Any]] = {}
    for line in lines:
        if line.get("kind") == "rubric":
            destination = str(line.get("destination"))
            entry = rubrics.setdefault(
                destination,
                {"role": line.get("domain"), "path": destination, "promotions": []},
            )
            entry["promotions"].append(line)
    staged = [row for row in _staged_rows(context, library) if "error" not in row]
    return {
        "library": str(library),
        "documents": documents,
        "rubrics": list(rubrics.values()),
        "promotions": len(lines),
        "staged": len(staged),
    }


# -- L2: one file ----------------------------------------------------------------------------


@_route
def document(context: Context, params: Mapping[str, str]) -> dict[str, Any]:
    """One standards, skill or bounds file: its text and every promotion line naming it."""
    library = _library(context)
    kind, role = params["kind"], params["role"]
    if not _is_role(role):
        msg = "no library file has this role"
        raise NotFoundError(msg, role=role)
    path = library / role / LIBRARY_FILES[kind]
    data = _read(context, library, path)
    if data is None:
        msg = "the library holds no such file"
        raise NotFoundError(msg, kind=kind, role=role)
    text = data.decode("utf-8")
    recorded = _recorded(library, path)
    history = [line for line in _promotions(context, library) if _names(line, recorded)]
    wrote = _wrote(history, hashlib.sha256(data).hexdigest())
    return {
        "kind": kind,
        "role": role,
        "path": recorded,
        **_fingerprint(data),
        "text": text,
        "promotions": history,
        "wrote": wrote,
        "state": _state(history, wrote),
    }


# -- L3: the staged candidates ---------------------------------------------------------------


def _destination(candidate: Candidate, kind: Kind) -> str:
    """Where promotion would write ``candidate``, as the log names it."""
    name = STANDARDS_NAME if kind == "standards" else SKILL_NAME
    return f"{RECORDED_ROOT}/{candidate.domain}/{name}"


def _staged_rows(context: Context, library: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind in STAGED_KINDS:
        folder = library / STAGING_DIR / kind
        try:
            if _read_folder(context, library, folder) is None:
                continue
        except PathRefusedError as exc:
            rows.append({"name": _recorded(library, folder), "kind": kind, "error": str(exc)})
            continue
        try:
            names = os.listdir(folder)
        except OSError as exc:
            error = _unreadable(exc, _recorded(library, folder), listing=True)
            rows.append({"name": _recorded(library, folder), "kind": kind, "error": str(error)})
            continue
        for name in sorted(names):
            if not name.endswith(".json"):
                continue
            rows.append(_staged_row(context, library, folder / name, kind))
    return rows


def _read_folder(context: Context, library: Path, folder: Path) -> Path | None:
    """``folder`` if it is a real folder inside the library, ``None`` if it is not there."""
    context.allowlist.resolve(folder)
    current = library
    for name in folder.relative_to(library).parts:
        current = current / name
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise _unreadable(exc, _recorded(library, folder)) from None
        if stat.S_ISLNK(st.st_mode):
            msg = "a link inside the library is not read, so where it points is never shown"
            raise PathRefusedError(msg, path=_recorded(library, folder))
        if not stat.S_ISDIR(st.st_mode):
            return None
    return folder


def _staged_row(context: Context, library: Path, path: Path, kind: Kind) -> dict[str, Any]:
    row: dict[str, Any] = {"name": path.name, "kind": kind}
    if PARAMETERS["candidate"].fullmatch(path.stem) is None:
        return {**row, "error": "the file is not named as staging names a candidate"}
    try:
        data = _read(context, library, path)
    except (PathRefusedError, UIError) as exc:
        return {**row, "error": str(exc)}
    if data is None:
        return {**row, "error": "the candidate went while it was read"}
    try:
        candidate = Candidate.model_validate_json(data.decode("utf-8"))
    except ValidationError as exc:
        return {**row, "error": f"the file does not read as a candidate: {_sentence(exc)}"}
    except UnicodeDecodeError:
        return {**row, "error": "the file does not read as a candidate: it is not UTF-8"}
    if candidate.kind != kind:
        msg = "a candidate's own kind is not the kind of the directory it is staged in"
        return {**row, "error": msg}
    return {
        **row,
        "candidate_id": candidate.candidate_id,
        "role": candidate.domain,
        "episode_id": candidate.episode_id,
        "written": candidate.written,
        "replaces": candidate.replaces,
        "destination": _destination(candidate, kind),
        **_fingerprint(data),
    }


@_route
def staged(context: Context, params: Mapping[str, str]) -> dict[str, Any]:
    """The staged candidates, without their content; one that is not a candidate is an error row."""
    library = _library(context)
    return {"candidates": _staged_rows(context, library)}


# -- L4: one candidate -----------------------------------------------------------------------


def _lines(data: bytes | None) -> list[str]:
    """``data``'s lines as UTF-8 text, each with its end kept; only a newline ends a line."""
    if data is None:
        return []
    parts = data.decode("utf-8").split("\n")
    lines = [part + "\n" for part in parts[:-1]]
    if parts[-1]:
        lines.append(parts[-1])
    return lines


def _changed_lines(destination: str, now: bytes | None, after: bytes) -> list[str]:
    """A unified diff of ``now`` and ``after`` that keeps how each line ends.

    Lines are compared with their ends, so a change of line endings alone, or of the last
    newline, is a changed line. Each line is then sent without its newline. A carriage return
    that ends it is shown as a symbol, and a line that ends the file with no newline is followed
    by the unified diff's own line saying so.
    """
    shown: list[str] = []
    diff = difflib.unified_diff(
        _lines(now), _lines(after), fromfile=destination, tofile=destination, lineterm=""
    )
    for index, line in enumerate(diff):
        if index < 2 or line.startswith("@@"):
            shown.append(line)
            continue
        text = line.removesuffix("\n")
        if text.endswith("\r"):
            text = text[:-1] + CARRIAGE_RETURN
        shown.append(text)
        if not line.endswith("\n"):
            shown.append(NO_NEWLINE)
    return shown


@_route
def candidate(context: Context, params: Mapping[str, str]) -> dict[str, Any]:
    """One staged candidate and what promoting it would do, by promotion's own code."""
    library = _library(context)
    candidate_id = params["candidate"]
    staging = library / STAGING_DIR
    # Every file the finder may open is judged first, so a refused one is a refusal here and
    # never reaches the request's guard.
    for kind in FINDER_KINDS:
        probed = staging / kind / f"{candidate_id}.json"
        if os.path.lexists(probed):
            context.allowlist.resolve(probed)
    # The general staging folder for both: the finder never looks inside the reviewers' tree,
    # and a rubric it finds here is one promotion would never find.
    try:
        found = find_staged(candidate_id, staging, staging)
    except OSError as exc:
        # A kind's folder the server may not search: the finder's own checks cannot run.
        raise _unreadable(exc, _recorded(library, staging)) from None
    if found is None or found[0] == "rubric":
        msg = "no candidate with this id is staged"
        raise NotFoundError(msg, candidate_id=candidate_id)
    kind, staged_candidate, _ = found
    destination = _destination(staged_candidate, kind)
    path = library.joinpath(*destination.split("/")[1:])
    now = _read(context, library, path)
    after, whole = promotion_bytes(staged_candidate, kind, now)
    if now is None:
        effect = "creates"
    elif whole:
        effect = "replaces whole"
    else:
        effect = "adds to"
    return {
        "candidate": staged_candidate.model_dump(mode="json"),
        "kind": kind,
        "destination": destination,
        "effect": effect,
        "now": None if now is None else _fingerprint(now),
        "after": _fingerprint(after),
        "lines": _changed_lines(destination, now, after),
    }


# -- L5: the ratings -------------------------------------------------------------------------


def _pair(value: float, unit: str) -> dict[str, Any]:
    return {"value": value, "unit": unit}


def _bound(bound: Range | Envelope) -> dict[str, Any]:
    return {
        "low": _pair(bound.low, bound.unit),
        "high": _pair(bound.high, bound.unit),
        "class": bound.component_class,
        "source": bound.source,
        "retrieved": bound.retrieved.isoformat(),
        "confirmed": bound.confirmed.isoformat(),
        "note": bound.note,
    }


def _range(entry: Range) -> dict[str, Any]:
    kind = kind_of(entry.quantity)
    return {
        "quantity": entry.quantity,
        "kind": None if kind is None else kind.name,
        **_bound(entry),
    }


@_route
def ratings(context: Context, params: Mapping[str, str]) -> dict[str, Any]:
    """The bounds tables' ranges and envelopes, and the catalogue's energy-store classes."""
    library = _library(context)
    tables = []
    for role in _roles(context, library):
        path = library / role / BOUNDS_NAME
        data = _read(context, library, path)
        if data is None:
            continue
        table = load_table(path)
        if table.sha256 != hashlib.sha256(data).hexdigest():
            # The table was loaded from bytes other than the ones judged and read here: a
            # sentence (422), since the bytes read here were judged and the table is not shown.
            msg = "the file changed while it was read"
            raise UIError(msg, path=_recorded(library, path))
        tables.append((path, table))
    # Joined as the gate joins them, so the gate's own rules (one envelope per kind) hold here.
    Bounds({table.domain: table for _, table in tables})
    return {
        "tables": [
            {
                "domain": table.domain,
                "path": _recorded(library, path),
                "sha256": table.sha256,
                "ranges": [_range(entry) for entry in table.ranges.values()],
                "envelopes": [
                    {"kind": kind, **_bound(entry)} for kind, entry in table.envelopes.items()
                ],
            }
            for path, table in tables
        ],
        "store_classes": [
            {
                "name": store.name,
                "fastest_discharge": _pair(store.per_hour, PER_HOUR),
                "source": store.source,
                "confirmed": store.confirmed.isoformat(),
            }
            for store in STORE_CLASSES
        ],
        "catalogue_digest": catalogue_digest(NO_LAWS),
    }
