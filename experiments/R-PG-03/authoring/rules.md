# Rules for this set

Read these after `format.md`. Where they say more than `format.md`, they hold. Some are checked
by a script before the set is used; every one is part of what the set is judged against.

## The parts sheet

1. Write only what a row says, with its qualification. A row whose value is a range, a list or a
   text, or that carries a note, means what its label and note say: a peak is not a continuous
   rating, and a value stated under a condition holds only under it. Where a note gives one setting
   under two labels (a figure in one table, a rounded label for the same setting in another), use
   the row's number and never the other label's.
2. A limit or a margin is never taken from an absolute-maximum row. An absolute maximum is where
   damage begins, not where a design works. If the working range is given only as a range, which a
   `derived:` source cannot cite, the margin is not written.

## What a revision may change

3. A revision never removes a quantity the base has, and never moves to a part, a cell chemistry or
   an arrangement whose numbers the parts sheet does not give.
4. A revision never relaxes a requirement, an acceptance floor or a protective limit. A floor or a
   minimum (a required rate, a minimum margin) is never lowered. A cap or a maximum (a duty cap, a
   current limit) is never raised or deleted, with one exception: a cap re-derived, by the same
   formula and with the same margin, from the rating it protects, because the revision changed a
   part or a supply. Every change has an engineering reason, never a convenience.
5. A limit is written only from a row that publishes it as a limit or a rating. An operating point
   (a speed or a torque at peak efficiency, a typical current) is never written as a limit. A limit
   the sheet does not publish is not written.
6. "Every revision is complete" (`format.md`) covers every `constrains` edge of every changed node,
   also when the target node is rewritten in the same revision for another reason. Then its numbers
   also follow from this change, or it carries a `no_change_justified` entry keyed by the changed
   node.
7. A revision never puts a different datasheet figure under an existing quantity name (another kind
   of thermal resistance, another rating). A different figure takes a name that says which it is.

## The base

8. Each factor in a derived number applies once. A rating the sheet gives at a part's output
   already includes that part's internal reduction, and is never multiplied by it again.
