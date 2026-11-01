"""R-PG-01b: the pins and places every script of the experiment shares (CRITERIA.md §2, §10, §14).

Nothing here reads a run's verdicts. Every value is the frozen file's, or a path it names; the
two facts filled after the freeze (arm F's manifest digest and the run commit's instrument tree)
are read from the filled ``CRITERIA.md`` on ``master`` by :func:`filled`, never typed here.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent

# ---- seeds (§15 row 15) ----
SEED = 7
SLOT_SEED = 29
ARM_ORDER_SEED = 31
BOOT_SEED = 13
BOOT_DRAWS = 10_000
PACKET_SEED = 37
CONTROL_SEED = 43

# ---- the code (§2.2, §2.4) ----
R_PG_01_COMMIT = "8bc03fc65f3a555f8f4f737eb5eeea1c6f179670"
#: The freeze: the commit that added CRITERIA.md. The run branch carries this file as frozen.
FREEZE_COMMIT = "e1262da3a85f659ff600036eaf68e8c57ea5c47b"
RUN_BRANCH = "exp/r-pg-01b-run"
RUN_TAG = "r-pg-01b-run"
#: The converter's commit: ``make_sheet.sh`` runs on master at it or later (§14).
CONVERTER_COMMIT = "31b90aa"
GATE_TREE = "29e7c8061e4f5e54b815afd41bf98f9e6455a7c3"
BOUNDS_BLOB = "cdeb9736d93362120f8f08f0244ab449b7bd5f90"
BOUNDS_SHA256 = "b75d14d541243108d02f0afc1414a8cd61493f694325c9c2e4f09e30cfa27071"
SPELLING_BLOB = "eaa4ce697092d27545a19c87c6d92fc6f1e966fc"
CATALOGUE_SHA256 = "171b054b61f703fee2aaf750b4ff107754bbf0726882e18531cb92db0028d69f"
REVIEWERS_TREE = "7df979eecb5b9acba572c5687747ea33586a87e1"
RUBRICS_TREE = "dd203340de8cee2f42878bb09ee72e64dfe1465b"
RUBRIC_SHA256 = {
    "control": "18be8569a3743d6f9f5ff554ac6fd7e7c86b082ffaad4c08d0a40a00bac111f5",
    "electrical": "a1b78302cf116ce471bf24a484de24a1e98e8679256e41d5f36b3dd4f48219b3",
    "firmware": "e265ef4733443d1af8a8152a8831fa97f999c3fcae0acc8f12f48fe1faed5f8a",
    "mechanical": "3ca83fe1099481ff4c32681b7e63a594e907dd01bcd6a56a8160ed0a8e0783fa",
}
#: R-PG-01's instrument tree; the run commit's is filled at "run commit filled" (§2.4).
R_PG_01_INSTRUMENT_TREE = "af7ead4ac5579c86b6e19ffe7a02991ac9872eca"
PARAMS_BLOB = "f32da7e47303ee168cc9671edb2a8b40e72b024e"
#: R-PG-01's frozen scripts, run unchanged at these blobs (§2.2).
R_PG_01_SCRIPTS = {
    "tally_rows.py": "0f138e7fa353e545cfab749ce73c7ca2e063f0f4",
    "read_catches.py": "d311b76e7492f81a54cba5e51dccdbc103505fad",
    "regate_r6.py": "39c33c98e0f6da328383020d14cbcbe1d08b44b3",
    "r4_twins.py": "a30afd3d4fecb742085c6d5d569710a528a1f58a",
    "r3_scan.py": "dfcddf2c34da27337cd956b9548c0d0c3aa706e8",
}
R_PG_01_LAUNCH_BLOB = "63efe5ac3f182d9b99c5870ae318caf871bc9c8e"
R4_RECORDS_SHA256 = "ea3d581a027abd3538c3aa5271f169ca8ddc2d868e5f7fe104739ef1ccb8e75c"
#: The sentences the account names the sheet in (§2.4), and R-PG-01's.
ACCOUNT_SHEET_SHA256 = "4adba41d2ba10410d8fa734013dcfa305c0918190e0757cb54ab6f3fc625c9c9"
ACCOUNT_SHEET_GIVEN_SHA256 = "09f545b2df9d39fe8c27784768d58d5dfa71a243c2fa5808996ed8a0718fe439"

# ---- the binary (§2.2, §10) ----
BINARY_VERSION = "2.1.301"
BINARY_SHA256 = "1e119036a802d359ba5f9886428e031586e8796f7a858d5a8ee179ac7b8604f0"
BINARY_SHA256_MACOS = "1f04c69e1c24e4d0a716a863af0aad8fc64d49a499334c29701f073700276b99"
REVIEWER_MODEL = "claude-sonnet-5"
AUTHOR_MODEL = "claude-opus-5-5"
REALITY_MODEL = "claude-opus-5-5"

# ---- the corpora (§2.2, §2.5) ----
ARM_I_CORPUS = "corpora/injected-errors/v1"
ARM_F_CORPUS = "corpora/injected-errors/v1-fullsheet"
ARM_I_MANIFEST_SHA256 = "41553301d5b036f84df289ee6d8c87ecce4504d5a09969e05291e23c9ebc026a"
ARM_I_SHEET_SHA256 = "bc1e5ec15c6f1df823f5a39207b0656b6a2b388eca4d3414db007b4d7999ca91"
ARM_F_SHEET_SHA256 = "2efbb6a8ab889ceac54d8ebdba15c8530274d8524c9eaf6181d22abf5ccbef90"
#: The authors' table, unedited (§2.5): every reality packet carries it verbatim (§6).
TABLE_SHA256 = "29f9568ce8465112ef0b0b164f05f3ba76f9702e3ccbc7a1dea96fbc3d057b3f"
TABLE_NAME = "parts_sheet.md"
#: The numbered lines each sheet's whole read returns, and the last row id both end with (§5.5).
SHEET_LINES = {"I": 984, "F": 1225}
LAST_ROW_ID = "R11.04"
ARMS = ("I", "F")
ROUNDS = (1, 2)
SIDES = ("injected", "twin")
DENOMINATOR = 40

# ---- the host (§2.6, §10, §11) ----
CHECKOUT_NAME = "physgate-r-pg-01b-run"
RUNS_NAME = "runs/rpg01b"
SCRATCH_NAME = "review-scratch"
TOKEN_FILE = ".config/physgate-run.env"
TOKEN_VARIABLE = "CLAUDE_CODE_OAUTH_TOKEN"
#: The shape a long-lived token's value must have before it is used, never printed; and the env
#: file's one line for it (token.sh's shape): the name, ``=``, the value, nothing else; and any
#: line that names the variable, however spelt (exactly one may).
TOKEN_SHAPE = re.compile(r"^sk-ant-oat01-[A-Za-z0-9_-]{20,}$")
TOKEN_LINE = re.compile(r"^CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-[A-Za-z0-9_-]{20,}$")
TOKEN_NAMED = re.compile(r"^\s*(export\s+)?CLAUDE_CODE_OAUTH_TOKEN\s*=")
#: §11: what the run account is known to carry in one 5-hour span, the projection's floor rate,
#: and how many reviews two sessions at once finish at most in 5 hours.
CARRIED_TOKENS = 80_000_000
FLOOR_TOKENS_PER_REVIEW = 400_000
REVIEWS_PER_5H = 120
#: §12: the reason reading's token guard; the infrastructure cascade; attempts per round.
REASONS_GUARD = 30_000_000
CASCADE = 3
MAX_ATTEMPTS = 3


#: A session's id, as the instrument names its directory under a review root.
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
#: A review root's own name (§2.6): ``rpb-<slot>``.
ROOT_NAME = re.compile(r"rpb-[0-9]{1,3}")
#: A records directory a trial may name: an absolute path of plain names.
_PLAIN_PATH = re.compile(r"/[A-Za-z0-9._+/-]*")


def check_slot(slot: object) -> int:
    """A slot, held to its form before any path is built from it: a whole number, 1 to 999.

    Raises:
        ValueError: anything else.
    """
    if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= 999:
        msg = f"a slot is a whole number from 1 to 999, not {slot!r}"
        raise ValueError(msg)
    return slot


def records_dir(value: str | None, home: Path) -> Path:
    """The experiment's records: the run's, or the directory a check-only trial names.

    Raises:
        ValueError: the named directory is not an absolute path of plain names with no ``..``.
    """
    if not value:
        return Path(home) / RUNS_NAME
    if not _PLAIN_PATH.fullmatch(value) or os.path.normpath(value) != value:
        msg = "the records directory is an absolute path of plain names, with no '..'"
        raise ValueError(msg)
    return Path(value)


def run_id(slot: int) -> str:
    """The run id of a slot (§2.6): the same form for both arms."""
    return f"rpb-{check_slot(slot)}"


def places(home: Path, slot: int, runs: Path | None = None) -> dict[str, Path]:
    """Every path of a slot (§2.6): its run directory, review root and installation."""
    check_slot(slot)
    runs = Path(runs) if runs is not None else Path(home) / RUNS_NAME
    return {
        "run": runs / f"run-{slot}",
        "scratch": Path(home) / SCRATCH_NAME / run_id(slot),
        "install": runs / f"install-{slot}",
    }


def sha256_bytes(data: bytes) -> str:
    """The sha256 of ``data``."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    """The sha256 of a file's bytes, read in pieces (a pinned binary is a quarter gigabyte)."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as f:
        for piece in iter(lambda: f.read(1 << 20), b""):
            digest.update(piece)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """A JSON-lines file, one value per non-blank line; read as :func:`read_own` reads.

    Raises:
        FailClosed: it is not a regular file that can be read, or it passes the read's bound.
    """
    data = read_own(path)
    if data is None:
        msg = f"{Path(path).name} is not a regular file that can be read"
        raise FailClosed(msg)
    return [json.loads(x) for x in data.decode().splitlines() if x.strip()]


# ---- under a review root or a run directory: nothing through a symlink, nothing outside ----
#
# Every read, listing and removal under a root walks from the root's own descriptor, opening each
# directory relative to its parent's descriptor with O_NOFOLLOW, and acts on what it holds open:
# no path string is used again after a check, so a part swapped for a symlink between the two is
# never followed. Nothing that is not a regular file is ever opened for reading (O_NONBLOCK, so a
# FIFO cannot hold the open), and every walk and read is bounded. A bound that is hit, or a
# directory that cannot be opened, raises :class:`FailClosed` with its cause: nothing is passed
# over as if it were not there.

#: The bounds of every walk and read under a root.
MAX_DEPTH = 32
MAX_ENTRIES = 250_000
MAX_FILE_BYTES = 256 * 1024 * 1024

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


class FailClosed(Exception):
    """A walk or read hit a bound, or could not confirm what lies under a root.

    The caller stops with this cause.
    """


def _after_open(parts: tuple[str, ...]) -> None:
    """Called with each directory's parts below the root just after the walk opens it.

    Nothing by default; a test puts a swap here, between the walk's check and its act.
    """
    return None


def _open_dir(name: str | Path, parent: int | None = None) -> int | None:
    """A directory opened without following a symlink, relative to ``parent``; ``None`` if not."""
    try:
        fd = os.open(name, _DIR_FLAGS, dir_fd=parent)
    except OSError:
        return None
    if not stat.S_ISDIR(os.fstat(fd).st_mode):
        os.close(fd)
        return None
    return fd


def _plain_parts(root: Path, path: Path) -> tuple[str, ...] | None:
    """``path``'s parts below ``root``, each a plain name; ``None`` if it is not below it."""
    try:
        parts = Path(path).relative_to(root).parts
    except ValueError:
        return None
    if not parts or len(parts) > MAX_DEPTH or any(x in ("", ".", "..") or "/" in x for x in parts):
        return None
    return parts


@contextlib.contextmanager
def _dir_inside(root: Path, parts: tuple[str, ...]) -> Iterator[int | None]:
    """The directory ``parts`` below ``root``, held open, each step taken with no symlink."""
    held: list[int] = []
    try:
        fd = _open_dir(root)
        if fd is None:
            yield None
            return
        held.append(fd)
        for k, name in enumerate(parts):
            fd = _open_dir(name, held[-1])
            if fd is None:
                yield None
                return
            held.append(fd)
            _after_open(parts[: k + 1])
        yield held[-1]
    finally:
        for fd in held:
            os.close(fd)


def _mode(name: str, parent: int) -> int | None:
    """An entry's own type (``lstat``), relative to ``parent``; ``None`` if it is not there."""
    try:
        return os.stat(name, dir_fd=parent, follow_symlinks=False).st_mode
    except FileNotFoundError:
        return None


def _names(fd: int, where: str) -> list[str]:
    """The names in the directory held at ``fd``, sorted, at most :data:`MAX_ENTRIES`."""
    names: list[str] = []
    with os.scandir(fd) as entries:
        for entry in entries:
            names.append(entry.name)
            if len(names) > MAX_ENTRIES:
                msg = f"{where} holds more than {MAX_ENTRIES} entries: the bound of a walk"
                raise FailClosed(msg)
    return sorted(names)


def _read_fd(fd: int, where: str) -> bytes | None:
    """A held file's bytes if it is a regular file, at most :data:`MAX_FILE_BYTES`."""
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return None
        data = f.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        msg = f"{where} is larger than {MAX_FILE_BYTES} bytes: the bound of a read"
        raise FailClosed(msg)
    return data


def read_inside(root: Path, path: Path) -> bytes | None:
    """A regular file's bytes under ``root``, reached through no symlink; else ``None``.

    Raises:
        FailClosed: the file is larger than the bound of a read.
    """
    parts = _plain_parts(root, path)
    if parts is None:
        return None
    with _dir_inside(root, parts[:-1]) as parent:
        if parent is None:
            return None
        try:
            fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=parent)
        except OSError:
            return None
        return _read_fd(fd, "/".join(parts))


def exists_inside(root: Path, path: Path) -> bool:
    """Whether anything stands at ``path`` under ``root``, reached through no symlink."""
    parts = _plain_parts(root, path)
    if parts is None:
        return False
    with _dir_inside(root, parts[:-1]) as parent:
        return parent is not None and _mode(parts[-1], parent) is not None


def list_inside(root: Path, parts: tuple[str, ...] = ()) -> list[tuple[str, int]]:
    """The names and own types in the directory ``parts`` below ``root``, in name order.

    Raises:
        FailClosed: the directory holds more entries than the bound of a walk.
    """
    with _dir_inside(root, parts) as fd:
        if fd is None:
            if os.path.lexists(Path(root).joinpath(*parts)):
                where = "/".join(parts) or Path(root).name
                msg = f"{where} could not be opened as a directory: what it holds is not confirmed"
                raise FailClosed(msg)
            return []
        found = []
        for name in _names(fd, "/".join(parts) or "the root"):
            mode = _mode(name, fd)
            if mode is not None:
                found.append((name, mode))
        return found


def walk_inside(root: Path) -> Iterator[tuple[tuple[str, ...], int]]:
    """Every entry below ``root``, as its parts and own type, in name order; none followed.

    Each directory is opened from its parent's descriptor with no symlink followed, and the
    walk descends into directories alone; a symlink and any other entry are given as they are,
    never opened. Nothing under a root that does not exist is given.

    Raises:
        FailClosed: a directory could not be opened, or the walk passed its depth or entry bound.
    """
    count = [0]

    def below(fd: int, prefix: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], int]]:
        if len(prefix) >= MAX_DEPTH:
            msg = f"{'/'.join(prefix)} lies deeper than {MAX_DEPTH}: the depth bound of a walk"
            raise FailClosed(msg)
        for name in _names(fd, "/".join(prefix) or "the root"):
            mode = _mode(name, fd)
            if mode is None:
                continue
            count[0] += 1
            if count[0] > MAX_ENTRIES:
                msg = f"the walk passed {MAX_ENTRIES} entries: the bound of a walk"
                raise FailClosed(msg)
            parts = (*prefix, name)
            yield parts, mode
            if stat.S_ISDIR(mode):
                child = _open_dir(name, fd)
                if child is None:
                    msg = f"{'/'.join(parts)} could not be opened: what it holds is not confirmed"
                    raise FailClosed(msg)
                try:
                    _after_open(parts)
                    yield from below(child, parts)
                finally:
                    os.close(child)

    if not os.path.lexists(root):
        return
    top = _open_dir(root)
    if top is None:
        msg = f"{Path(root).name} could not be opened: what it holds is not confirmed"
        raise FailClosed(msg)
    try:
        yield from below(top, ())
    finally:
        os.close(top)


def session_dirs(root: Path) -> tuple[list[str], int]:
    """The ids of every ``<root>/<session id>/session`` directory reached through no symlink.

    Also how many entries of a session's form were refused as symlinks.
    """
    found: list[str] = []
    refused = 0
    for name, mode in list_inside(root):
        if not SESSION_ID.fullmatch(name):
            continue
        if stat.S_ISLNK(mode):
            refused += 1
            continue
        if not stat.S_ISDIR(mode):
            continue
        inner = dict(list_inside(root, (name,))).get("session")
        if inner is not None and stat.S_ISLNK(inner):
            refused += 1
        elif inner is not None and stat.S_ISDIR(inner):
            found.append(name)
    return found, refused


#: Where a session's login is put, by the instrument's own credential code: the binary's login
#: file in its config directory, or an API key and its helper in its state directory.
LOGIN_FILES = {"config": (".credentials.json",), "state": ("key", "key-helper.sh")}


def login_files(root: Path) -> dict[str, int]:
    """What may still hold a session's login under ``root``, by a bounded walk through no symlink.

    ``left``: entries at a login file's name in a session's ``config`` or ``state`` (whatever
    their type). ``unconfirmed``: a symlink standing where a session's directory, its
    ``session``, ``config`` or ``state`` belongs, behind which nothing can be confirmed.

    Raises:
        FailClosed: a directory could not be opened, or the walk passed a bound.
    """
    left = unconfirmed = 0
    for parts, mode in walk_inside(root):
        name = parts[-1]
        in_session = len(parts) >= 3 and parts[-3] == "session"
        if in_session and name in LOGIN_FILES.get(parts[-2], ()):
            left += 1
        elif stat.S_ISLNK(mode) and (
            SESSION_ID.fullmatch(name)
            or name == "session"
            or (name in LOGIN_FILES and len(parts) >= 2 and parts[-2] == "session")
        ):
            unconfirmed += 1
    return {"left": left, "unconfirmed": unconfirmed}


def _empty(fd: int, depth: int = 0) -> bool:
    """Remove everything in the directory held at ``fd``, or say it could not.

    Regular files and directories alone are removed, each by name relative to its held parent;
    anything else is refused and left, as is anything whose removal fails: the caller confirms
    what is left (:func:`login_files`).
    """
    if depth >= MAX_DEPTH:
        return False
    clean = True
    for name in _names(fd, "a directory being removed"):
        mode = _mode(name, fd)
        if mode is not None and stat.S_ISREG(mode):
            try:
                os.unlink(
                    name, dir_fd=fd
                )  # a name swapped since is unlinked itself, never followed
            except OSError:
                clean = False
        elif mode is not None and stat.S_ISDIR(mode):
            child = _open_dir(name, fd)
            if child is None:
                clean = False
                continue
            try:
                inner = _empty(child, depth + 1)
            finally:
                os.close(child)
            try:
                if inner:
                    os.rmdir(name, dir_fd=fd)
            except OSError:
                inner = False
            clean = clean and inner
        elif mode is not None:
            clean = False
    return clean


def unlink_inside(root: Path, parts: tuple[str, ...]) -> str:
    """Unlink the entry ``parts`` below ``root``, through no symlink on the way.

    A symlink there is itself unlinked, never followed. It returns ``removed``, ``absent`` or
    ``refused``.
    """
    with _dir_inside(root, parts[:-2]) as grand:
        if grand is None:
            return "refused"
        held = _mode(parts[-2], grand)
        if held is None:
            return "absent"  # no directory to hold it
        parent = _open_dir(parts[-2], grand) if stat.S_ISDIR(held) else None
        if parent is None:
            return "refused"
        try:
            mode = _mode(parts[-1], parent)
            if mode is None:
                return "absent"
            if stat.S_ISDIR(mode):
                return "refused"
            os.unlink(parts[-1], dir_fd=parent)
        except FileNotFoundError:
            return "absent"
        except OSError:
            return "refused"
        finally:
            os.close(parent)
        return "removed"


def remove_inside(root: Path, parts: tuple[str, ...]) -> str:
    """Remove the directory ``parts`` below ``root`` and what it holds, through no symlink.

    It returns ``removed``, ``absent``, or ``refused`` (a part or an entry that is a symlink or
    neither a file nor a directory, or a removal that failed; what is left stays). The caller
    confirms what is left with :func:`login_files`.
    """
    with _dir_inside(root, parts[:-1]) as parent:
        if parent is None:
            return "refused"
        mode = _mode(parts[-1], parent)
        if mode is None:
            return "absent"
        if not stat.S_ISDIR(mode):
            return "refused"
        fd = _open_dir(parts[-1], parent)
        if fd is None:
            return "refused"
        try:
            _after_open(parts)
            clean = _empty(fd)
        finally:
            os.close(fd)
        if not clean:
            return "refused"
        try:
            os.rmdir(parts[-1], dir_fd=parent)  # a symlink put here since is refused (ENOTDIR)
        except OSError:
            return "refused"
        return "removed"


def read_own(path: Path) -> bytes | None:
    """A regular file the run wrote, opened once and never through a symlink; else ``None``.

    Raises:
        FailClosed: the file is larger than the bound of a read.
    """
    try:
        fd = os.open(path, _FILE_FLAGS)
    except OSError:
        return None
    return _read_fd(fd, Path(path).name)


def read_log(path: Path) -> tuple[list[dict[str, Any]], int]:
    """A run log's lines, and how many did not parse.

    A killed process can leave half a line, and a crashed one no file at all (no lines, none
    broken). A log that is a symlink is not read: it has no lines.
    """
    lines: list[dict[str, Any]] = []
    broken = 0
    data = read_own(path)
    for raw in data.decode(errors="replace").splitlines() if data is not None else []:
        if not raw.strip():
            continue
        try:
            line = json.loads(raw)
        except json.JSONDecodeError:
            broken += 1
            continue
        if isinstance(line, dict):
            lines.append(line)
        else:
            broken += 1
    return lines, broken


def git(repo: Path, *args: str) -> str:
    """One git command in ``repo``; its output, stripped. Raises on failure."""
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


# ---- the filled facts (§2.4, §2.5), read from the filled CRITERIA.md ----

#: How the "sheet filled" and "run commit filled" commits write each fact: the placeholder's
#: own sentence, its placeholder replaced by the fact in backticks.
FILLED = {
    "arm_f_label": re.compile(r"format 1, author model `claude-opus-5-5`, label `([^`]+)`"),
    "arm_f_manifest": re.compile(r"Its manifest digest is `([0-9a-f]{64})`"),
    "instrument_tree": re.compile(r"Instrument tree at the run commit:\*\* `([0-9a-f]{40})`"),
    "run_commit": re.compile(r"\*\*Run commit:\*\* `([0-9a-f]{40})`"),
}


def filled(criteria_text: str) -> dict[str, str]:
    """Each filled fact of a filled ``CRITERIA.md``; a fact still a placeholder is absent."""
    found: dict[str, str] = {}
    flat = " ".join(criteria_text.split())
    for name, pattern in FILLED.items():
        hit = pattern.search(flat)
        if hit and not hit.group(1).startswith("[FILL"):
            found[name] = hit.group(1)
    return found


def filled_on(repo: Path, ref: str) -> dict[str, str]:
    """The filled facts of ``CRITERIA.md`` at ``ref`` (``origin/master`` at launch)."""
    return filled(git(repo, "show", f"{ref}:experiments/R-PG-01b/CRITERIA.md"))
