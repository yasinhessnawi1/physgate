"""The injected-error corpus: its format, its manifest, and the words that would give it away.

A corpus is one directory:

- ``base.json``: the shared base design, a label and whole node payloads. It is
  the given design every artefact is a revision of.
- ``artefacts/<id>.json``: one artefact each. It holds the clean patch and the
  injected patch, both whole node payloads, written over the base as one
  revision; the error class, exactly one of four; the check expected to catch
  it; and a description of the error in physics terms. A propagation artefact
  also names the one edge whose target the change did not reach.
- ``MANIFEST.json``: the digest of every other file, the corpus's label and the
  model string of the sessions that wrote it.
- any ``*.md`` file: documentation, digested like the rest.

**The corpus is fixed before anything reads it.** Loading refuses a directory
whose files are not exactly the ones the manifest lists, byte for byte, so an
artefact changed after a run is a different corpus and says so.

**There is no menu of injections.** The format holds two patches and the
difference between them is the error, however its author chose to make it. A
fixed set of operations would itself steer which errors get written.

**Nothing a reviewer is shown may say what the corpus is.** Every string in every
node payload, keys included, is held to a list of telltale words (``inject``,
``mistake``, the class names followed by "error", and so on). The class, the
expected check and the description are the answers, and they stay in the
artefact's own fields, which no reviewer is given.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from physgate.evaluation.inject.exceptions import CorpusError
from physgate.orchestrator.common import ModelString, NonEmptyStr, first_problem
from physgate.orchestrator.protocols import CheckName
from physgate.state.exceptions import DesignStateError
from physgate.state.schema import NODE_ID_PATTERN, validate_node

#: The four error classes of risk row 1, fixed in advance.
ErrorClass = Literal["unit", "magnitude", "equilibrium", "propagation"]
ERROR_CLASSES: tuple[ErrorClass, ...] = ("unit", "magnitude", "equilibrium", "propagation")
#: Artefacts per class in a complete corpus.
PER_CLASS = 10

MANIFEST_NAME = "MANIFEST.json"
BASE_NAME = "base.json"
ARTEFACTS_DIRNAME = "artefacts"

ArtefactId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{0,31}$")]
NodeId = Annotated[str, StringConstraints(pattern=NODE_ID_PATTERN.pattern, max_length=128)]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
#: A path inside the corpus: no segment starts with a dot, so none is ``.`` or ``..``.
RelativePath = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Za-z0-9_-][A-Za-z0-9._-]*(/[A-Za-z0-9_-][A-Za-z0-9._-]*)*$"),
]
Payload = dict[str, Any]

#: Words that would tell a reader what the corpus is or where its answer lies. Each
#: is matched as a word on text folded to lower case with ``_ - . /`` read as spaces,
#: so ``stall_current_injected`` is caught. "plant" alone is not here: it is the
#: control engineer's word for the system being controlled.
TELLTALES: tuple[str, ...] = (
    r"\binject",
    r"\bplanted\b",
    r"\bdeliberate",
    r"\bmistake",
    r"\bcorpus",
    r"\bcorpora\b",
    r"\banswer",
    r"\btwin\b",
    r"\bphysgate\b",
    r"\bphysics gate\b",
    r"\breviewer",
    r"\bexpected check\b",
    r"\berror class\b",
    r"\b(unit|units|magnitude|equilibrium|propagation) error",
    r"\bwrong\b",
    r"\bfaulty\b",
    r"\bincorrect",
    r"\bbug\b",
)
_TELLTALE = re.compile("|".join(TELLTALES))


def telltales(text: str) -> list[str]:
    """Every telltale word in ``text``, as matched, sorted and each once."""
    folded = " ".join(re.sub(r"[_\-./]+", " ", text.casefold()).split())
    return sorted({m.group(0) for m in _TELLTALE.finditer(folded)})


def strings_of(value: object) -> Iterator[str]:
    """Every string in a JSON value: keys, values and list items, depth first."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from strings_of(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from strings_of(item)


def _whole_nodes(nodes: tuple[Payload, ...]) -> tuple[Payload, ...]:
    ids = [str(n.get("id")) for n in nodes]
    if len(set(ids)) != len(ids):
        msg = "a node appears twice in one set of nodes"
        raise ValueError(msg)
    for payload in nodes:
        try:
            validate_node(payload)
        except (DesignStateError, ValidationError) as exc:
            msg = f"node {payload.get('id')!r} is not a whole node: {exc}"
            raise ValueError(msg) from exc
        found = sorted({w for s in strings_of(payload) for w in telltales(s)})
        if found:
            msg = f"node {payload.get('id')!r} carries words that give the corpus away: {found}"
            raise ValueError(msg)
    return nodes


#: Whole node payloads, at least one, each id once, none carrying a telltale.
WholeNodes = Annotated[tuple[Payload, ...], Field(min_length=1), AfterValidator(_whole_nodes)]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class Patch(_Frozen):
    """Whole node payloads written over the base design as one revision, in order."""

    nodes: WholeNodes

    def ids(self) -> tuple[str, ...]:
        """The node ids this patch writes, in order."""
        return tuple(str(n["id"]) for n in self.nodes)

    def node(self, node_id: str) -> Payload | None:
        """This patch's payload for ``node_id``, if it writes one."""
        return next((n for n in self.nodes if n["id"] == node_id), None)

    def canonical(self) -> str:
        """The patch as one string, keys sorted, so two patches compare by content."""
        return json.dumps(list(self.nodes), sort_keys=True)


class Edge(_Frozen):
    """One ``constrains`` edge: from the node that changed to the node it constrains."""

    source: NodeId
    target: NodeId

    @model_validator(mode="after")
    def _two_nodes(self) -> Edge:
        if self.source == self.target:
            msg = "an edge joins two different nodes"
            raise ValueError(msg)
        return self


class CorpusArtefact(_Frozen):
    """One artefact: a revision of the base, clean and with one error injected."""

    id: ArtefactId
    error_class: ErrorClass
    #: The check the corpus author expects to catch the error, by name.
    expected_check: CheckName
    #: The producing role whose paired reviewer reviews the revision.
    assigned_role: NonEmptyStr
    #: What the injected error is, in physics terms.
    description: NonEmptyStr
    #: For a propagation error, the edge whose target the change did not reach.
    edge: Edge | None
    clean: Patch
    injected: Patch

    @model_validator(mode="after")
    def _one_error_of_its_class(self) -> CorpusArtefact:
        if (self.edge is None) == (self.error_class == "propagation"):
            msg = "a propagation artefact names its edge, and no other artefact names one"
            raise ValueError(msg)
        if self.clean.canonical() == self.injected.canonical():
            msg = "the injected patch is the clean patch: there is no error in it"
            raise ValueError(msg)
        if self.edge is not None:
            source = self.injected.node(self.edge.source)
            if source is None or self.clean.node(self.edge.source) is None:
                msg = "a propagation artefact's source is written by both patches"
                raise ValueError(msg)
            if self.edge.target not in source.get("constrains", []):
                msg = "a propagation artefact's source constrains its target"
                raise ValueError(msg)
            if self.clean.node(self.edge.target) is None:
                msg = "the clean patch of a propagation artefact reaches the edge's target"
                raise ValueError(msg)
        return self


class Base(_Frozen):
    """The shared base design, and what it is."""

    #: What the design is and where its numbers come from, e.g. that it is a stand-in.
    label: NonEmptyStr
    nodes: WholeNodes


class Manifest(_Frozen):
    """Every file of the corpus by digest, and who wrote it."""

    format: Literal[1]
    label: NonEmptyStr
    #: The model string the corpus sessions ran on. No reviewer may run on it.
    author_model: ModelString
    files: dict[RelativePath, Sha256]


@dataclass(frozen=True)
class Corpus:
    """A corpus as loaded: held to its manifest, every artefact validated."""

    root: Path
    manifest: Manifest
    #: The digest of the manifest file's bytes: the corpus's identity in a run's record.
    manifest_sha256: str
    base: Base
    #: Every artefact, in id order.
    artefacts: tuple[CorpusArtefact, ...]


def digest(path: Path) -> str:
    """The sha256 of a file's bytes."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def files_under(root: Path) -> dict[str, str]:
    """Every file under ``root`` but the manifest, by relative path, with its digest.

    Raises:
        CorpusError: an entry is a symbolic link, or neither a file nor a directory.
            A link can point anywhere, so the bytes digested would not be the corpus.
    """
    found: dict[str, str] = {}
    for path in sorted(Path(root).rglob("*")):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            msg = "a corpus holds files and directories only"
            raise CorpusError(msg, path=rel)
        if path.is_file() and rel != MANIFEST_NAME:
            found[rel] = digest(path)
    return found


def manifest_for(root: Path, *, label: str, author_model: str) -> Manifest:
    """The manifest of the corpus at ``root`` as it is on disk now."""
    return Manifest(format=1, label=label, author_model=author_model, files=files_under(root))


def write_manifest(root: Path, manifest: Manifest) -> None:
    """Write ``manifest`` into the corpus at ``root``, in one stable spelling."""
    text = json.dumps(manifest.model_dump(mode="json"), indent=1, sort_keys=True) + "\n"
    (Path(root) / MANIFEST_NAME).write_text(text)


def _parse[M: BaseModel](model: type[M], path: Path, root: Path) -> M:
    try:
        return model.model_validate_json(path.read_bytes())
    except ValidationError as exc:
        msg = "a corpus file is not what its place in the corpus requires"
        raise CorpusError(
            msg, path=path.relative_to(root).as_posix(), reason=first_problem(exc)
        ) from exc


def load_corpus(root: Path) -> Corpus:
    """Load the corpus at ``root``, held to its manifest.

    Raises:
        CorpusError: the manifest is missing or malformed; a file differs from it,
            is missing, or is not listed; a file is not a valid base or artefact;
            or an artefact writes a node the base does not let it write.
    """
    root = Path(root)
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        msg = "the corpus has no manifest"
        raise CorpusError(msg, root=str(root))
    manifest = _parse(Manifest, manifest_path, root)
    on_disk = files_under(root)
    if on_disk != manifest.files:
        changed = sorted(
            p for p in on_disk.keys() & manifest.files.keys() if on_disk[p] != manifest.files[p]
        )
        msg = "the corpus on disk is not the one its manifest lists"
        raise CorpusError(
            msg,
            changed=",".join(changed[:5]) or "none",
            missing=",".join(sorted(manifest.files.keys() - on_disk.keys())[:5]) or "none",
            unlisted=",".join(sorted(on_disk.keys() - manifest.files.keys())[:5]) or "none",
        )
    for rel in manifest.files:
        is_artefact = rel.startswith(ARTEFACTS_DIRNAME + "/") and rel.count("/") == 1
        if (
            rel != BASE_NAME
            and not rel.endswith(".md")
            and not (is_artefact and rel.endswith(".json"))
        ):
            msg = "a corpus holds its base, its artefacts and documentation, and nothing else"
            raise CorpusError(msg, path=rel)
    if BASE_NAME not in manifest.files:
        msg = "the corpus has no base design"
        raise CorpusError(msg, root=str(root))
    base = _parse(Base, root / BASE_NAME, root)
    artefacts = []
    for rel in sorted(
        p for p in manifest.files if p.startswith(ARTEFACTS_DIRNAME + "/") and p.endswith(".json")
    ):
        artefact = _parse(CorpusArtefact, root / rel, root)
        if f"{ARTEFACTS_DIRNAME}/{artefact.id}.json" != rel:
            msg = "an artefact's file is named for its id"
            raise CorpusError(msg, path=rel, id=artefact.id)
        _writable_over(base, artefact)
        artefacts.append(artefact)
    return Corpus(
        root=root,
        manifest=manifest,
        manifest_sha256=digest(manifest_path),
        base=base,
        artefacts=tuple(artefacts),
    )


def _writable_over(base: Base, artefact: CorpusArtefact) -> None:
    """Refuse a patch the store would refuse over the base: the check before any run.

    Raises:
        CorpusError: a patch rewrites an interface node, which is fixed once written,
            or gives a node of the base another owner, which is a write by another role.
    """
    given = {str(n["id"]): n for n in base.nodes}
    for patch in (artefact.clean, artefact.injected):
        for payload in patch.nodes:
            before = given.get(str(payload["id"]))
            if before is None:
                continue
            if before["kind"] == "interface":
                msg = "a patch rewrites an interface node, which the store keeps as first written"
                raise CorpusError(msg, artefact=artefact.id, node=str(payload["id"]))
            if before["owner_role"] != payload["owner_role"]:
                msg = "a patch gives a node of the base another owner"
                raise CorpusError(msg, artefact=artefact.id, node=str(payload["id"]))


def require_complete(corpus: Corpus) -> None:
    """Refuse a corpus that is not the measurement's: ten per class, ten distinct edges.

    Raises:
        CorpusError: a class has other than ten artefacts, or two propagation
            artefacts name the same edge, so ten errors would be fewer than ten.
    """
    counts = {c: sum(a.error_class == c for a in corpus.artefacts) for c in ERROR_CLASSES}
    if any(n != PER_CLASS for n in counts.values()):
        msg = f"a complete corpus has {PER_CLASS} artefacts of each class"
        raise CorpusError(msg, **{c: str(n) for c, n in counts.items()})
    edges = {(a.edge.source, a.edge.target) for a in corpus.artefacts if a.edge is not None}
    if len(edges) != PER_CLASS:
        msg = (
            f"a complete corpus's {PER_CLASS} propagation artefacts name {PER_CLASS} distinct edges"
        )
        raise CorpusError(msg, distinct=str(len(edges)))
