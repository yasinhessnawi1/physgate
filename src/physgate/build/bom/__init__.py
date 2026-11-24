"""The parts a person left to find, checked offline against a price sheet (ARCH-120, ARCH-121).

A slice that is shown, not measured. It reads a recorded run's event log, takes as its lines the
plan's parts a person answered "find" (not a bill of materials a design produced), looks each up
by its exact node id in a price sheet committed beside this code and labelled as an example
fixture, and gives each line a verdict on the five facts ARCH-120 names and the two limits the
frozen risk table sets for sourcing in Norway.

- :mod:`.sheet`: the sheet's schema, where every number is a value with its unit, and its loader.
- :mod:`.check`: the lines of a run and the verdict rules.
- :mod:`.cli`: ``physgate bom check <run>``.

Deliberately not here: a live distributor (it needs credentials, and which distributor to
use is not chosen here), the orchestrator sending a failing line back to a role, and the
measurement the risk row asks for. There is no way to order: the check only reads (ARCH-121).
"""
