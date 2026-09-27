"""The injected-error corpus: its format, its manifest, and the words that would give it away.

A corpus is one directory:

- ``base.json``: the shared base design, a label and whole node payloads. It is
  the given design every artefact is a revision of.
- ``artefacts/<id>.json``: one artefact each. It holds the clean patch and the
  injected patch, both whole node payloads, written over the base as one
  revision; the error class, exactly one of four; the check expected to catch
  it; and a description of the error in physics terms. A propagation artefact
  also names the one edge whose target the change did not reach.
- ``sources.json``: the parts sheet the numbers cite, by row id, each row that
  is one number with its unit and the URL it was read from.
- ``MANIFEST.json``: the digest of every other file, the corpus's label and the
  model string of the sessions that wrote it.
- any ``*.md`` file: documentation, digested like the rest.

**The corpus is fixed before anything reads it.** Loading refuses a directory
whose files are not exactly the ones the manifest lists, byte for byte, so an
artefact changed after a run is a different corpus and says so.

**There is no menu of injections.** The format holds two patches and the
difference between them is the error, however its author chose to make it. A
fixed set of operations would itself steer which errors get written.

**Every number says where it comes from**: a URL; ``derived: ...``, arithmetic
over cited rows of the corpus's parts sheet (``sources.json``), which must give
the quantity's dimension under pint; or ``design: ...``, only for the closed
list of design choices. A property of a bought part is never a choice.

**Nothing a reviewer is shown may say what the corpus is.** Every string in every
node payload, keys included, is held to a list of telltale words (``inject``,
``mistake``, the class names followed by "error", and so on). The class, the
expected check and the description are the answers, and they stay in the
artefact's own fields, which no reviewer is given.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, cast

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
from physgate.gate.units import PINT_ERRORS, UnitRefusedError, parse
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
SOURCES_NAME = "sources.json"
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


#: The quantities a design chooses rather than buys, and the only ones a ``design:``
#: source may carry: a closed list, because a suffix such as ``_setpoint`` can be put
#: on any name and a list cannot. The common quantity list marks exactly these.
DESIGN_CHOICES: frozenset[str] = frozenset({"sample_rate", "loop_gain"})
_URL = re.compile(r"^https?://\S+$")
#: A cited row of the parts sheet: ``[R<section>.<row>]``, e.g. ``[R1.03]``, ``[R1a.02]``.
_ROW = r"R[0-9]+[a-z]?\.[0-9]{2}"
_ROW_REF = re.compile(rf"\[({_ROW})\]")
_ARITHMETIC = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)


def derivation(text: str) -> tuple[ast.expr, tuple[str, ...]]:
    """A ``derived:`` expression parsed, and the rows it cites, in order of first use.

    Every operand is a cited row of the parts sheet, ``[R1.03]``; the only numbers
    written into the expression are whole-number powers. Anything else (a node's
    quantity, a bare constant, a call) is refused, so a derived number is arithmetic
    over sourced numbers and never a guess folded into a formula.

    Raises:
        ValueError: the expression is not one of that form.
    """
    rows: list[str] = []

    def named(match: re.Match[str]) -> str:
        if match.group(1) not in rows:
            rows.append(match.group(1))
        return f"_row{rows.index(match.group(1))}"

    spelled = _ROW_REF.sub(named, text.strip())
    try:
        tree = ast.parse(spelled, mode="eval").body
    except SyntaxError as exc:
        msg = f"a derived source is arithmetic over cited rows: {text!r}"
        raise ValueError(msg) from exc

    def check(node: ast.expr, exponent: bool = False) -> None:
        if isinstance(node, ast.BinOp) and isinstance(node.op, _ARITHMETIC):
            check(node.left)
            check(node.right, exponent=isinstance(node.op, ast.Pow))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub | ast.UAdd):
            check(node.operand, exponent)
        elif isinstance(node, ast.Name) and re.fullmatch(r"_row[0-9]+", node.id):
            if exponent:
                msg = "a power is a whole number, not a cited row"
                raise ValueError(msg)
        elif exponent and isinstance(node, ast.Constant) and type(node.value) is int:
            return
        else:
            msg = f"every operand of a derived source is a cited row of the parts sheet: {text!r}"
            raise ValueError(msg)

    # A number is accepted only as a power, which has a base, so every expression
    # that passes cites at least one row.
    check(tree)
    return tree, tuple(rows)


def source_problem(name: str, source: str) -> str | None:
    """Why ``source`` is not a legal source for the quantity ``name``, or ``None``.

    Every number says where it comes from, in one of three forms: the URL of the
    row it was copied from; ``derived: <arithmetic over cited rows>``; or
    ``design: <reason>``, only for a quantity on the closed list of design choices.
    Whether the cited rows exist, and whether the arithmetic gives the quantity's
    dimension, is checked when the corpus loads, against its parts sheet.
    """
    head, _, rest = source.partition(":")
    if head in ("derived", "design") and not rest.strip():
        return f"a {head} source says what it is: {source!r}"
    if head == "design" and name not in DESIGN_CHOICES:
        return f"{name!r} is not on the list of design choices, so it is not a design choice"
    if head == "derived":
        try:
            derivation(rest)
        except ValueError as exc:
            return str(exc)
    if head not in ("derived", "design") and not _URL.match(source):
        return f"a source is a URL, 'derived: ...' or 'design: ...', not {source!r}"
    return None


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
        for name, quantity in payload.get("quantities", {}).items():
            problem = source_problem(str(name), str(quantity["source"]))
            if problem is not None:
                msg = f"node {payload.get('id')!r}: {problem}"
                raise ValueError(msg)
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


RowId = Annotated[str, StringConstraints(pattern=rf"^{_ROW}$")]


class SourceRow(_Frozen):
    """One row of the parts sheet: a number with its unit where the row is one number."""

    quantity: NonEmptyStr
    #: ``None`` for a row that is not one number (a range, a text): it cannot be cited.
    value: float | int | None
    unit: NonEmptyStr | None
    url: NonEmptyStr

    @model_validator(mode="after")
    def _a_number_has_its_unit(self) -> SourceRow:
        if (self.value is None) != (self.unit is None):
            msg = "a row's number and unit are given together, or neither is"
            raise ValueError(msg)
        return self


class Sources(_Frozen):
    """The parts sheet the design's numbers come from, by row."""

    label: NonEmptyStr
    rows: dict[RowId, SourceRow]


@dataclass(frozen=True)
class Corpus:
    """A corpus as loaded: held to its manifest, every artefact validated."""

    root: Path
    manifest: Manifest
    #: The digest of the manifest file's bytes: the corpus's identity in a run's record.
    manifest_sha256: str
    base: Base
    sources: Sources
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
            rel not in (BASE_NAME, SOURCES_NAME)
            and not rel.endswith(".md")
            and not (is_artefact and rel.endswith(".json"))
        ):
            msg = "a corpus holds its base, its artefacts and documentation, and nothing else"
            raise CorpusError(msg, path=rel)
    if BASE_NAME not in manifest.files:
        msg = "the corpus has no base design"
        raise CorpusError(msg, root=str(root))
    if SOURCES_NAME not in manifest.files:
        msg = "the corpus has no parts sheet for its numbers to cite"
        raise CorpusError(msg, root=str(root))
    base = _parse(Base, root / BASE_NAME, root)
    sources = _parse(Sources, root / SOURCES_NAME, root)
    numbers = _numbers(sources)
    _derivations_hold(numbers, "base", base.nodes, dimension=True)
    artefacts = []
    for rel in sorted(
        p for p in manifest.files if p.startswith(ARTEFACTS_DIRNAME + "/") and p.endswith(".json")
    ):
        artefact = _parse(CorpusArtefact, root / rel, root)
        if f"{ARTEFACTS_DIRNAME}/{artefact.id}.json" != rel:
            msg = "an artefact's file is named for its id"
            raise CorpusError(msg, path=rel, id=artefact.id)
        _writable_over(base, artefact)
        _derivations_hold(numbers, artefact.id, artefact.clean.nodes, dimension=True)
        # The injected patch may carry the error in a derived quantity's unit or value,
        # so only its citations are held there, not its arithmetic.
        _derivations_hold(numbers, artefact.id, artefact.injected.nodes, dimension=False)
        artefacts.append(artefact)
    return Corpus(
        root=root,
        manifest=manifest,
        manifest_sha256=digest(manifest_path),
        base=base,
        sources=sources,
        artefacts=tuple(artefacts),
    )


def _numbers(sources: Sources) -> dict[str, Any]:
    """Every row that is one number, as a quantity under the gate's own unit registry.

    Raises:
        CorpusError: a row's unit is not one the registry reads.
    """
    found: dict[str, Any] = {}
    for row_id, row in sources.rows.items():
        if row.value is None or row.unit is None:
            continue
        try:
            found[row_id] = parse(row.value, row.unit)
        except UnitRefusedError as exc:
            msg = "a row of the parts sheet has a unit the gate cannot read"
            raise CorpusError(msg, row=row_id, unit=row.unit) from exc
    return found


def _evaluate(node: ast.expr, operands: dict[str, Any]) -> Any:  # noqa: ANN401 - pint's type
    if isinstance(node, ast.BinOp):
        left, right = _evaluate(node.left, operands), _evaluate(node.right, operands)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        return left**right
    if isinstance(node, ast.UnaryOp):
        value = _evaluate(node.operand, operands)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.Name):
        return operands[node.id]
    return cast("ast.Constant", node).value


def _spelled(dimensionality: Mapping[str, Any]) -> str:
    """A dimension as text, ``[current]*[length]^-1``; pint's own spelling fails on fractions."""
    parts = [k if v == 1 else f"{k}^{v}" for k, v in sorted(dict(dimensionality).items())]
    return "*".join(parts) or "dimensionless"


def _derivations_hold(
    numbers: dict[str, Any], where: str, nodes: tuple[Payload, ...], *, dimension: bool
) -> None:
    """Refuse a derived quantity that cites a row the sheet lacks, or has another dimension.

    Raises:
        CorpusError: a cited row is not on the sheet or is not one number; or, where
            ``dimension`` holds, the arithmetic does not check under pint or does not
            give the dimension of the quantity's own unit.
    """
    for payload in nodes:
        for name, quantity in payload.get("quantities", {}).items():
            head, _, rest = str(quantity["source"]).partition(":")
            if head != "derived":
                continue
            tree, rows = derivation(rest)
            missing = [r for r in rows if r not in numbers]
            if missing:
                msg = "a derived quantity cites a row that is not one number on the parts sheet"
                raise CorpusError(
                    msg, where=where, node=str(payload["id"]), quantity=name, rows=",".join(missing)
                )
            if not dimension:
                continue
            operands = {f"_row{n}": numbers[r] for n, r in enumerate(rows)}
            try:
                derived = _evaluate(tree, operands)
                declared = parse(quantity["value"], quantity["unit"])
                same = derived.dimensionality == declared.dimensionality
            except (*PINT_ERRORS, UnitRefusedError, AttributeError) as exc:
                msg = "a derived quantity's arithmetic does not check under pint"
                raise CorpusError(
                    msg, where=where, node=str(payload["id"]), quantity=name, reason=str(exc)
                ) from exc
            if not same:
                msg = "a derived quantity's arithmetic gives another dimension than its unit"
                raise CorpusError(
                    msg,
                    where=where,
                    node=str(payload["id"]),
                    quantity=name,
                    derived=_spelled(derived.dimensionality),
                    declared=_spelled(declared.dimensionality),
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

    The propagation check is the cross-domain one (ARCH-080, row 7), so each
    propagation artefact's edge joins two nodes of different domains.

    Raises:
        CorpusError: a class has other than ten artefacts; two propagation
            artefacts name the same edge, so ten errors would be fewer than ten;
            or an edge stays within one domain.
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
    for artefact in corpus.artefacts:
        if artefact.edge is None:
            continue
        source = artefact.injected.node(artefact.edge.source) or {}
        target = artefact.clean.node(artefact.edge.target) or {}
        if source.get("domain") == target.get("domain"):
            msg = "a propagation artefact's edge joins two domains"
            raise CorpusError(msg, artefact=artefact.id, domain=str(source.get("domain")))
