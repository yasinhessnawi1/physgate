"""PROVISIONAL serialisation of a generator sample to the JSON Laya sees.

**This is not the R3 fixture.** The R3 serialisation fixture is step 2's
deliverable. This module exists for one purpose only: to give step 1's
feasibility timing realistic token lengths, so that the seconds-per-update
number is measured on sequences the length the real run will use.

It follows R3's shape - exactly the raw generator fields, under readable names,
with readable values, no derived feature, no engineered summary, and never the
label or anything computed from it - so that the token-length distribution it
produces is representative. It is committed here so that step 2 can diff its
fixture against it and say whether the lengths moved. If they move materially,
step 1's wall-clock estimate has to be re-checked.

Nothing downstream of step 1 may import this module.
"""
from __future__ import annotations

import json
from typing import Any, Dict

# The raw field order the generator produces, fixed here so the JSON is stable.
FIELD_ORDER = [
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

# The generator stores these as int8 0/1. "Readable value" for a pass/fail gate
# is a boolean, not a 0. This is one of the choices step 2's fixture has to make
# deliberately; it is made provisionally here and flagged.
BOOLEAN_FIELDS = {
    "gate_unit_pass",
    "gate_magnitude_pass",
    "gate_power_pass",
    "gate_propagation_pass",
    "cross_domain_quantity_changed",
    "interface_node_touched",
}


def state_from_raw(raw: Dict[str, Any], i: int) -> Dict[str, Any]:
    """Row ``i`` of the generator's raw dict, as a plain JSON-able dict."""
    out: Dict[str, Any] = {}
    for name in FIELD_ORDER:
        v = raw[name][i]
        if name in BOOLEAN_FIELDS:
            out[name] = bool(int(v))
        elif name in ("attempt", "prior_failures_module"):
            out[name] = int(v)
        else:
            out[name] = str(v)
    return out


def serialise(raw: Dict[str, Any], i: int) -> str:
    return json.dumps(state_from_raw(raw, i), ensure_ascii=False)
