# The design's format

A design is a set of nodes. Each node is one JSON object with exactly these
fields (ARCH-010, in `architecture.md`), and no others:

| field | what it holds |
|---|---|
| `id` | a short dotted identifier in lower case, `<domain or area>.<name>`, e.g. `electrical.motor_left`. Letters, digits and `_` only, a dot between parts, at least one dot |
| `kind` | `component` (one part), `module` (a group of parts that belong together), `requirement`, or `interface` (a boundary between two domains, fixed once written) |
| `domain` | `mechanical`, `electrical`, `control`, `firmware`, or `cross` (for an interface) |
| `owner_role` | the role that writes the node: `mechanical`, `electrical`, `control` or `firmware`, the same as its domain; `integration` for a `cross` node |
| `quantities` | an object from quantity name to `{"value": <number>, "unit": "<unit>", "source": "<where the number comes from>", "written_by": "<the owner role>"}`. A number is a JSON number, never a string. Every quantity has all four fields |
| `requirements` | a list of requirement ids, or `[]` |
| `constrains` | the ids of the nodes that must be revisited when this node changes: a part names the module it belongs to, a consumer names the supply it draws from, a load names the structure that carries it. `[]` if none |
| `model` | `null`, or a path to an executable model |
| `geometry_hash` | no node of this design has geometry, so every node carries exactly this string, copied as it stands: `"sha256:0000000000000000000000000000000000000000000000000000000000000000"` |
| `updated` | copy `"2026-09-28T10:00:00Z"` into every node |
| `no_change_justified` | optional. An object from the id of a node that constrains this one to the reason, in words, that this node's numbers need not change although that node changed. Omit it, or `{}`, when there is none |

**Units** are written as plain text a units library reads: `A`, `mA`, `V`,
`W`, `mW`, `J`, `W*h`, `kg`, `g`, `m`, `mm`, `N`, `N*m`, `Hz`, `rad/s`,
`degC`, `K`, `K/W`, `dimensionless`. Products with `*`, quotients with `/`,
powers with `**`. No Unicode symbols (`·`, `µ`, `Ω`, `°`): write `N*m`, `uA`,
`ohm`, `degC`.

**Sources.** Every quantity's `source` says where its number comes from, in
one of three forms, and a number that has none of them is not written:

- `"<URL>"`: the URL of the parts sheet row it was copied from, as that row
  gives it. The number is the row's, converted only between units;
- `"derived: <arithmetic>"`: computed from rows of the parts sheet, each cited
  by its id in brackets, e.g. `"derived: [R5.03] * [R5.06]"` (the pack's nominal voltage times its capacity). `+ - * / **` and
  brackets only. **Every operand is a cited row**; the only other number allowed
  is a whole-number power (`[R9.01] ** 2`). No constants and no other node's
  quantity. A count (six cells, two motors) is cited as its own row of unit
  `count`, like any other number; a count the sheet does not give is not used. The cited rows must each be one number with a unit on the
  sheet, and the arithmetic must give the dimension of the quantity's own unit;
  the files are refused otherwise. The arithmetic is done by hand: write the
  result to three significant figures;
- `"design: <reason>"`: a choice the design makes, allowed **only** on the
  quantities `vocabulary.md` marks as design choices (`sample_rate`,
  `loop_gain`). Never on anything else: the files are refused if it is.

A property of a bought part that no row of the parts sheet gives, and that
cannot be derived from rows it does give, is not written, and it is never
estimated. The design does without that quantity.

**Words.** The nodes read as an engineering design and nothing else. None of
these words appears anywhere in a node, in any spelling: inject, planted,
deliberate, mistake, corpus, corpora, answer, twin, physgate, physics gate,
reviewer, expected check, error class, unit error, magnitude error,
equilibrium error, propagation error, wrong, faulty, incorrect, bug.

## The files

A **base design**, `base.json`:

```json
{"label": "<one sentence: what the design is and that it is a stand-in>", "nodes": [<node>, ...]}
```

A **revision**, `clean/aNN.json` (`a01` to `a20`): one change a role might make
to the base, with everything that change requires of other nodes.

```json
{"id": "a07", "assigned_role": "<the role that makes the change>", "summary": "<one sentence>", "clean": {"nodes": [<node>, ...]}}
```

Each node in `clean.nodes` is the whole node as it reads after the revision.
A revision is written over the base: a node in it that the base has replaces
the base's, and a node the base does not have is added. A revision never
rewrites an `interface` node and never changes a node's `owner_role`.

**Every revision is complete.** If it changes a node, or adds one, then every
node that node's `constrains` names, before the change and after it, is also
in the revision with its numbers updated to follow; or, if that node's numbers
truly need not change, it is in the revision unchanged except for a
`no_change_justified` entry keyed by the changed node's id, giving the
physical reason. A node written with the same numbers and no reason counts as
unchanged.

An **injection**, `injections/aNN.json`: the same revision with one error in
it, written as **only what differs** from the revision. You do not copy the
revision: the files are put together from the revision and these two lists,
mechanically.

```json
{
 "id": "a07",
 "error_class": "unit | magnitude | equilibrium | propagation",
 "expected_check": "units | magnitude | equilibrium | power | conservation | thermal | propagation",
 "description": "<the error, in physics terms: which quantity, what it should be, what it is>",
 "edge": null,
 "replace": [<node>, ...],
 "drop": ["<node id>", ...]
}
```

- `replace`: each node of the revision you change, written whole as it reads
  with the error. Usually one node. Every node here is a node the revision has.
- `drop`: ids of nodes of the revision to leave out, for a propagation error
  whose target the change did not reach. `[]` otherwise.
- The revision's other nodes are kept exactly as they are.

For a `propagation` error, `edge` is `{"source": "<id>", "target": "<id>"}`:
the node that changed and the node, in another domain, that its change should
have reached but did not. Either drop the target, or replace it with the
base's node for it unchanged. `null` for the other classes.
