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
  would replay an agent's line as genuine.
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
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from physgate.hooks.config import SessionConfig
from physgate.hooks.runtime import ALLOW, Decision, HookInput, HookSpec, refuse
from physgate.hooks.snapshot import BlobStore, Entry, file_digest, quarantine, record, signature
from physgate.hooks.snapshot import signatures as take_signatures
from physgate.hooks.state import append_log, session_dir
from physgate.state.store import Store

PUT_BACK = (
    "Protected paths changed during this session and were put back: {paths}. Protected "
    "paths are not written by agent sessions; anything new was moved aside, not deleted."
)
HALTED = (
    "The code the hooks run from changed during this session ({paths}), so nothing the hooks "
    "decide can be trusted, and every call is refused."
)
NODE_MISMATCH = (
    "A graph node file does not hold what the journal says it holds ({paths}). The store "
    "serves node files as they are, so every call is refused until the orchestrator reopens "
    "the store, which rebuilds the file from the journal."
)
UNRESTORABLE = (
    "A protected path changed and could not be put back ({paths}); every call is refused."
)


def _roots(config: SessionConfig, watch: str) -> list[str]:
    return [root.path for root in config.protected_roots if root.watch == watch]


def _frozen_experiment_paths(config: SessionConfig) -> list[str]:
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


def _loaded_code(config: SessionConfig) -> list[str]:
    """The files of the code this hook process has loaded, under the installation roots."""
    halt_roots = [os.path.realpath(r) for r in _roots(config, "halt")]
    files = {os.path.realpath(sys.executable)}
    for module in list(sys.modules.values()):
        path = getattr(module, "__file__", None)
        if path:
            files.add(os.path.realpath(path))
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
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.blobs = BlobStore(directory / "blobs")
        self.quarantine = directory / "quarantine"
        self.path = directory / "baseline.json"

    def load(self) -> dict[str, Any] | None:
        if not self.path.exists():
            return None
        loaded: dict[str, Any] = json.loads(self.path.read_text())
        return loaded

    def save(self, base: dict[str, Any]) -> None:
        tmp = self.directory / ".baseline.json.tmp"
        tmp.write_text(json.dumps(base, sort_keys=True))
        os.replace(tmp, self.path)


@contextmanager
def _locked(directory: Path) -> Iterator[None]:
    """One sentinel at a time per session: tool calls can run in parallel."""
    directory.mkdir(parents=True, exist_ok=True)
    fd = os.open(directory / "lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _journal_state(root: str, blobs: BlobStore) -> dict[str, Any] | None:
    journal = os.path.join(root, "journal.jsonl")
    if not os.path.isfile(journal):
        return None
    data = Path(journal).read_bytes()
    digest = blobs.keep(journal)
    return {"size": len(data), "digest": digest, "blob": digest}


def _baseline(config: SessionConfig, state: _State) -> dict[str, Any]:
    revert_roots = sorted(set(_roots(config, "revert") + _frozen_experiment_paths(config)))
    entries = record(revert_roots, state.blobs)
    return {
        "revert_roots": revert_roots,
        "revert": {p: _entry_json(e) for p, e in entries.items()},
        "journal": {r: _journal_state(r, state.blobs) for r in _roots(config, "journal")},
        "halt": {p: _code_record(p) for p in _loaded_code(config)},
        "nodes": {r: _nodes_record(r, _journal_heads(r)) for r in _roots(config, "journal")},
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
    recorded = {p: _entry(raw) for p, raw in base["revert"].items()}
    current = take_signatures(base["revert_roots"])
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
    for path in sorted(set(recorded) - set(take_signatures(base["revert_roots"])), key=_depth):
        _restore_entry(path, recorded[path], state)
        touched.append(path)
    # Verify, and take the restored files' new signatures as the baseline: a
    # replaced file has a new inode, with the content it had before.
    after = take_signatures(base["revert_roots"])
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


def _check_journals(base: dict[str, Any], state: _State) -> list[str]:
    restored = []
    for root, was in base["journal"].items():
        journal = os.path.join(root, "journal.jsonl")
        if was is None:
            base["journal"][root] = _journal_state(root, state.blobs)
            continue
        try:
            data = Path(journal).read_bytes()
        except FileNotFoundError:
            data = b""
        head = data[: was["size"]]
        if len(data) >= was["size"] and hashlib.sha256(head).hexdigest() == was["digest"]:
            if len(data) > was["size"]:
                # Appended to: the orchestrator does that. The store's own guard
                # refuses on its next call if the append was not its own.
                base["journal"][root] = _journal_state(root, state.blobs)
            continue
        state.blobs.restore(journal, was["blob"], 0o644)
        restored.append(journal)
    return restored


def _code_record(path: str) -> list[Any]:
    return [list(signature(os.lstat(path))), file_digest(path)]


def _check_halt(base: dict[str, Any], config: SessionConfig) -> list[str]:
    """Loaded code whose bytes changed. Hashed only where the signature moved."""
    changed = []
    for path, (sig, digest) in base["halt"].items():
        try:
            if list(signature(os.lstat(path))) == sig:
                continue
            if file_digest(path) != digest:
                changed.append(path)
        except OSError:
            changed.append(path)
    for path in _loaded_code(config):
        if path not in base["halt"]:
            base["halt"][path] = _code_record(path)
    return changed


def _journal_heads(root: str) -> dict[str, tuple[int, int, dict[str, Any]]]:
    """The newest (revision, version, payload) the journal records for each node.

    Read-only: the journal is opened for reading, and no store is constructed,
    because constructing one runs recovery, which rewrites node files. A final
    line without its terminator is a write still in progress and is not read. A
    line that is not a record is skipped: a journal holding one is refused by
    the store itself, which then serves nothing.
    """
    try:
        fd = os.open(os.path.join(root, "journal.jsonl"), os.O_RDONLY)
    except FileNotFoundError:
        return {}
    try:
        chunks = []
        while chunk := os.read(fd, 1 << 20):
            chunks.append(chunk)
    finally:
        os.close(fd)
    heads: dict[str, tuple[int, int, dict[str, Any]]] = {}
    for line in b"".join(chunks).split(b"\n")[:-1]:
        try:
            record_ = json.loads(line)
            node_id, rev = record_["node_id"], int(record_["rev"])
            version, payload = int(record_["version"]), record_["payload"]
        except (ValueError, KeyError, TypeError):
            continue
        if (
            isinstance(node_id, str)
            and isinstance(payload, dict)
            and (node_id not in heads or rev > heads[node_id][0])
        ):
            heads[node_id] = (rev, version, payload)
    return heads


def _expected_body(head: tuple[int, int, dict[str, Any]]) -> bytes:
    # The store's own function for what a node file holds, so the comparison is
    # against what writing actually produces. It is a pure function; calling it
    # opens nothing.
    return Store._node_body(*head).encode()


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


def _nodes_record(root: str, heads: dict[str, tuple[int, int, dict[str, Any]]]) -> dict[str, Any]:
    watched = [os.path.join(root, "journal.jsonl"), os.path.join(root, "nodes")]
    return {
        "sigs": {p: list(sig) for p, sig in take_signatures(watched).items()},
        "revs": {node_id: head[0] for node_id, head in heads.items()},
    }


def _read_as_the_store_does(path: str) -> bytes | None:
    try:
        return Path(path).read_bytes()
    except OSError:
        return None


def _check_nodes(base: dict[str, Any]) -> list[str]:
    """Node files that do not hold what the journal says, read-only; nothing is written.

    The orchestrator writes a node in two steps, the journal line and then the
    file, and a check can land between them. So the journal is read again
    before deciding, and a file is not a finding if it matches the journal as
    it now stands, or if its node has a newer journal line than the last check
    saw: that is the orchestrator's write in progress. A file whose node's
    newest line was already seen, and which still does not match, is a finding.
    """
    findings: list[str] = []
    for root, was in base.get("nodes", {}).items():
        watched = [os.path.join(root, "journal.jsonl"), os.path.join(root, "nodes")]
        now = {p: list(sig) for p, sig in take_signatures(watched).items()}
        if now == was["sigs"]:
            continue
        heads = _journal_heads(root)
        suspects = [
            (node_id, path)
            for node_id, path in _node_files(root).items()
            if node_id not in heads
            or _read_as_the_store_does(path) != _expected_body(heads[node_id])
        ]
        if suspects:
            heads = _journal_heads(root)
            for node_id, path in suspects:
                head = heads.get(node_id)
                if head is not None and (
                    _read_as_the_store_does(path) == _expected_body(head)
                    or head[0] > was["revs"].get(node_id, 0)
                ):
                    continue
                findings.append(path)
        base["nodes"][root] = _nodes_record(root, heads)
    return findings


def _check_logged(base: dict[str, Any], config: SessionConfig) -> list[str]:
    roots = _roots(config, "log")
    now = {p: list(s) for p, s in take_signatures(roots).items()}
    changed = sorted(p for p in set(now) | set(base["log"]) if now.get(p) != base["log"].get(p))
    base["log"] = now
    return changed


def _event(config: SessionConfig, hook_input: HookInput, action: str, paths: list[str]) -> None:
    append_log(
        config,
        {
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


def check(hook_input: HookInput, config: SessionConfig) -> Decision:
    """Compare the protected paths with the session's record, and act on any change."""
    directory = session_dir(config, hook_input.session_id) / "sentinel"
    with _locked(directory):
        state = _State(directory)
        base = state.load()
        if base is None:
            state.save(_baseline(config, state))
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
        put_back += _check_journals(base, state)
        mismatched = _check_nodes(base)
        logged = _check_logged(base, config)
        if failed:
            base["halted"] = UNRESTORABLE.format(paths=", ".join(failed))
        elif mismatched:
            base["halted"] = NODE_MISMATCH.format(paths=", ".join(mismatched))
        state.save(base)
    if logged:
        _event(config, hook_input, "changed", logged)
    if failed:
        _event(config, hook_input, "unrestorable", failed)
        return refuse(UNRESTORABLE.format(paths=", ".join(failed)))
    if mismatched:
        _event(config, hook_input, "node mismatch", mismatched)
        return refuse(NODE_MISMATCH.format(paths=", ".join(mismatched)))
    if put_back:
        _event(config, hook_input, "put back", put_back)
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
