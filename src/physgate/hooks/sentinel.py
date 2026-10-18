"""The second layer: compare every protected path after every call, and put back what moved.

The layers before this one refuse a write they can see coming. A shell cannot be
modelled completely — a path built from a variable, a substitution, a string
assembled inside a script, an archive, a patch — so this layer does not try to
see the write coming. It compares what the protected paths are now with what
they were, at every hook of every tool: before each call, after each call
whether it succeeded or failed (a failing command fires only the failure
event), and when the session stops and ends. A change that lands between
hooks is therefore caught at the next one, not only a change made during a
shell call.

What it does with a change depends on the root, as the session configuration
says:

- ``revert``: put it back. A modified or deleted file is restored from the
  bytes kept when the session started, by replacing it; anything new, or of the
  wrong type, is moved aside into the session's quarantine, never deleted. The
  call is reported as refused, with the paths.
- ``journal``: the graph store's journal. The orchestrator appends to it while
  sessions run, so an append cannot be told from an agent's; the check is that
  the bytes already there are unchanged, and an append is left to the store's
  own guard, which refuses on the orchestrator's next call when the journal
  moved under its handle. That is sound only if the orchestrator treats that
  refusal as an incident and never reopens and continues, because a reopen
  would replay an agent's line as genuine. The node files beside it are
  derived from the journal: one that no longer holds what the journal says, or
  that is missing while the journal names it, is rebuilt from the journal's
  newest line for it, with the store's own write, and every call after it is
  refused. A node's name becomes a path only through the store's own name rule;
  a node directory replaced by a link, or a journal line naming a node no store
  could serve, halts the session with nothing rebuilt.
- ``halt``: the code the hooks run from. It cannot be put back by the code it
  runs, and a hook running on changed code cannot be trusted to say so, so this
  is detection at best: when it is seen, every later call is refused. What
  protects the installation is that no agent tool can write it, and in the end
  an installation the session's user cannot write at all.
- ``log``: files other processes change legitimately; a change is recorded.

The records live in the hook state directory, which the hooks themselves write
and which is protected only by the layers that refuse writes before they
happen. That is the same-user limit: anything a hook can write, a command run
as the same user can write too.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
import time
from typing import TYPE_CHECKING

from physgate.hooks import withheld
from physgate.hooks.journal_view import Head, heads
from physgate.hooks.runtime import ALLOW, Decision, HookSpec, refuse
from physgate.hooks.snapshot import BlobStore, Entry, file_digest, quarantine, record, signature
from physgate.hooks.snapshot import signatures as take_signatures
from physgate.hooks.state import append_log, session_dir

if TYPE_CHECKING:
    from typing import Any

    from physgate.hooks.views import ConfigView, InputView

PUT_BACK = (
    "Protected paths changed during this session and were put back: {paths}. Protected "
    "paths are not written by agent sessions; anything new was moved aside, not deleted."
)
HALTED = (
    "The code the hooks run from changed during this session ({paths}), so nothing the hooks "
    "decide can be trusted, and every call is refused."
)
NODE_MISMATCH = (
    "A graph node file does not hold what the journal says it holds ({paths}). Node files are "
    "written by the orchestrator alone: a file the journal names is rebuilt from the journal, "
    "and every call is refused."
)
UNRESTORABLE = (
    "A protected path changed and could not be put back ({paths}); every call is refused."
)
LINKED = (
    "A held-out or answer-key file has a second name, changed, or cannot be checked ({paths}); "
    "a second name can be read where the first is withheld, so every call is refused."
)

#: Where the held-out and answer-key tripwire runs: the session's start and its end.
#: (The orchestrator checks again before it commits the attempt.)
WITHHELD_EVENTS = frozenset({"SessionStart", "SessionEnd"})


def _withheld_roots(config: ConfigView) -> tuple[str, ...]:
    return (*config.held_out, *config.answer_keys)


def _roots(config: ConfigView, watch: str) -> list[str]:
    return [root.path for root in config.protected_roots if root.watch == watch]


def _exceptions(config: ConfigView, watch: str) -> list[str]:
    """Every path a root of this ``watch`` kind excludes from its own protection.

    Matches ``paths.py``'s ``protection()``, which already treats a root's own
    ``exceptions`` as not protected by that root: this is the same carve-out,
    applied to what the sentinel snapshots and reverts rather than to what it
    refuses before a write. Without it, a legitimate write inside the
    exception (``knowledge/staging/`` inside ``knowledge/``) would succeed at
    the first layer and then be silently put back by this one, the very next
    hook event.
    """
    return [
        exception
        for root in config.protected_roots
        if root.watch == watch
        for exception in root.exceptions
    ]


def _frozen_experiment_paths(config: ConfigView) -> list[str]:
    """Every frozen experiment directory and every criteria file, as revert roots."""
    out: list[str] = []
    for rule in config.experiments:
        if not os.path.isdir(rule.root):
            continue
        for name in sorted(os.listdir(rule.root)):
            experiment = os.path.join(rule.root, name)
            if not os.path.isdir(experiment) or os.path.islink(experiment):
                continue
            files = [(d, f) for d, _, fs in os.walk(experiment) for f in fs]
            if any(f.casefold() == rule.frozen_marker.casefold() for _, f in files):
                out.append(experiment)
                continue
            out.extend(
                os.path.join(d, f)
                for d, f in files
                if f.casefold() == rule.always_frozen_name.casefold()
            )
    return out


#: What the two rare paths import beyond an ordinary hook: the validation library
#: and the state package, and the standard library they bring with them. An
#: ordinary hook no longer loads any of it, so the halt record would never see it;
#: the first hook finds these files without importing them instead. A test runs
#: both rare paths and fails if either loads a file under the installation that
#: this list leaves out, so a new import upstream cannot slip past it.
LAZY_MODULES = (
    "pydantic", "pydantic_core", "annotated_types", "typing_extensions", "typing_inspection",
    "physgate.state",
    "_bisect", "_bz2", "_compression", "_contextvars", "_csv", "_datetime", "_decimal",
    "_lzma", "_opcode", "_osx_support", "_random", "_sha2", "_socket", "_struct", "_uuid",
    "_weakrefset", "_zoneinfo", "array", "ast", "base64", "binascii", "bisect", "bz2", "calendar",
    "contextvars", "copy", "csv", "dataclasses", "datetime", "decimal", "dis", "email",
    "fractions", "importlib", "inspect", "ipaddress", "linecache", "locale", "lzma", "math",
    "ntpath", "numbers", "opcode", "pathlib", "platform", "quopri", "random", "select", "selectors",
    "shutil", "socket", "string", "struct", "sysconfig", "tempfile", "textwrap", "threading",
    "token", "tokenize", "urllib", "uuid", "weakref", "zipfile", "zlib", "zoneinfo",
)  # fmt: skip
_CODE_SUFFIXES = (".py", ".so", ".pyd")


def _lazy_code() -> list[str]:
    """The files of :data:`LAZY_MODULES`, found without importing any of them."""
    # Imported here: only the first hook of a session needs it.
    import importlib.util

    files: list[str] = []
    for name in LAZY_MODULES:
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            continue
        if spec is None:
            continue
        if spec.submodule_search_locations:
            for location in spec.submodule_search_locations:
                for directory, _, names in os.walk(location):
                    files.extend(
                        os.path.join(directory, n) for n in names if n.endswith(_CODE_SUFFIXES)
                    )
        elif spec.origin and os.path.isfile(spec.origin):
            files.append(spec.origin)
        elif spec.origin == "frozen":
            # A frozen standard-library module still names its source file, and
            # that is the file a loaded module's record points at.
            source = getattr(spec.loader_state, "filename", None)
            if isinstance(source, str) and os.path.isfile(source):
                files.append(source)
    stdlib = os.path.dirname(os.__file__)
    files.extend(
        os.path.join(stdlib, n)
        for n in os.listdir(stdlib)
        if n.startswith("_sysconfigdata_") and n.endswith(".py")
    )
    return files


def _loaded_code(config: ConfigView, also: list[str] | None = None) -> list[str]:
    """The files of the code this hook process has loaded, and ``also``, under the halt roots."""
    halt_roots = [os.path.realpath(r) for r in _roots(config, "halt")]
    files = {os.path.realpath(sys.executable)}
    # The same answer as resolving every file, found by resolving each directory
    # once: a hundred modules live in a dozen directories, and this runs at
    # every hook. A file that is itself a link is still resolved whole.
    directories: dict[str, str] = {}
    paths = [getattr(module, "__file__", None) for module in list(sys.modules.values())]
    for path in [*paths, *(also or [])]:
        if not path:
            continue
        if os.path.islink(path):
            files.add(os.path.realpath(path))
            continue
        head, tail = os.path.split(os.path.abspath(path))
        if head not in directories:
            directories[head] = os.path.realpath(head)
        files.add(os.path.join(directories[head], tail))
    for directory in {os.path.dirname(p) for p in files if p.endswith("site.py")} | set(sys.path):
        if os.path.isdir(directory):
            files.update(
                os.path.join(directory, n) for n in os.listdir(directory) if n.endswith(".pth")
            )
    return sorted(
        f for f in files if any(f == r or f.startswith(r.rstrip("/") + "/") for r in halt_roots)
    )


def _entry_json(entry: Entry) -> list[Any]:
    return [list(entry.signature), entry.digest, entry.link]


def _entry(raw: list[Any]) -> Entry:
    return Entry(tuple(raw[0]), raw[1], raw[2])


class _State:
    def __init__(self, directory: str) -> None:
        self.directory = directory
        self.blobs = BlobStore(os.path.join(directory, "blobs"))
        self.quarantine = os.path.join(directory, "quarantine")
        self.path = os.path.join(directory, "baseline.json")
        self.loaded_text: str | None = None

    def load(self) -> dict[str, Any] | None:
        if not os.path.exists(self.path):
            return None
        with open(self.path) as handle:
            self.loaded_text = handle.read()
        loaded: dict[str, Any] = json.loads(self.loaded_text)
        return loaded

    def save(self, base: dict[str, Any]) -> None:
        text = json.dumps(base, sort_keys=True)
        if text == self.loaded_text:
            # The record is byte for byte what was read under the same lock:
            # rewriting it would change nothing, on the call that is most common.
            return
        tmp = os.path.join(self.directory, ".baseline.json.tmp")
        with open(tmp, "w") as handle:
            handle.write(text)
        os.replace(tmp, self.path)
        self.loaded_text = text


def _lock(directory: str) -> int:
    """One sentinel at a time per session: tool calls can run in parallel."""
    os.makedirs(directory, exist_ok=True)
    fd = os.open(os.path.join(directory, "lock"), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    return fd


def _unlock(fd: int) -> None:
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


def _journal_state(root: str, blobs: BlobStore) -> dict[str, Any] | None:
    journal = os.path.join(root, "journal.jsonl")
    if not os.path.isfile(journal):
        return None
    with open(journal, "rb") as handle:
        data = handle.read()
    digest = blobs.keep(journal)
    return {"size": len(data), "digest": digest, "blob": digest}


def _baseline(config: ConfigView, state: _State) -> dict[str, Any]:
    revert_roots = sorted(set(_roots(config, "revert") + _frozen_experiment_paths(config)))
    revert_exceptions = sorted(set(_exceptions(config, "revert")))
    entries = record(revert_roots, state.blobs, revert_exceptions)
    return {
        "revert_roots": revert_roots,
        "revert_exceptions": revert_exceptions,
        "revert": {p: _entry_json(e) for p, e in entries.items()},
        "journal": {r: _journal_state(r, state.blobs) for r in _roots(config, "journal")},
        "halt": _halt_record(config),
        "nodes": {r: _nodes_record(r, heads(r)) for r in _roots(config, "journal")},
        "log": {p: list(sig) for p, sig in take_signatures(_roots(config, "log")).items()},
        "halted": None,
    }


def _depth(path: str) -> int:
    return path.count("/")


def _restore_entry(path: str, entry: Entry, state: _State) -> None:
    kind = entry.signature[0]
    mode = entry.signature[1]
    if kind == "dir":
        os.makedirs(path, exist_ok=True)
        os.chmod(path, mode)
    elif kind == "file" and entry.digest is not None:
        state.blobs.restore(path, entry.digest, mode)
    elif kind == "link" and entry.link is not None:
        os.symlink(entry.link, path)


def _revert(base: dict[str, Any], state: _State) -> tuple[list[str], list[str]]:
    """Put the revert roots back. Returns (paths put back, paths that could not be)."""
    exclude = base.get("revert_exceptions", [])
    current = take_signatures(base["revert_roots"], exclude)
    if current == {p: tuple(raw[0]) for p, raw in base["revert"].items()}:
        # Every path is where it was, with the signature it had: nothing moved,
        # so there is nothing to put back and nothing to verify. That is every
        # call but the rare one where something changed, and it spares the two
        # further walks the path below takes.
        return [], []
    recorded = {p: _entry(raw) for p, raw in base["revert"].items()}
    touched: list[str] = []
    moved: list[str] = []
    for path in sorted(set(current) - set(recorded), key=_depth):
        if any(path.startswith(m.rstrip("/") + "/") for m in moved):
            continue
        quarantine(path, state.quarantine)
        moved.append(path)
        touched.append(path)
    for path in sorted(set(current) & set(recorded), key=_depth):
        if any(path.startswith(m.rstrip("/") + "/") for m in moved):
            continue
        was, now = recorded[path], current[path]
        if was.signature == now:
            continue
        if was.signature[0] != now[0]:
            quarantine(path, state.quarantine)
            moved.append(path)
            _restore_entry(path, was, state)
            touched.append(path)
        elif now[0] == "file":
            if now[1] != was.signature[1] or file_digest(path) != was.digest:
                _restore_entry(path, was, state)
                touched.append(path)
        elif now[0] == "dir" and now[1] != was.signature[1]:
            os.chmod(path, was.signature[1])
            touched.append(path)
        elif now[0] == "link" and os.readlink(path) != was.link:
            quarantine(path, state.quarantine)
            _restore_entry(path, was, state)
            touched.append(path)
    for path in sorted(
        set(recorded) - set(take_signatures(base["revert_roots"], exclude)), key=_depth
    ):
        _restore_entry(path, recorded[path], state)
        touched.append(path)
    # Verify, and take the restored files' new signatures as the baseline: a
    # replaced file has a new inode, with the content it had before.
    after = take_signatures(base["revert_roots"], exclude)
    failed = sorted(set(after) ^ set(recorded))
    for path, entry in recorded.items():
        if (
            path in after
            and entry.signature[0] == "file"
            and after[path] != entry.signature
            and file_digest(path) != entry.digest
        ):
            failed.append(path)
        if path in after:
            base["revert"][path] = [list(after[path]), entry.digest, entry.link]
    return sorted(set(touched)), failed


def _check_journals(
    base: dict[str, Any], state: _State
) -> tuple[list[str], list[tuple[str, int, int]]]:
    """Journals put back, and appends seen: (journal, first byte, end), end exclusive."""
    restored = []
    appended: list[tuple[str, int, int]] = []
    for root, was in base["journal"].items():
        journal = os.path.join(root, "journal.jsonl")
        if was is None:
            base["journal"][root] = _journal_state(root, state.blobs)
            continue
        try:
            with open(journal, "rb") as handle:
                data = handle.read()
        except FileNotFoundError:
            data = b""
        head = data[: was["size"]]
        if len(data) >= was["size"] and hashlib.sha256(head).hexdigest() == was["digest"]:
            if len(data) > was["size"]:
                # Appended to: the orchestrator does that, and so could anything
                # that got past the first layer. The two cannot be told apart
                # here, so the append is recorded with the call it was seen after
                # and its byte range, for the orchestrator to match against its
                # own writes; its stale-handle guard is the second layer.
                appended.append((journal, was["size"], len(data)))
                base["journal"][root] = _journal_state(root, state.blobs)
            continue
        state.blobs.restore(journal, was["blob"], 0o644)
        restored.append(journal)
    return restored, appended


def _code_record(path: str, *, hashed: bool = True) -> list[Any]:
    return [list(signature(os.lstat(path))), file_digest(path) if hashed else None]


def _halt_record(config: ConfigView) -> dict[str, list[Any]]:
    """The halt class's record: loaded code and the rare paths' code, taken at the first hook.

    The code this process loaded is hashed, as before, so a touch that changes no
    byte is not a change. Two kinds of file are recorded by signature alone: the
    interpreter binary (31 MB on the server) and the rare paths' code (about 250
    files, 13 MB), which together cost the first hook more than every check it
    runs. Nothing touches either legitimately, and the signature caught every
    attack measured against it, so with no digest to excuse a touch, any move of
    their signature is a change.
    """
    loaded = set(_loaded_code(config))
    unhashed = {os.path.realpath(sys.executable)}
    record = {p: _code_record(p, hashed=p not in unhashed) for p in loaded}
    for path in _loaded_code(config, _lazy_code()):
        if path not in record:
            record[path] = _code_record(path, hashed=False)
    return record


def _check_halt(base: dict[str, Any], config: ConfigView) -> list[str]:
    """Loaded code whose bytes changed. Hashed only where the signature moved."""
    changed = []
    for path, (sig, digest) in base["halt"].items():
        try:
            if list(signature(os.lstat(path))) == sig:
                continue
            if digest is None or file_digest(path) != digest:
                changed.append(path)
        except OSError:
            changed.append(path)
    for path in _loaded_code(config):
        if path not in base["halt"]:
            base["halt"][path] = _code_record(path)
    return changed


def _expected_body(head: Head) -> bytes:
    # The store's own function for what a node file holds, so the comparison is
    # against what writing actually produces. It is a pure function; calling it
    # opens nothing. Imported here, because importing the state package loads
    # the validation library, and this runs only when the store has changed.
    from physgate.state import node_file_body

    return node_file_body(*head).encode()


def _node_files(root: str) -> dict[str, str]:
    """Node id to path, for every name the store would serve a node from."""
    nodes = os.path.join(root, "nodes")
    if not os.path.isdir(nodes):
        return {}
    return {
        name[: -len(".json")]: os.path.join(nodes, name)
        for name in sorted(os.listdir(nodes))
        if name.endswith(".json")
    }


def _nodes_record(root: str, found: dict[str, Head]) -> dict[str, Any]:
    watched = [os.path.join(root, "journal.jsonl"), os.path.join(root, "nodes")]
    return {
        "sigs": {p: list(sig) for p, sig in take_signatures(watched).items()},
        "revs": {node_id: head[0] for node_id, head in found.items()},
    }


def _read_as_the_store_does(path: str) -> bytes | None:
    # A link in a node file's place is not read through: it is a mismatch, and the
    # rebuild replaces it.
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    try:
        with os.fdopen(fd, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def _node_path(root: str, node_id: str) -> str | None:
    """The file the store serves ``node_id`` from under ``root``, or ``None``.

    A name read from the journal becomes a path only through the store's own name
    rule, so a separator, a parent reference, an absolute name, a NUL or a final
    newline never reaches the filesystem. The result must also stay directly in
    the node directory once every link above it is resolved.
    """
    from pathlib import Path

    from physgate.state import DesignStateError, node_file_path

    nodes = Path(root, "nodes")
    try:
        path = node_file_path(nodes, node_id)
    except DesignStateError:
        return None
    real_nodes = Path(os.path.realpath(nodes))
    real_parent = Path(os.path.realpath(path.parent))
    if (
        path.parent != nodes
        or real_parent != real_nodes
        or not real_parent.is_relative_to(real_nodes)
    ):
        return None
    return str(path)


#: One node finding: the path named on record, the store root, and the node to
#: rebuild, or ``None`` when there is nothing the sentinel may rebuild.
NodeFinding = tuple[str, str, str | None]


def _check_nodes(base: dict[str, Any]) -> list[NodeFinding]:
    """Node files that do not hold what the journal says, read-only; nothing is written.

    A node the journal names whose file is missing is a finding too: the store
    would serve nothing for it until its next open, and a deleted file is as far
    from the journal as a rewritten one. A node directory replaced by a link is a
    finding, and so is a journal line naming a node no store could serve; neither
    is turned into a path to read or write.

    The orchestrator writes a node in two steps, the journal line and then the
    file, and a check can land between them. So the journal is read again
    before deciding, and a file is not a finding if it matches the journal as
    it now stands, or if its node has a newer journal line than the last check
    saw: that is the orchestrator's write in progress, a new node's file not yet
    written included. A file whose node's newest line was already seen, and
    which still does not match or is still missing, is a finding.
    """
    findings: list[NodeFinding] = []
    for root, was in base.get("nodes", {}).items():
        journal = os.path.join(root, "journal.jsonl")
        nodes = os.path.join(root, "nodes")
        watched = [journal, nodes]
        now = {p: list(sig) for p, sig in take_signatures(watched).items()}
        if now == was["sigs"]:
            continue
        found = heads(root)
        if os.path.islink(nodes):
            findings.append((nodes, root, None))
            base["nodes"][root] = _nodes_record(root, found)
            continue
        files = _node_files(root)
        suspects = [
            (node_id, path)
            for node_id, path in files.items()
            if node_id not in found
            or _read_as_the_store_does(path) != _expected_body(found[node_id])
        ]
        unservable = False
        for node_id in sorted(set(found) - set(files)):
            path = _node_path(root, node_id)
            if path is None:
                unservable = True
            else:
                suspects.append((node_id, path))
        if unservable:
            # The orchestrator never writes such a line, so it is no write in
            # progress: the journal itself is named, and nothing is rebuilt for it.
            findings.append((journal, root, None))
        if suspects:
            found = heads(root)
            for node_id, path in suspects:
                head = found.get(node_id)
                if head is not None and (
                    _read_as_the_store_does(path) == _expected_body(head)
                    or head[0] > was["revs"].get(node_id, 0)
                ):
                    continue
                findings.append((path, root, node_id if head is not None else None))
        base["nodes"][root] = _nodes_record(root, found)
    return findings


#: How often a rebuild is retried when the orchestrator writes the same node meanwhile.
_REBUILD_ATTEMPTS = 3


def _restore_nodes(base: dict[str, Any], findings: list[NodeFinding]) -> list[str]:
    """Rebuild each mismatched node file from the journal. Returns the files rebuilt.

    The journal is the authority, so the file is written as the journal's newest
    line for its node says, with the store's own write: atomic, and following no
    link. A file the journal never named has nothing to be rebuilt from and is
    left for the store, whose next open refuses it or moves it aside. Nothing is
    written into a node directory that is a link, and the only directory ever
    made is the store's own node directory, by its fixed name.

    The orchestrator may write the same node meanwhile: its journal line, then
    its file. If its file lands before this one, this one would be older, so the
    journal is read again after the write, and a node whose newest line moved is
    written again from the newer line.
    """
    # Imported here: the state package loads the validation library, and this
    # runs only when a node file has changed.
    from pathlib import Path

    from physgate.state import DesignStateError
    from physgate.state import store as graph

    restored: list[str] = []
    roots: set[str] = set()
    for path, root, node_id in findings:
        roots.add(root)
        if node_id is None:
            continue
        nodes = os.path.join(root, "nodes")
        if not os.path.lexists(nodes):
            # The whole directory was removed: made again as the store makes it, so
            # each file can be rebuilt.
            try:
                os.mkdir(nodes)
            except OSError:
                continue
        if os.path.islink(nodes) or _node_path(root, node_id) != path:
            continue
        for _ in range(_REBUILD_ATTEMPTS):
            head = heads(root).get(node_id)
            if head is None:
                break
            try:
                graph.write_node_file(Path(nodes), node_id, *head)
            except (OSError, DesignStateError):
                break
            now = heads(root).get(node_id)
            if now is not None and now[0] == head[0]:
                restored.append(path)
                break
    for root in roots:
        # The rebuilt files are the record now, so the next check starts from them.
        base["nodes"][root] = _nodes_record(root, heads(root))
    return restored


def _check_logged(base: dict[str, Any], config: ConfigView) -> list[str]:
    roots = _roots(config, "log")
    now = {p: list(s) for p, s in take_signatures(roots).items()}
    changed = sorted(p for p in set(now) | set(base["log"]) if now.get(p) != base["log"].get(p))
    base["log"] = now
    return changed


def _event(
    config: ConfigView,
    hook_input: InputView,
    action: str,
    paths: list[str],
    extra: dict[str, Any] | None = None,
) -> None:
    append_log(
        config,
        (extra or {})
        | {
            "t": time.time(),
            "session": hook_input.session_id,
            "agent": hook_input.agent_id,
            "profile": config.profile,
            "role": config.role,
            "event": hook_input.hook_event_name,
            "tool": hook_input.tool_name,
            "tool_input": hook_input.tool_input,
            "hook": "sentinel",
            "decision": action,
            "paths": paths,
        },
    )


def check(hook_input: InputView, config: ConfigView) -> Decision:
    """Compare the protected paths with the session's record, and act on any change."""
    directory = os.path.join(session_dir(config, hook_input.session_id), "sentinel")
    fd = _lock(directory)
    try:
        state = _State(directory)
        base = state.load()
        if base is None:
            base = _baseline(config, state)
            files, problems = withheld.survey(_withheld_roots(config))
            base["withheld"] = {p: list(i) for p, i in files.items()}
            if problems:
                base["halted"] = LINKED.format(paths=", ".join(problems))
            state.save(base)
            if problems:
                _event(config, hook_input, "withheld", problems)
                return refuse(base["halted"])
            return ALLOW
        if base.get("halted"):
            return refuse(base["halted"])
        halted = _check_halt(base, config)
        if halted:
            base["halted"] = HALTED.format(paths=", ".join(halted))
            state.save(base)
            _event(config, hook_input, "halt", halted)
            return refuse(base["halted"])
        put_back, failed = _revert(base, state)
        journals_put_back, appended = _check_journals(base, state)
        put_back += journals_put_back
        node_findings = _check_nodes(base)
        mismatched = [path for path, _root, _node in node_findings]
        restored = _restore_nodes(base, node_findings) if node_findings else []
        logged = _check_logged(base, config)
        # The withheld-file tripwire runs after everything above has been put back, so
        # finding something there never costs a put-back; it adds a halt of its own.
        unsure: list[str] = []
        if hook_input.hook_event_name in WITHHELD_EVENTS:
            now, unsure = withheld.survey(_withheld_roots(config))
            recorded = {p: (i[0], i[1]) for p, i in base.get("withheld", {}).items()}
            unsure += withheld.changed(recorded, now)
        if failed:
            base["halted"] = UNRESTORABLE.format(paths=", ".join(failed))
        elif mismatched:
            base["halted"] = NODE_MISMATCH.format(paths=", ".join(mismatched))
        elif unsure:
            base["halted"] = LINKED.format(paths=", ".join(unsure))
        state.save(base)
    finally:
        _unlock(fd)
    for journal, first, end in appended:
        _event(config, hook_input, "journal append", [journal], {"bytes": [first, end]})
    if logged:
        _event(config, hook_input, "changed", logged)
    if unsure:
        _event(config, hook_input, "withheld", unsure)
    # Every action taken is on record before any refusal is chosen: a halt for one
    # fault may not hide another fault's put-back from the log.
    if put_back:
        _event(config, hook_input, "put back", put_back)
    if failed:
        _event(config, hook_input, "unrestorable", failed)
        return refuse(UNRESTORABLE.format(paths=", ".join(failed)))
    if mismatched:
        _event(config, hook_input, "node mismatch", mismatched, {"restored": restored})
        return refuse(NODE_MISMATCH.format(paths=", ".join(mismatched)))
    if unsure:
        return refuse(LINKED.format(paths=", ".join(unsure)))
    if put_back:
        return refuse(PUT_BACK.format(paths=", ".join(put_back)))
    return ALLOW


HOOK = HookSpec(
    "sentinel",
    {
        "SessionStart": check,
        "PreToolUse": check,
        "PostToolUse": check,
        "PostToolUseFailure": check,
        "Stop": check,
        "SessionEnd": check,
    },
)
