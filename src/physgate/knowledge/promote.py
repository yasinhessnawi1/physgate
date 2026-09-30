"""``physgate knowledge promote``: the library's only writer, and it is a human (ARCH-100).

Promotion has two guards, not one. ``require_interactive`` refuses to run unless
``stdin`` is a real terminal — it cannot be satisfied from inside an agent
session, a script, or a pipe, by design. The actual write (``_apply``) carries
no such check itself, so it can be tested directly and exhaustively without a
terminal; nothing in this module calls it without ``require_interactive``
having already run first, and the CLI is the one caller that matters.

A promoted candidate is written whole into its destination — a `kind:
"standards"` candidate replaces `knowledge/<domain>/standards.md` outright
(ARCH-101: one standards file per domain, and promoting a new draft is the
human's explicit act of replacing it); a `kind: "skill"` or `"antipattern"`
candidate creates `knowledge/<domain>/skill.md` if none exists yet, or is
appended to it if one already does, matching ARCH-100's own model of a skill
file accumulating from many episodes over time. Either way the candidate is
removed from `staging/` once promoted, so `staging/` always reflects exactly
what is still pending, and a candidate id cannot be promoted twice.

Every promotion appends one line to `knowledge/promotions.jsonl`: which
candidate, which kind and domain, which destination, who approved it, and
when. This is the record ARCH-100's own acceptance test reads: the library's
content, minus what this file's writes account for, is empty.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from physgate.knowledge.exceptions import KnowledgeError
from physgate.knowledge.staging import STAGING_ROOT, Candidate, Kind

#: Where the library lives, relative to a worktree root — the same convention
#: `loader.py` and `hooks/settings.py`'s knowledge-root discovery already use.
KNOWLEDGE_ROOT = Path("knowledge")

#: One line per promotion, appended, never rewritten.
PROMOTIONS_NAME = "promotions.jsonl"

STANDARDS_NAME = "standards.md"
SKILL_NAME = "skill.md"


class PromotionError(KnowledgeError):
    """A promotion refused: not interactive, no name to approve it, or no such candidate."""


def require_interactive() -> None:
    """Refuse unless ``stdin`` is a real terminal.

    The only guard between an agent session and the library. Nothing in this
    module, and nothing calling it, may pass a flag that skips this check for
    a real promotion — a test calls it directly to prove it refuses, exactly
    as a real non-interactive run would.

    Raises:
        PromotionError: ``stdin`` is not a TTY.
    """
    if not sys.stdin.isatty():
        msg = (
            "promotion refuses to run non-interactively: it moves a candidate into the "
            "library only when a human is at a terminal to approve it"
        )
        raise PromotionError(msg)


def _destination(domain: str, kind: Kind, root: Path) -> Path:
    name = STANDARDS_NAME if kind == "standards" else SKILL_NAME
    return Path(root) / domain / name


def _find(candidate_id: str, staging_root: Path) -> tuple[Kind, Candidate, Path] | None:
    kinds: tuple[Kind, ...] = ("standards", "skill", "antipattern")
    for kind in kinds:
        path = Path(staging_root) / kind / f"{candidate_id}.json"
        if path.is_file():
            return kind, Candidate.model_validate_json(path.read_text(encoding="utf-8")), path
    return None


def _apply(
    candidate_id: str,
    *,
    by: str,
    staging_root: Path,
    knowledge_root: Path,
    promotions_path: Path,
) -> Path:
    """Write the candidate into the library, log the promotion, remove it from staging.

    Carries no interactivity check of its own — ``require_interactive`` is the
    caller's job, always run first for a real promotion.

    Raises:
        PromotionError: ``by`` is empty, or no candidate with ``candidate_id``
            is staged.
    """
    if not by.strip():
        msg = "promotion needs the name of the human approving it"
        raise PromotionError(msg, candidate_id=candidate_id)
    found = _find(candidate_id, staging_root)
    if found is None:
        msg = "no staged candidate has this id"
        raise PromotionError(msg, candidate_id=candidate_id)
    kind, candidate, candidate_path = found
    destination = _destination(candidate.domain, kind, knowledge_root)
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = candidate.content.rstrip() + "\n"
    if kind == "standards" or not destination.exists():
        destination.write_text(text, encoding="utf-8")
    else:
        with destination.open("a", encoding="utf-8") as appended:
            appended.write("\n---\n\n" + text)
    event = {
        "candidate_id": candidate.candidate_id,
        "kind": kind,
        "domain": candidate.domain,
        "episode_id": candidate.episode_id,
        "destination": str(destination),
        "promoted_by": by,
        "promoted": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    promotions_path.parent.mkdir(parents=True, exist_ok=True)
    with promotions_path.open("a", encoding="utf-8") as log:
        log.write(json.dumps(event, sort_keys=True) + "\n")
    candidate_path.unlink()
    return destination


def promote(
    candidate_id: str,
    *,
    by: str,
    staging_root: Path = STAGING_ROOT,
    knowledge_root: Path = KNOWLEDGE_ROOT,
    promotions_path: Path | None = None,
) -> Path:
    """Refuse unless interactive, then move one staged candidate into the library.

    The one function the real CLI calls. Everything it does beyond the
    interactivity check is `_apply`, tested directly and without a terminal.

    Raises:
        PromotionError: ``stdin`` is not a TTY, ``by`` is empty, or no
            candidate with ``candidate_id`` is staged.
    """
    require_interactive()
    resolved_promotions = (
        Path(promotions_path)
        if promotions_path is not None
        else Path(knowledge_root) / PROMOTIONS_NAME
    )
    return _apply(
        candidate_id,
        by=by,
        staging_root=staging_root,
        knowledge_root=knowledge_root,
        promotions_path=resolved_promotions,
    )


def promotions(
    promotions_path: Path = KNOWLEDGE_ROOT / PROMOTIONS_NAME,
) -> tuple[dict[str, str], ...]:
    """Every promotion recorded so far, oldest first; an empty tuple if none yet."""
    path = Path(promotions_path)
    if not path.is_file():
        return ()
    return tuple(json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line)
