# `physgate.hooks` — the enforced surface, as Claude Code hooks

This package is where "enforce, do not request" (ARCH-003) becomes code. Before
an agent's tool call runs, these hooks refuse what no agent session may do; after
it, and before the next one, a sentinel checks that nothing protected moved and
puts back what did. The table they implement is ARCH-090's, and every row of it
has a test that refuses a blocked input and passes an allowed one.

The hooks are generated, never hand-edited: `physgate hooks install` writes a
session's settings file and configuration outside its worktree, and the
session is started with them.

## What it owns

| | |
|---|---|
| `settings.py`, `cli.py` | The generator: the session configuration, the settings file naming one command per event, and the spawn arguments |
| `config.py` | The pydantic schema of the session configuration and of Claude Code's event description. The generator validates with it |
| `lean.py`, `views.py` | The hot path's standard-library validator for the same two shapes, and the read-only interfaces every hook is typed against |
| `runtime.py`, `__main__.py`, `trampoline.sh` | The dispatcher, the entry point, and the shell wrapper that turns every outcome but a clean pass into a refusal |
| `registry.py` | Every hook module by name; the generator wires exactly these |
| `tools.py` | Each profile runs on a closed list of tools |
| `paths.py` | No file tool writes a protected path, and nothing reads the held-out tier |
| `shell_paths.py`, `shell.py` | No shell command names a protected path unless it only reads; no background jobs; no nested Claude Code. `shell.py` splits a command into the commands it would run |
| `git_ops.py` | No force push, no skipping the repository's hooks, no rebase, no hard reset beyond the session's own branch, no ref writes |
| `graph.py`, `journal_view.py` | A graph node reaches the store only as a proposal file, checked for owner and schema as it is written; the journal is read without ever opening a store |
| `reading.py` | No tool but Read until the required reading is done (ARCH-020) |
| `token_ceiling.py` | Every tool refused while the always-loaded set is over its ceiling (ARCH-023) |
| `sentinel.py`, `snapshot.py` | The second layer: every protected path compared at every hook, and put back when it moved |
| `state.py`, `reasons.py`, `exceptions.py` | The hook layer's own records, the shared refusal reasons, the domain exceptions |

## What it deliberately does not own

- **The gate.** It protects `src/physgate/gate/`, which may be empty.
- **What a role must read** and **how large the always-loaded set may be.** It
  enforces a list and a ceiling it is given; the ceiling has no default.
- **Applying proposals.** The orchestrator applies them at merge, from the
  subtask's commit, under the role it recorded at dispatch, all of a subtask's
  proposals or none. The store's guards run then as the second line.
- **Anything that needs a model, or the network.** A hook is deterministic and
  makes no network call; a test runs every generated command with every socket
  operation and every process start blocked.
- **The orchestrator's own session**, and anything outside a session: a process
  running as the same user outside the session is not something a hook can see.

## How a session is started

```
physgate hooks install --profile role --role electrical \
    --worktree <worktree> --own-branch <branch> --store-root <store> \
    --state-dir <state> --target <settings dir> --claude-config-dir <dir> \
    --ceiling <tokens> --reading <file> ... --always-loaded <file> ...
```

It prints the spawn arguments: `--setting-sources ""` and `--settings <file>`,
and a scratch `CLAUDE_CONFIG_DIR`. All of it is outside the worktree, and all of
it is protected. This is measured, not assumed: with any settings file inside
the worktree loaded, one write of `disableAllHooks` into it switched every hook
off for the rest of the session, and an `env` block written the same way
changed what every hook saw. With no worktree settings loaded and the hooks in
a file passed by flag, neither write changed anything, and the flag file itself
is not re-read when edited.

Every hook command carries the path of the session configuration and its
sha256, and a hook whose configuration no longer matches refuses every call.

`--api-key-helper <script>` names a script that prints the API key in the
settings file (`apiKeyHelper`), so the key is not in the session's environment,
where any tool call could print it. The script must sit in the session's own
files or its state directory, both protected roots; anywhere else is refused.
A session running as the same user can still read and run it, which is a known
limit, not a closure.

Three profiles: `role` (a domain agent writing one module), `reviewer` (reads,
writes nothing) and `orchestrator` (a harness session). None of the three
writes the gate.

## Fail closed

Claude Code runs a tool on every hook outcome except exit status 2 or an
explicit JSON refusal: an exit of 1, an uncaught exception, a killed process, a
missing interpreter and a hook that outlives its timeout all let the tool run
(measured on the pinned version). So every hook command is wrapped by
`trampoline.sh`, which passes a clean 0 and a 2 through and turns everything
else into a 2, with a watchdog at least ten seconds shorter than Claude Code's
own hook timeout. Every refusal is a JSON refusal and exit 2 at once, so the
agent is told the reason and nothing else. The hook code runs from an
installation outside the worktree, with the interpreter in isolated mode.

## Two layers against the shell

A Write hook alone proves nothing: `cat > gate/check.py <<EOF` reaches the gate
without calling the Write tool. So the shell is covered twice.

1. **Before the call**, `shell_paths.py` refuses a command that names a
   protected path anywhere in it unless the command only reads, and output
   redirected into one whatever the command. It finds paths in globs, `~` and
   `$VAR`, after a `cd`, inside `dd of=…` and `python -c "open('…')"`. A reader
   carrying a flag that writes (`git diff --output`, `find -fprint`, `tree -o`,
   `less -o`, `rg --pre`, …) is a writer. It is deliberately coarse, because a
   shell cannot be modelled completely.
2. **After the call, and before the next one**, the sentinel compares every
   protected path's `lstat` signature (type, mode, device, inode, size,
   modification and change time, link count) with the record it took at the
   session's first hook, and acts by the root's watch class:
   - `revert`: put back from the bytes kept at the start, by replacing the
     file; anything new is moved into a quarantine, never deleted;
   - `journal` (the graph store): the journal's existing bytes must be
     unchanged; appends are the orchestrator's, and the store's own staleness
     guard refuses one that was not; node files must hold what the journal
     says, or the session halts;
   - `halt` (the hook code): every later call is refused;
   - `log`: recorded, because other processes write it legitimately;
   - `none`: the hooks' own state and the session's Claude Code directory,
     which the hooks and Claude Code write themselves.

What the first layer cannot see — a path built from a variable, a
substitution, a string assembled in a script, an archive, a patch — is the
second layer's, and the tests assert those forms as allowed by the first layer
so that the boundary is on record. The bypass suite runs thirty-four attempts
through the real Claude Code binary, each judged by the bytes of the protected
trees and by which layer logged the refusal; its tolerance is zero.

## Matching commands, not text

The git hook looks only at a command whose command position is git, including
git reached through a path, `env`, `command`, `exec`, a substitution, a
subshell or the string given to `sh -c`. A heredoc body, a quoted argument to
another program and the content of a Write are never matched, so a document or
a test that names a forbidden flag can be written.

**A commit message that names a protected path** is the one place this costs
something: `git commit -m '… src/physgate/gate/check.py …'` names the path in
the command, and the shell layer refuses it. Write the message to a file and
commit with `git commit -F <file>`: the file's content is not read as part of
the command. The refusal says so itself.

## The graph: proposals, never the store

No agent tool writes any file in the store's directory: a direct write to a
node file is served until the next open, and a line appended to the journal is
replayed as if the store had written it. An agent proposes a node instead, by
writing the whole node to `.physgate/proposals/<node id>.json` in its worktree
with the Write or Edit tool. The hook checks it as it is written, in the store's
order and with the store's reasons: a legal identifier matching the file name;
ownership (a new node names the session's role, an existing node is already
owned by it and keeps that owner); no write to an interface node; every
quantity a value with a unit, a source and a writer; the whole node valid. The
current owner is read from the journal, opened read-only; a hook never opens a
store, because opening one runs recovery, which writes.

## The hot path

Every agent tool call starts a hook process, and a hook has 200 ms. The
validation library and the state package's models cost more than that to
import before any check ran, so the hot path uses the standard library only.
`lean.py` validates the configuration and the event with the same rules as the
pydantic models in `config.py`, which stay the schema. A test holds the two
together: on the configuration's own cases, on thousands of generated variants
and on thousands of documents mutated character by character, both must accept
or both must refuse, and where both accept every field must be the same. Two
validators that drift apart is the defect the equivalence test exists to catch;
a change to either that makes them disagree fails it.

The validation library and the state package are imported only on the two
paths that need them: a Write or Edit into the proposals directory, and the
sentinel's node check after the store changed. A test reads the interpreter's
own import log from every generated command and fails if any other call loads
them.

To measure the hooks on a realistic role session, beside a same-day control:

```
uv run python tests/integration/hooks/measure_latency.py latency.json
```

## Known limits

- **The same user.** Anything a hook can write, a command run as the same user
  can write too: the hooks' state directory, the session's Claude Code
  directory, and the interpreter's own installation where that user can write
  it. On Linux the installer hard-links the environment from its cache, which
  gives each installed file a second, unprotected name. The closure is to
  install the harness where the session's user cannot write.
- **The halt is detection only.** Code that tampers with the hooks' own code
  runs before any check inside it.
- **Reads of the held-out tier have one layer.** A read moves no signature, so
  the sentinel cannot see one.
- **The first hook of a session** takes the sentinel's record: it keeps the
  bytes of every protected file in one pack, and finds the files of the code
  the rare paths load, without importing them, so a change to them is seen from
  the start. It costs about twice an ordinary hook, and more where the hook
  state directory sits on a network filesystem; keep it on a local disk.
