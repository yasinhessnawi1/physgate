"""R3 — the serialisation fixture. One function, used by every Laya call.

CRITERIA §4 R3: *"One function produces the JSON for every Laya call. It emits
**exactly the raw generator fields, under the ARCH-010/ARCH-012 field names,
with readable values** (`"attempt": 2`, `"reviewer_verdict": "accept"`). It
contains **no derived feature, no engineered summary and never the label or
anything computed from it**. Its source and one example per split are committed
with the run. Without this rule every other criterion measures an unknown."*

This module is that function. Nothing else in the experiment serialises a state,
and `serialise()` is the only public entry point.

--------------------------------------------------------------------------
Why the field names are the generator's own
--------------------------------------------------------------------------
R3 asks for "the ARCH-010/ARCH-012 field names". ARCH-010 defines a graph *node*
schema (`id`, `kind`, `domain`, `owner_role`, `quantities`, `requirements`,
`constrains`, `model`, `geometry_hash`, `updated`) and ARCH-012 describes a
ledger *line* in prose ("id, spec path, assigned role, attempt count, gate
result, review result, merge commit"). Neither defines a field called
`reviewer_verdict` or `gate_propagation_pass`.

What settles it is R3's own two examples: `"attempt": 2` and
`"reviewer_verdict": "accept"` are, verbatim, two of the generator's raw field
names. So the instruction is not "rename the fields to ARCH-010's" — it is
"use the design's field names rather than the bit vector's". The contrast R3 is
drawing is with `generator.BIT_NAMES`, the 21 booleanised names
(`"attempt>=3"`, `"verdict=accept"`, `"reviewer_conf>=high"`), which *are*
derived features and which R3 forbids.

Renaming would also break R2's "one source": the arms that consume bits and the
arm that consumes JSON have to be looking at the same sample under the same
description.

The full mapping, including the fields ARCH-010 and ARCH-012 do not name, is
`ARCH_PROVENANCE` below and is reproduced in `RESULT.md`. The fields with no
ARCH counterpart are recorded as C5 M7.

--------------------------------------------------------------------------
Readable values
--------------------------------------------------------------------------
The generator stores the four gates and the two flags as ``int8`` 0/1. They are
rendered as JSON ``true``/``false``. This is a **rendering of the stored value,
not a derived feature**: it is one-to-one, reversible, and carries exactly the
information the raw field carries. R3's own examples show readable renderings
(`"attempt": 2` as a number, `"reviewer_verdict": "accept"` as a word) rather
than raw storage. Ruled by the orchestrator on 2026-09-21 and named in `RESULT.md`
as a judgement call, so a reader can disagree with it.

The rendering is applied **uniformly to every field of that kind** and to no
others. ``attempt`` and ``prior_failures_module`` stay integers, because that is
what they are. ``domain`` keeps the generator's vocabulary (``"mech"``,
``"elec"``, ``"ctrl"``, ``"fw"``) rather than ARCH-010's
(``mechanical | electrical | control | firmware``): translating the *values*
would be a substitution rather than a rendering, and R3 says "exactly the raw
generator fields". Recorded as part of C5 M7.

--------------------------------------------------------------------------
What is not here
--------------------------------------------------------------------------
No label. No `y`, no `y_clean`, no hidden-rule term, no bit vector, no count, no
aggregate, no "n_gates_failed", no ordering that depends on the sample. The
field order is fixed by `FIELD_ORDER` and is the generator's own declaration
order, so the JSON is stable across samples, splits and seeds.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

# The raw fields, in the generator's own declaration order (`sample_raw`).
FIELD_ORDER: List[str] = [
    "gate_unit_pass",
    "gate_magnitude_pass",
    "gate_power_pass",
    "gate_propagation_pass",
    "attempt",
    "reviewer_verdict",
    "reviewer_confidence",
    "domain",
    "cross_domain_quantity_changed",
    "interface_node_touched",
    "prior_failures_module",
    "spec_coverage",
]

# int8 0/1 in the generator; rendered as JSON booleans. Nothing else is.
BOOLEAN_FIELDS = frozenset({
    "gate_unit_pass",
    "gate_magnitude_pass",
    "gate_power_pass",
    "gate_propagation_pass",
    "cross_domain_quantity_changed",
    "interface_node_touched",
})

INTEGER_FIELDS = frozenset({"attempt", "prior_failures_module"})

# Where each field comes from in the architecture specification. "—" means the
# specification names no counterpart; see C5 M7.
ARCH_PROVENANCE: Dict[str, str] = {
    "gate_unit_pass": "ARCH-012 'gate result'; ARCH-031, ARCH-080. Not named individually.",
    "gate_magnitude_pass": "ARCH-012 'gate result'; ARCH-031, ARCH-080. Not named individually.",
    "gate_power_pass": "ARCH-012 'gate result'; ARCH-031, ARCH-080. Not named individually.",
    "gate_propagation_pass": "ARCH-012 'gate result'; ARCH-031, ARCH-080. Not named individually.",
    "attempt": "ARCH-012 'attempt count'; ARCH-030 repair budget of three attempts.",
    "reviewer_verdict": "ARCH-012 'review result'; ARCH-131 'the reviewer verdict'.",
    "reviewer_confidence": "—  no ARCH-010 or ARCH-012 counterpart.",
    "domain": "ARCH-010 'domain'. The only exact field-name match; values differ, see module docstring.",
    "cross_domain_quantity_changed": "ARCH-010 quantities marked 'cross' and ARCH-051 sizing; "
                                     "ARCH-131 'the changed-node summary'. No field name.",
    "interface_node_touched": "ARCH-010 kind 'interface' and ARCH-011; "
                              "ARCH-131 'the changed-node summary'. No field name.",
    "prior_failures_module": "—  no ARCH-010 or ARCH-012 counterpart.",
    "spec_coverage": "—  no ARCH-010 or ARCH-012 counterpart (ARCH-022 is about spec contents, "
                     "not a per-attempt state field).",
}

assert set(FIELD_ORDER) == set(ARCH_PROVENANCE), "mapping and field order disagree"


def state_from_raw(raw: Dict[str, Any], i: int) -> Dict[str, Any]:
    """Row ``i`` of the generator's raw dict as a plain JSON-able dict.

    ``raw`` is the fourth element of a ``generator_b.make_split`` tuple. Only the
    twelve fields in ``FIELD_ORDER`` are read; anything else in ``raw`` is
    ignored, and the split's labels are not in ``raw`` at all.
    """
    out: Dict[str, Any] = {}
    for name in FIELD_ORDER:
        v = raw[name][i]
        if name in BOOLEAN_FIELDS:
            out[name] = bool(int(v))
        elif name in INTEGER_FIELDS:
            out[name] = int(v)
        else:
            out[name] = str(v)
    return out


def serialise(raw: Dict[str, Any], i: int) -> str:
    """The JSON string handed to Laya for row ``i``. The only entry point."""
    return json.dumps(state_from_raw(raw, i), ensure_ascii=False)
