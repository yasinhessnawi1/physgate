# Sizing — skill

> Procedures and antipatterns for sizing tasks, researched and drafted from published sources by an
> agent and approved by a person before use. Rule numbers (§N) refer to
> `knowledge/sizing/standards.md`; read `knowledge/cross/standards.md` first.

## Procedure: reading what you are given

1. Read your specification: which pass this is (the first, or the closing pass after the domain
   modules), and the quantities it names as yours.
2. List every criterion of the brief your specification quotes or cites that fixes, bounds or
   depends on a cross quantity: a part, a supply, a limit, a speed, a load, a mass.
3. List the domain modules of the plan and what each reads from sizing, by its specification and
   its interface nodes.
4. On the closing pass, read every sizing node, every node it constrains and every node that
   constrains it, as the design graph holds them now, and note which changed after the first pass
   (§11).

## Procedure: the cross-quantity table

One row per quantity sizing writes (§1, §2):

| Node, quantity | Value, unit | Kind of source | Source and condition | Domains that read it | `constrains` |
|---|---|---|---|---|---|
| e.g. supply, `supply_voltage` | 7.2 V nominal; range written beside it | brief, maker | brief criterion n; cell datasheet, nominal and cut-off per cell × cells | control, firmware | the nodes that use it |

1. A value the brief fixes is copied as the brief states it, with the criterion named, unless a
   person's order carried to the pass chose another value, which is then written (§3, §11).
2. A maker's figure is quoted at its stated condition (§2).
3. A calculated value shows its formula and each input with its source.
4. A value with none of these is a best estimate marked TBR, with its rationale, what would resolve
   it and who (§2).
5. Use a name the automated checks know where the quantity is one. Under a name a check compares
   with a bound, write the value it must judge (the largest demand, the rating); under any other,
   the brief's or the nominal value. Other conditions go under `_max`, `_min` or `_nominal` (§10).
   An efficiency or a duty cycle is a fraction in the unit `1`, under `efficiency`, `duty_cycle` or
   a name ending in `_efficiency` or `_duty_cycle` (§10).
6. A quantity two domains read that the plan gave sizing no node for is listed as unowned (§1).

## Procedure: the interfaces sizing produces

1. List every interface node the plan gives sizing (its owner is sizing) and its quantities.
2. For each, keep one node of your own in the cross-quantity table that names the interface in its
   `constrains` edges and holds every one of the interface's quantities under the same name, in a
   unit of the same kind, with the value the domains are to read (§10). Values at other conditions
   go under suffixed names on that node.
3. Never write the interface node: at the change check of your first pass the harness writes it
   from your joined node, and your reviewer is shown each value that changes, old and new. An
   interface with no joined node, a missing name, two joined nodes that disagree, or a unit of
   another kind refuses the attempt before the gate (§10).

## Procedure: the supply range

1. Write the nominal voltage, and the lowest and highest the supply reaches in use, each with its
   source (§4): the top is cells × the charged open-circuit voltage; the bottom is cells × the
   cut-off, less any drop under load the design knows.
2. For each value derived from the supply, say which voltage it was computed at, and check it at
   the worst end: demands against ratings at the top, speeds and headroom at the bottom. A criterion
   the specification pins to one design voltage is checked at it, with what the ends give stated
   beside it.

## Procedure: a motor's operating points

1. Take the two published points at the rated voltage: no-load speed and current, stall torque and
   current (§5).
2. Fit `R`, `K_t` and `K_e`; say which `K_t` fit you use and why; show the arithmetic with units.
   Keep `K_t` and `K_e` separate when they were fitted at a gearbox output.
3. For each further gear stage, from tooth counts where the maker gives them: `K_e` times its ratio,
   `K_t` times its ratio and its efficiency (1 where none is sourced, stated as an assumption).
4. At each voltage that matters (the command limit's average at the top, nominal and bottom of the
   supply range): stall current `V / R`, no-load speed, and the torque available at the speeds the
   specification asks for; and the reversal current `(V + K_e·ω) / R` at the largest speed the
   design states, unless a stated reason says it cannot occur (§7).
   Arithmetic example: `R` = 2.0 Ω at 12 V is 6.0 A at stall.
5. Note where the maker calls a figure extrapolated, and the maker's continuous-load guidance (§5).

## Procedure: a command limit

1. Write the full scale and the limit in the units the firmware uses (counts), and the duty
   `limit / full scale` (§6).
2. Convert to an average voltage at the supply voltage the brief or the design names, and say which.
3. At that voltage, compute what the limit allows: no-load speed, stall current, and the torque at
   the speeds the specification asks for.
4. Compare with each criterion your specification gives that needs voltage, speed or torque. Where
   the comparison needs a domain's model (a controller's plant, a recovery), state that, with the
   headroom the limit leaves at the criterion's condition. A criterion the limit cannot meet is a
   conflict: record it (below), and keep the limit the brief fixes (§3).

## Procedure: the current budget

| Supply element | Rating, kind, source | Currents that flow at once, condition | Sum | Margin |
|---|---|---|---|---|
| e.g. one motor driver | peak rating, datasheet section | its motor at stall at the largest voltage it can be commanded; its reversal current, or the reason it cannot occur | | capability − demand, and capability ÷ demand |

One row per element on each path (§7); a rating not found is written as missing.

## Procedure: the mass budget

List every part with its mass and source, the sum, and where a domain needs them the centre of mass
and inertia with how each was found; an estimate is TBR (§8).

## Procedure: recording a conflict

In a record under your module directory, cited from the `source` of the value it concerns (§3, §9):

1. The two statements, each with its criterion or source.
2. The calculation that shows they conflict, with units.
3. The margin, negative, and the criterion it puts at risk.
4. That the value written is the one the brief fixes, and that deciding is a person's.

## Procedure: the closing pass

1. For each node read in step 4 of the first procedure that changed: rewrite each joined sizing
   node to agree with it, citing the node it follows, or keep its values and write the reason in
   `no_change_justified` under the changed node's id (§11).
2. Recompute the budgets and margins the change touches (§7, §8, §9).
3. Where your specification or a person's order carries a value a person chose on a dispute, write
   it exactly as chosen (§11).
4. For each rewritten value whose edges reach a domain node, record the node, the value and the
   follow-up it now owes (§11).
5. Write no node of another role.

## Antipatterns

- **A domain's number written by a domain.** A quantity two domains read is sizing's; a domain
  writing it, or keeping its own copy, makes two values (§1).
- **A number with no condition.** A stall current with no voltage, a speed with no load (§2, §5).
- **Moving a brief's limit to make a criterion pass.** The brief's value stands, unless a person
  chose another; the conflict is recorded (§3).
- **Negotiating a dispute.** Sizing does not see or reply to a dispute; precedence and a person
  decide (§3).
- **One voltage for every check.** A stall current at the nominal voltage understates the worst
  case; a speed at a fresh charge overstates it (§4).
- **Equating constants fitted at a gearbox output.** The output torque carries the gearbox's losses
  (§5).
- **Treating an extrapolated stall figure as a working point.** The maker calls it theoretical (§5).
- **A count limit called a voltage.** It is a voltage only at a named supply voltage (§6).
- **Peak against continuous.** A stall current compared with a continuous rating, or a sustained
  draw with a peak one (§7).
- **Stall as the worst current of a motor that reverses.** Reversed while turning, it draws more
  (§7).
- **Motors counted one at a time.** Motors that start together draw together (§7).
- **A mass with parts missing.** The batteries are the usual omission (§8).
- **An invented margin.** A margin no source requires, presented as one that does (§9).
- **A name of your own for a known quantity.** It leaves the value unchecked (§10).
- **A missing edge.** A cross node with no `constrains` edge to a node that uses it lets a change
  go unpropagated (§10, §11).
- **An interface left to the plan's guess.** No node of sizing's joined to an interface it
  produces, or one that lacks one of its names: the attempt is refused, and the domains would read
  the plan's forecast instead of the computed values (§10).
- **A percentage as a fraction.** An efficiency of 90 or a duty of 75 is refused; write 0.9 and
  0.75 (§10).
- **A closing pass that only re-reads.** A changed domain node owes a rewrite or a stated reason
  (§11).
