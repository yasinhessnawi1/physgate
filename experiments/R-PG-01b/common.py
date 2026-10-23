"""R-PG-01b: the pins and places every script of the experiment shares (CRITERIA.md §2, §10, §14).

Nothing here reads a run's verdicts. Every value is the frozen file's, or a path it names; the
two facts filled after the freeze (arm F's manifest digest and the run commit's instrument tree)
are read from the filled ``CRITERIA.md`` on ``master`` by :func:`filled`, never typed here.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
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


def run_id(slot: int) -> str:
    """The run id of a slot (§2.6): the same form for both arms."""
    return f"rpb-{slot}"


def places(home: Path, slot: int, runs: Path | None = None) -> dict[str, Path]:
    """Every path of a slot (§2.6): its run directory, review root and installation."""
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
    """The sha256 of a file's bytes."""
    return sha256_bytes(Path(path).read_bytes())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """A JSON-lines file, one value per non-blank line."""
    return [json.loads(x) for x in Path(path).read_text().splitlines() if x.strip()]


def read_log(path: Path) -> tuple[list[dict[str, Any]], int]:
    """A run log's lines, and how many did not parse.

    A killed process can leave half a line, and a crashed one no file at all (no lines, none
    broken).
    """
    lines: list[dict[str, Any]] = []
    broken = 0
    for raw in Path(path).read_text(errors="replace").splitlines() if Path(path).is_file() else []:
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
