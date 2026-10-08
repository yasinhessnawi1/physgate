# Cross-domain standards

> Researched and drafted by the
> implementing agent per the spec's content-authorship correction (Yasin, 29.09.2026): grounded in
> this project's own already-built and already-cited enforcement, reviewed and iterated by Yasin
> before any promotion. Every rule below names what enforces it; none is invented to fill a gap.

Read this file first, before any domain's own standards file, on every task regardless of domain.
It states the rules the automated design-quantity checks (the gate) already hold every domain's
numbers to, and the minimum documentation discipline every role owes every other role, the gate,
and the reviewer.

## 1. Every quantity is a `{value, unit, source, written_by}` record

A bare number is a schema error and is refused before it ever reaches the gate. A quantity's
`source` names where the number came from (a datasheet, a calculation, a cited standard) — not
because a document requires it, but because the next role, the reviewer, and the gate's own
magnitude check all need to know where a number claims to come from.

**Enforced:** the design-state graph's schema validation (a bare number fails to write at all); the
gate's check 1 re-validates unit consistency on every committed expression regardless.

## 2. Units are SI, or an SI-coherent unit, and unit arithmetic is exact

Angles are dimensionless in unit arithmetic but are tracked separately by their radian power (a
frequency and an angular velocity are not interchangeable even though both reduce to 1/s)
[International Bureau of Weights and Measures, *The International System of Units (SI)*, 9th
edition, 2019, §2.3.3 (angles are "quantities with the unit one") and §2.3.4
("The SI unit of frequency is hertz, the SI unit of angular velocity and angular frequency is
radian per second"; Table 4, note (b))]. An absolute temperature and a temperature *difference* are
different kinds in the catalogue — `temperature` may be written in an offset unit such as Celsius;
`temperature_difference` may not, always Kelvin — because subtracting two absolute temperatures
gives a difference, not another absolute temperature, and the offset does not carry over into it.
SI itself allows either unit for a difference ("A difference or interval of temperature may be
expressed in kelvins or in degrees Celsius" [ibid., §2.3.1, the kelvin; Table 4, note (f)]);
kelvin-only is the gate's own, stricter convention, so that the Celsius offset can
never be applied to a difference. The convention's record cites the Brochure at §2.3.4 and the
notes to Table 4, as read via search, not in full, 26.09.2026.

**Enforced:** gate check 1 (`check_units.py`), which parses every unit against the catalogue's kind
rules — this is the same rule the gate's own catalogue already carries.

## 3. A magnitude claim is checked against a sourced range, or is recorded as unchecked — never assumed passed

Every quantity name the catalogue knows is checked against a range that itself carries a source, a
retrieval date, and a note on what it does and does not cover
(`knowledge/<domain>/bounds.toml`). A quantity under a name the catalogue does not know gets a unit
check and nothing else, and is recorded `unchecked` — visibly, not silently.

**Enforced:** gate check 2 (`check_magnitude.py`).

## 4. A supply is held to no more than what it can prove it supplies

A source of power or energy must declare its rating (a rated output power, an energy capacity); a
consumer's draw is checked against what its supply is declared to provide, at both module and
system scope.

**Enforced:** gate checks 4 and 5 (`check_power.py`, `check_conservation.py`).

## 5. A changed quantity that constrains another node owes that node a follow-up, or a stated reason it needs none

If a node's quantities change in a way that is physically different (not a re-saved identical
number), every node its `constrains` edges name owes a later change in the same change set or a
subsequent one — or the owning role writes a non-empty reason in `no_change_justified`, recorded as
unchecked, never silently passed.

**Enforced:** gate check 7 (`check_propagation.py`), at the integration call.

## 6. A thermal or mechanical margin is checked where a limit exists, and named as absent where it does not

A component with a declared thermal resistance or heat-rejection capacity is held to a margin at
module and system scope — a negative margin warns at module scope and blocks at system scope, not
the same severity at both; a mount is solved in closed form where it is statically determinate, and
where it is not, its declared reactions are checked against the loads for balance, with the load
split between supports left explicitly unverified rather than assumed correct.

**Enforced:** gate checks 3 and 6 (`check_equilibrium.py`, `check_thermal.py`).

## 7. Nothing above substitutes for engineering judgement

The gate catches a unit that does not parse, a magnitude outside its sourced range, an unbalanced
supply, an unpropagated change, and a mount or thermal path with no margin. It does not catch wrong
physics reasoning, a bad topology choice, or a plausible-looking number that is still wrong for the
application. That is what the reviewer is for, and what your own domain standards file exists to
reduce the odds of — read it next.

**Judgement-only** — this rule is the stated limit of everything enforced above, not itself a
further gate check; nothing in the gate verifies that a reviewer actually catches what this section
says the gate cannot.
