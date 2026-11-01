# Brief: the base design and twenty revisions

You are writing the base for an experiment in a thesis on checking engineering
designs made by AI agents. The experiment is risk row 1 (`risk_row_1.md`):
known errors are injected into otherwise valid revisions of a design and
run past reviewers. This set is a smaller one of the same kind: twenty revisions. **You write the valid part.** A different session, later,
injects one error into each of your revisions. You inject nothing.

Everything you need is in this directory. Read these first, in this order:

1. `architecture.md`: how a design is written down (ARCH-010), the checks the
   architecture names (ARCH-080), and what "a change reaches the nodes it
   constrains" means (ARCH-082).
2. `risk_row_1.md`: the experiment your work is for.
3. `format.md`: the node format, the source rules, and the files you write.
   `rules.md`: rules this set adds to the format. Where they say more than
   `format.md`, they hold.
4. `vocabulary.md`: the quantity names a design uses where one fits.
5. `parts_sheet.md`: the robot's parts with their datasheet numbers, each with
   its URL and date. **It is your only source of part data.**

You can read and write files in this directory only. There is no shell and no
web.

## What to write

**1. `base.json`: a stand-in design of the self-balancing robot on the parts
sheet** (the Pololu Balboa 32U4 kit as the sheet lists it). Its `label` says it
is a stand-in built from that parts sheet, not a reference design.

- About 15 to 30 nodes, in all four domains: the mechanical structure that
  carries the parts (with the masses, positions and forces on it), the
  electrical parts and the supply they draw from, the control loop, and the
  firmware that runs it. Group parts into modules where they belong together.
- Every edge a real engineer would follow: a motor constrains the supply it
  draws from and the structure that carries it; a sensor constrains the loop
  that reads it; the loop constrains the firmware that runs it; and so on.
  Aim for many edges between different domains: at least ten distinct pairs of
  nodes in different domains joined by an edge.
- The design is **physically consistent**, as a careful engineer would make it:
  budgets add up, a supply covers what draws from it, a structure carries its
  loads, and every number has its source as `format.md` says.
- A number the sheet does not give, and that cannot be derived from numbers it
  does give, is left out: the design does without that quantity. Never
  estimate one.

**2. `clean/a01.json` to `clean/a20.json`: twenty revisions of the base.** Each
is one change a role might make to the design, with everything that change
requires of other nodes (`format.md`, "Every revision is complete"):

- swapping a part for another the sheet lists (a motor of another gear ratio,
  another battery arrangement, …), or a design choice changed (a rate, a gain,
  a limit), with every dependent number re-derived;
- spread across all four domains and all kinds of node, so that across the
  twenty there are many different places an error could sit: units, magnitudes,
  the statics of the structure, and changes that must reach another domain;
- **at least five of them change a node that has an edge into another domain,
  on at least five different such edges**, with the target node updated in the
  same revision;
- each with an `assigned_role`: the role whose node carries the change;
- each with a one-sentence `summary` of the change, in engineering terms.

A revision is valid on its own: another session will make each wrong in exactly
one place, so each must be right everywhere before that.

## How to work

Write `base.json` first and read it back once, whole. Then the revisions, one
file each. When all twenty exist, write `done.md` with one line per revision:
its id and its summary. Then stop.
