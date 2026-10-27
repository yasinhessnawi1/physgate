"""R-PG-03: the pins and places every script of the experiment shares (CRITERIA.md §3, §10, §14).

Nothing here reads a verdict. Every value is the frozen file's, or a path it names. The facts
filled after the freeze ("Commits filled", "Sheet filled", "Set filled") are never typed here:
they are read from the fills record on ``master`` (:func:`fills_on`), and a script that needs one
refuses while it is absent.

The reads under a review root, a run directory or a session's directory are R-PG-01b's: every
walk and read goes from a held descriptor with no symlink followed, bounded, and fails closed.
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
EXPERIMENT = "experiments/R-PG-03"
#: The freeze: the criteria and the README as committed before any code, byte for byte for good.
FREEZE_COMMIT = "3e7a3c8b62e93c38758a7ca3aabee9e6597fefbc"
FROZEN_BLOBS = {
    f"{EXPERIMENT}/CRITERIA.md": "5a9c996b97cda9a2c5c13722761af4481a54eb60",
    f"{EXPERIMENT}/README.md": "7ce44f4c1627df24049338df81b26e245d7cb869",
}

# ---- the arms (§3.1) ----

#: The arms, in the order a block starts them (§5 R8).
ARMS = ("A2", "A1", "B")
ARM_KIND = {"A2": "paired", "A1": "paired", "B": "generalist"}
#: Which checkout each arm runs from (§3.2): the run commit, or its rubric-only sibling.
ARM_CHECKOUT = {"A2": "R", "A1": "R_K", "B": "R_K"}
ROLES = ("control", "electrical", "firmware", "mechanical")
#: The rubric sha256 every review line of an arm carries, by role (§3.1).
RUBRIC_SHA256: dict[str, dict[str, str]] = {
    "A2": {
        "control": "73a1311b5ea85f5dedb82104f099ae2d4577552c351c970c23ece5bc7945dae0",
        "electrical": "f0fcbc2ac8ffa864bf6f5d1867a0d2150672ccf61bed06276b80e6036bddcdd6",
        "firmware": "16bb9fa6cf0e9b0de5216bc265faedfd32b69565e457e2e013f3e69321a689d3",
        "mechanical": "cee5a478d535bcb58cf1d1493a1563b023dac94b7eca37a17baec1719f98e212",
    },
    "A1": {
        "control": "08a5cfbc1b6729843bd5f6d8cad5c3596faaeecc596fb472230905815a2677d6",
        "electrical": "5ca8c13584ac896abda9825d52a0a3b8177866024e68249ad75375c59086b445",
        "firmware": "614ad78c9ebceba6903fba31267801e970162d80fbf10df0713064c99377c25e",
        "mechanical": "ee68896b4adce53b1e66330d1c8072e5afbac66a547d077abd4d0325ef8dadf8",
    },
    "B": {
        "control": "a75561161064cf498890301ab8356d6e2bd332e7754e4ee6d3cb8386ad584e54",
        "electrical": "12f3b842dd8dd98033b6de50e7449ada993a50f231216ca4c1cff229f2bedab5",
        "firmware": "f22093b19159b730a1eb030834ea2fd975ce18f22e696b38406a3862fdde756a",
        "mechanical": "5f76f510724122fea9c2cc1125892e09c5ac84ef2735fe0ef34a1d0805867e5e",
    },
}
#: The knowledge each arm reads, as git trees, identical in R and R_K (§3.1).
KNOWLEDGE_TREES = {
    "knowledge/control": "260dc0d9deac61166849fa078d1550f0e6c82c06",
    "knowledge/electrical": "64d5ca418c65afff5a67fa624cfe35b9f7f90b7d",
    "knowledge/firmware": "66a6eac5c76b9a472ec5c78867ae5f741d17b86a",
    "knowledge/mechanical": "14cde0b1c32875893a626c8358824fb52c363378",
    "knowledge/cross": "aa03dc8c7ff21529431007c9acdd637548f5f983",
}
#: The account's three fixed paragraphs (§3.3), unchanged.
ACCOUNT_SHA256 = "8580efd05af6fd2d304810950f00bb2c3d462302dddfd00b1d12373e340ab838"

# ---- the code (§3.2, §3.3) ----

#: R descends from master at or after this commit (§3.2).
R_FLOOR = "fc28f323fc0cb83b2c0f4575d2bd52be7ab4242a"
#: The commit that promoted the fixed rubrics, and its parent, where K's rubrics are (§3.2).
FIX_COMMIT = "d93be3afa5b16f30433b2105211f1ca34991272e"
K_COMMIT = "1a7bb0d5c53c2c4e0fa2347dd066ce3149124fc3"
PROMOTIONS = "knowledge/promotions.jsonl"
RUBRIC_PATHS = tuple(f"knowledge/reviewers/{role}/rubric.md" for role in ROLES)
#: The five paths R_K restores to K's state, and no other (§3.2).
R_K_PATHS = (*RUBRIC_PATHS, PROMOTIONS)
#: The three old trees code_changes.py lists from (§3.3): R-PG-02's run, the practice cycle's
#: noise run and its kept round (the tag ``gr2-r1-run-tree``).
OLD_TREES = {
    "0936f1f": "0936f1f7a36392cecc2091f28cd7b3dee524b02f",
    "eae78c0": "eae78c09b73d587691d463f7d557929124146094",
    "8c51f48": "8c51f481742cb60dc971586724db718f69ff8508",
}
KEPT_ROUND_TAG = "gr2-r1-run-tree"
NOISE_RUN_TREE = OLD_TREES["eae78c0"]
KEPT_ROUND_TREE = OLD_TREES["8c51f48"]

# ---- the binary, the models, the parameters (§3.4) ----

BINARY_VERSION = "2.1.301"
BINARY_SHA256 = "1e119036a802d359ba5f9886428e031586e8796f7a858d5a8ee179ac7b8604f0"
#: The macOS build of the same version: for the tests' scripted sessions on a laptop only.
BINARY_SHA256_MACOS = "1f04c69e1c24e4d0a716a863af0aad8fc64d49a499334c29701f073700276b99"
REVIEWER_MODEL = "claude-sonnet-5"
AUTHOR_MODEL = "claude-opus-5-5"
REALITY_MODEL = "claude-opus-5-5"
REALITY_EFFORT = "high"
#: R-PG-02's parameters file: every field but ``lanes`` is R-PG-03's (§3.4).
PARAMS_FRESH = "experiments/R-PG-02/params_fresh.json"
LANES = {"A2": 3, "A1": 3, "B": 2}

# ---- the blocks and the seeds (§10, §14 item 5) ----

#: The blocks, in their fixed order.
BLOCKS = ("x1", "y1", "z1", "z2", "y2", "x2", "s", "p1", "p2")
PRIMARY_BLOCKS = ("x1", "y1", "z1", "z2", "y2", "x2")
BLOCK_SEED = {
    "x1": 53,
    "y1": 59,
    "z1": 83,
    "z2": 89,
    "y2": 67,
    "x2": 61,
    "s": 71,
    "p1": 73,
    "p2": 79,
}
#: Each block's corpus, by name.
BLOCK_CORPUS = {
    "x1": "fresh-v2-x1",
    "x2": "fresh-v2-x2",
    "y1": "fresh-v2-y1",
    "y2": "fresh-v2-y2",
    "z1": "fresh-v2-z1",
    "z2": "fresh-v2-z2",
    "s": "fresh-v2-s",
    "p1": "fresh-v1c-a01-a20",
    "p2": "fresh-v1c-a21-a40",
}
#: §7's corpus order, which numbers every line of the reading.
CORPUS_ORDER = (
    "fresh-v2-x1",
    "fresh-v2-x2",
    "fresh-v2-y1",
    "fresh-v2-y2",
    "fresh-v2-z1",
    "fresh-v2-z2",
    "fresh-v2-s",
    "fresh-v1c-a01-a20",
    "fresh-v1c-a21-a40",
)
FRESH_V2 = CORPUS_ORDER[:7]
FRESH_V1C = CORPUS_ORDER[7:]
AUTHOR_PAIR = {"x1": "X", "x2": "X", "y1": "Y", "y2": "Y", "z1": "Z", "z2": "Z"}
PAIRS = ("X", "Y", "Z")
#: Items per block, injected (and as many twins).
BLOCK_ITEMS = {**dict.fromkeys(PRIMARY_BLOCKS, 20), "s": 10, "p1": 20, "p2": 20}
#: Every other batch's size per class: five of each of the four classes (§2.5 item 1).
PER_CLASS_BATCH = 5
#: The instrument's domain-standard class, and ``fresh-v2-s``'s size of it: that class alone, ten
#: of it (§2.1, §2.5 item 1).
STANDARD_CLASS = "standard"
PER_CLASS_S = 10
BOOT_SEED = 13
BOOT_DRAWS = 10_000
PACKET_SEED = 37
CONTROL_SEED = 43

# ---- the sheet (§2.4) ----

TABLE_NAME = "parts_sheet.md"
SHEET_NAME = "sources.json"
#: R-PG-02's authors' table, and the edited one every session and packet carries.
TABLE_SHA256 = "29f9568ce8465112ef0b0b164f05f3ba76f9702e3ccbc7a1dea96fbc3d057b3f"
EDITED_TABLE_SHA256 = "0573ef044ebdcee9ff184eec2789e1a10b31fef6f32947735f9005ea8b0daedc"
#: R-PG-02's sources.json, whose numbers the converter keeps.
KEEP_FROM_SHA256 = "bc1e5ec15c6f1df823f5a39207b0656b6a2b388eca4d3414db007b4d7999ca91"
#: The one prose line named to be dropped although it holds a row id (§2.4).
DROP_LINE_SHA256 = "4c7844dc7a445b5e8628c27a5ae14b526275b2d45270d0e4ff571fb4e1dd7a8c"
#: The drafter's probe of the reviewers' sheet (§2.4).
PROBE_SHEET_SHA256 = "2efbb6a8ab889ceac54d8ebdba15c8530274d8524c9eaf6181d22abf5ccbef90"
PROBE_COUNTS = {
    "rows": 163,
    "rows_with_a_number": 101,
    "rows_with_given": 111,
    "rows_with_given_only": 62,
    "rows_with_neither": 0,
    "notes": 130,
    "prose_lines_dropped": 9,
    "telltale_words": 0,
    "bytes": 40_095,
}
#: Where R-PG-02's frozen table and the tuning set's sheet are, in this checkout.
R_PG_02_TABLE = "experiments/R-PG-02/fresh-authoring/briefs/parts_sheet.md"
TUNING_SET = "corpora/injected-errors/fresh-v1"
TUNING_SET_MANIFEST = "e76a4904e7b42326a85a9a9267973518e6f79b510c8f2b8b3391e8b23d37620c"
CONVERTER = "scripts/parts_sheet_sources.py"
#: The last row id of the sheet, which a whole read returns.
LAST_ROW_ID = "R11.04"

# ---- §7 ----

REALITY_PROMPT_SHA256 = "41438ab78097d57a6e986b24f4f8071516fa36c1f0393f408874cd81adb23913"
REALITY_SCHEMA_SHA256 = "57c3852f8aa0adf9450de3504509b0bf95f85e78c55ff77b199a9c0998172324"
REALITY_PROMPTS = "experiments/R-LAW-01/prompts/final"
#: The domain standards a `standard`-class packet carries, held to these blobs' digests.
STANDARDS_SHA256 = {
    "control": "96ea261cf359b9b1a1cf2886dc56dbe378fb6c747fe7a37ea01eccbc1e31dff1",
    "electrical": "adc3c4f2fbdf9a5dc07dd6cfd12e64301983b724cbdaf9f1693c9dd4bfa3cefb",
    "firmware": "da7594e65d0aedacc57a84ac40849e39ad46454e077b98b84a40c65901fac4b1",
    "mechanical": "2bc64f3d645a43727bd09ada264b6bf3ba2cb9c7cee65ed7f64fe575278227f0",
}
#: R-PG-02's frozen tally, imported unedited, and its published tally, read for blocks p1 and p2.
RPG02_TALLY_SHA256 = "294c9b309eb8d38034781c97bb6ae3bc6e2e885b9b667232bcc7b870bf9352b9"
RPG02_PUBLISHED_TALLY = "experiments/R-PG-02/evidence/tally_2026_10_20.json"
RPG02_PUBLISHED_TALLY_SHA256 = "5f3e31ce472f86b9cbaead81a46a2db7b149c3f1e3b056743a197ad69eb095f7"
#: The pre-freeze probe of the false-finding control's keys, published beside the scripts.
FF_PROBE_SHA256 = "d1def63279798ee19885647611bf0cd7f16e0617a397bb915e337e0953baf7ad"
#: R-LAW-01's extractor and its recorded input digests, as the probe read them.
LAW_EXTRACT_SHA256 = "08b8d840ff1386dfcd18f6ddbc43537113500a89ff55b045d1f0e3d795d7afe8"
LAW_INPUTS_SHA256 = "e3792c3ae13a8942586d2f483810016b810eee9ca7ebc1e41d8b6fca9334afb9"

# ---- the account, the ledger, the 5-hour projection (§10) ----

W5 = 80_000_000
#: The upper rates a block is projected at, per review (§10).
RATE = {"A2": 700_000, "A1": 700_000, "B": 350_000}
WINDOW_5H_S = 5 * 3600
MAX_VOID_ATTEMPTS = 3
TOKEN_FILE = ".config/physgate-run.env"
TOKEN_VARIABLE = "CLAUDE_CODE_OAUTH_TOKEN"
#: The env file's one line for the token (R-PG-01b's ``token.sh`` shape), and any line naming it.
TOKEN_LINE = re.compile(r"^CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-[A-Za-z0-9_-]{20,}$")
TOKEN_NAMED = re.compile(r"^\s*(export\s+)?CLAUDE_CODE_OAUTH_TOKEN\s*=")

# ---- the host (§10) ----

#: Under the run account's home: the two checkouts, the records and the review roots.
CHECKOUT_R = "physgate-r-pg-03-run"
CHECKOUT_R_K = "physgate-r-pg-03-run-k"
RUNS_NAME = "runs/rpg03"
SCRATCH_NAME = "review-scratch"

#: A session's id, as the instrument names its directory under a review root.
SESSION_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


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


def git(repo: Path, *args: str) -> str:
    """One git command in ``repo``; its output, stripped. Raises on failure."""
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    )
    return done.stdout.strip()


def git_bytes(repo: Path, *args: str) -> bytes:
    """One git command in ``repo``; its output as bytes. Raises on failure."""
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True)
    return done.stdout


def utc_now() -> str:
    """The time now, UTC, to the second."""
    import time

    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ---- the fills (CRITERIA.md's status block) ----

#: The record the three fill commits write, one key each; never written by a script here. Its form,
#: which every script reads it in:
#:
#: - ``commits`` ("Commits filled"): ``R`` and ``R_K`` (full shas); ``trees``, ``blobs`` and
#:   ``sha256`` (path to git tree id, blob id or file digest), every one held in both checkouts at
#:   launch; and the published path of ``code_changes.py``'s list;
#: - ``sheet`` ("Sheet filled"): ``sha256`` and the counts §2.4 names;
#: - ``sets`` ("Set filled"): ``manifests``, corpus name to manifest sha256, for fresh-v2's seven
#:   and fresh-v1c's two.
FILLS_NAME = "fills.json"
FILL_KEYS = ("commits", "sheet", "sets")
#: Each fill's name, which the subject of the commit that adds it names.
FILL_NAMES = {"commits": "Commits filled", "sheet": "Sheet filled", "sets": "Set filled"}


class RefusedError(Exception):
    """A pin, a fill or a precondition does not hold."""


def fills_from(text: str | None) -> dict[str, Any]:
    """The fills a record holds; a record that is absent holds none.

    Raises:
        RefusedError: the record is not a JSON object, or holds a key no fill writes.
    """
    if text is None:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict) or set(data) - set(FILL_KEYS):
        raise RefusedError("the fills record holds a key no fill commit writes")
    return data


def fills_history(repo: Path, ref: str) -> list[dict[str, Any]]:
    """Every commit that changed the fills record on ``ref``, oldest first, each held to its rule.

    Each fill is "filled later, each in its own dated commit": a commit that changes the record is
    one commit (never a merge), changes that file alone, adds exactly one fill, the next of
    "Commits filled", "Sheet filled" and "Set filled" in that order, names it in its subject, and
    changes no fill added before it.

    Raises:
        RefusedError: any commit breaks the rule.
    """
    path = f"{EXPERIMENT}/{FILLS_NAME}"
    log = git(repo, "log", "--reverse", "--format=%H%x1f%P%x1f%s", ref, "--", path)
    before: dict[str, Any] = {}
    found = []
    for row in log.splitlines():
        sha, parents, subject = row.split("\x1f")
        short = sha[:7]
        if len(parents.split()) != 1:
            raise RefusedError(f"{short} changes the fills record and is not one commit of its own")
        files = git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines()
        if files != [path]:
            raise RefusedError(f"{short} touches more than the fills record ({len(files)} paths)")
        try:
            after = fills_from(git(repo, "show", f"{sha}:{path}"))
        except subprocess.CalledProcessError:
            raise RefusedError(f"{short} removes the fills record") from None
        if set(before) - set(after) or any(after[k] != v for k, v in before.items()):
            raise RefusedError(f"{short} changes or drops a fill added before it")
        added = sorted(set(after) - set(before))
        if len(added) != 1:
            raise RefusedError(f"{short} adds {len(added)} fills: a fill commit adds one")
        if added[0] != FILL_KEYS[len(before)]:
            want = FILL_NAMES[FILL_KEYS[len(before)]]
            raise RefusedError(f"{short} adds a fill out of order: {want!r} comes next")
        if FILL_NAMES[added[0]] not in subject:
            raise RefusedError(f"{short}'s subject names no {FILL_NAMES[added[0]]!r}")
        found.append({"commit": sha, "fill": added[0], "subject": subject})
        before = after
    return found


def fills_on(repo: Path, ref: str) -> dict[str, Any]:
    """The fills on ``ref`` (``origin/master`` at launch), held to their history.

    There are none before the first fill commit.

    Raises:
        RefusedError: the record, or a commit that wrote it, breaks the fills' rule.
    """
    fills_history(repo, ref)
    try:
        text = git(repo, "show", f"{ref}:{EXPERIMENT}/{FILLS_NAME}")
    except subprocess.CalledProcessError:
        return {}
    return fills_from(text)


def need_fill(fills: dict[str, Any], key: str) -> dict[str, Any]:
    """One fill, or a refusal naming it.

    Raises:
        RefusedError: the fill is not on record yet.
    """
    found = fills.get(key)
    if not isinstance(found, dict) or not found:
        names = {"commits": "Commits filled", "sheet": "Sheet filled", "sets": "Set filled"}
        raise RefusedError(f'"{names[key]}" is not on record: the fact it fills is not known yet')
    return found


# ---- under a root: nothing through a symlink, nothing outside (R-PG-01b's reads) ----
#
# Every read, listing and removal under a root walks from the root's own descriptor, opening each
# directory relative to its parent's descriptor with O_NOFOLLOW, and acts on what it holds open:
# no path string is used again after a check, so a part swapped for a symlink between the two is
# never followed. Nothing that is not a regular file is ever opened for reading (O_NONBLOCK, so a
# FIFO cannot hold the open), and every walk and read is bounded. A bound that is hit, or a
# directory that cannot be opened, raises :class:`FailClosedError` with its cause.

MAX_DEPTH = 32
MAX_ENTRIES = 250_000
MAX_FILE_BYTES = 256 * 1024 * 1024

_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
_FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


class FailClosedError(Exception):
    """A walk or read hit a bound, or could not confirm what lies under a root."""


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
                raise FailClosedError(msg)
    return sorted(names)


def _read_fd(fd: int, where: str) -> bytes | None:
    """A held file's bytes if it is a regular file, at most :data:`MAX_FILE_BYTES`."""
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            return None
        data = f.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        msg = f"{where} is larger than {MAX_FILE_BYTES} bytes: the bound of a read"
        raise FailClosedError(msg)
    return data


def read_inside(root: Path, path: Path) -> bytes | None:
    """A regular file's bytes under ``root``, reached through no symlink; else ``None``.

    Raises:
        FailClosedError: the file is larger than the bound of a read.
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
        FailClosedError: the directory holds more entries than the bound of a walk, or stands there
            but cannot be opened as a directory.
    """
    with _dir_inside(root, parts) as fd:
        if fd is None:
            if os.path.lexists(Path(root).joinpath(*parts)):
                where = "/".join(parts) or Path(root).name
                msg = f"{where} could not be opened as a directory: what it holds is not confirmed"
                raise FailClosedError(msg)
            return []
        found = []
        for name in _names(fd, "/".join(parts) or "the root"):
            mode = _mode(name, fd)
            if mode is not None:
                found.append((name, mode))
        return found


def walk_inside(root: Path) -> Iterator[tuple[tuple[str, ...], int]]:
    """Every entry below ``root``, as its parts and own type, in name order; none followed.

    Raises:
        FailClosedError: a directory could not be opened, or the walk passed a bound.
    """
    count = [0]

    def below(fd: int, prefix: tuple[str, ...]) -> Iterator[tuple[tuple[str, ...], int]]:
        if len(prefix) >= MAX_DEPTH:
            msg = f"{'/'.join(prefix)} lies deeper than {MAX_DEPTH}: the depth bound of a walk"
            raise FailClosedError(msg)
        for name in _names(fd, "/".join(prefix) or "the root"):
            mode = _mode(name, fd)
            if mode is None:
                continue
            count[0] += 1
            if count[0] > MAX_ENTRIES:
                msg = f"the walk passed {MAX_ENTRIES} entries: the bound of a walk"
                raise FailClosedError(msg)
            parts = (*prefix, name)
            yield parts, mode
            if stat.S_ISDIR(mode):
                child = _open_dir(name, fd)
                if child is None:
                    msg = f"{'/'.join(parts)} could not be opened: what it holds is not confirmed"
                    raise FailClosedError(msg)
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
        raise FailClosedError(msg)
    try:
        yield from below(top, ())
    finally:
        os.close(top)


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
        FailClosedError: the file is larger than the bound of a read.
    """
    try:
        fd = os.open(path, _FILE_FLAGS)
    except OSError:
        return None
    return _read_fd(fd, Path(path).name)


def read_log(path: Path) -> tuple[list[dict[str, Any]], int]:
    """A JSON-lines log's objects, and how many lines did not parse as one.

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


def lane_roots(scratch: Path) -> list[Path]:
    """A run's review roots: ``lane-<k>`` under its scratch directory, or the directory itself.

    The instrument puts each lane's sessions under ``<scratch>/lane-<k>`` when it runs more than
    one lane, and under the scratch directory itself when it runs one.
    """
    lanes = sorted(
        name
        for name, mode in list_inside(scratch)
        if re.fullmatch(r"lane-[0-9]{1,2}", name) and stat.S_ISDIR(mode)
    )
    return [scratch / name for name in lanes] if lanes else [scratch]


def result_tokens(text: str | None) -> int | None:
    """The binary's own total for one session, from its stream's last ``result`` line."""
    found: dict[str, Any] | None = None
    for line in (text or "").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "result":
            found = event
    if found is None:
        return None
    usage = found.get("usage") or {}
    kinds = (
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    )
    return sum(int(usage.get(k) or 0) for k in kinds)
