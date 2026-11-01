# Brief: ten errors against the domains' own standards

You are writing errors for an experiment in a thesis on checking engineering designs made by AI
agents. Another session wrote a design (`base.json`) and ten valid revisions of it
(`clean/s01.json` to `clean/s10.json`). **You make each revision wrong in exactly one place, so that
it breaks a rule its domain's standards state.**

Everything you need is in this directory. Read these first, in this order:

1. `architecture.md`: how a design is written down, and the checks the architecture names.
2. `format.md` and `rules.md`: the node format, the files, and the rules the revisions keep.
3. `vocabulary.md` and `parts_sheet.md`: the quantity names and the parts' data.
4. `standards/control.md`, `standards/electrical.md`, `standards/firmware.md`,
   `standards/mechanical.md`: each domain's standards.
5. `base.json` and the ten files in `clean/`.

You can read and write files in this directory only. There is no shell and no web. Do not change
`base.json` or anything in `clean/`.

## The errors

Each is a number that breaks a rule its domain's standards file states: a rating exceeded, a
derating not applied, a margin below the standard's minimum, a timing or rate budget overrun. It
sits in a node of the revision's `assigned_role`'s domain. The design and the parts sheet give
everything a careful reader needs to see it. It is not a unit slip, a scale slip with no standard
behind it, a structure that no longer balances, or a node a change did not reach. It is one a
competent engineer, or a capable model, could plausibly make and not notice. Spread them over the
four domains, at least two in each.

## What to write

`injections/s01.json` to `injections/s10.json`, in the form `format.md` gives for an injection,
with `error_class` `"standard"`, `edge` `null`, `expected_check` the check in the architecture's
table nearest to it, and a `description` that names the standards file and the rule, the quantity,
what it should be, what it is, and why. Nothing in any node may say that it is wrong or that
anything was changed on purpose (`format.md`, "Words").

## How to work

Read everything first. Write `plan.md`: for each revision, the rule it will break and where. Then
write the ten injection files. Then stop.
