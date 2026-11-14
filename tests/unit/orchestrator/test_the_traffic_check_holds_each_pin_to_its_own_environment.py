"""The decomposition call's catalog-and-flags check holds each pin to the environment it was given.

On the earlier pins every session carries the switches that keep the served model catalog and
the remote feature flags off, so a run proceeds only when the decomposition call saw them off. On
2.1.322 the owner allowed the traffic the advisor needs, so the flags are fetched and the catalog
may be served: what the call saw is recorded with the run, and is no reason to refuse it. (A
change in that state between sessions of one run is what halts a run on the new pin.)
"""

from __future__ import annotations

import pytest

from physgate.orchestrator.decompose import traffic_refusal
from physgate.orchestrator.managed import FLAGS_OFF_BY_SETTING, ObservedTraffic

OFF = ObservedTraffic(
    served_catalog="off", served_catalog_reason="essential_traffic", feature_flags="off"
)
FLAGS_ON = ObservedTraffic(
    served_catalog="off", served_catalog_reason=None, feature_flags="not reported off"
)
BOTH_ON = ObservedTraffic(
    served_catalog="not reported off", served_catalog_reason=None, feature_flags="not reported off"
)


@pytest.mark.parametrize("version", ["2.1.272", "2.1.283", "2.1.301"])
@pytest.mark.parametrize("seen", [FLAGS_ON, BOTH_ON], ids=["flags", "catalog and flags"])
def test_an_earlier_pin_refuses_a_run_whose_call_did_not_see_both_off(
    version: str, seen: ObservedTraffic
) -> None:
    why = traffic_refusal(seen, version)
    assert why is not None and seen.feature_flags in why


@pytest.mark.parametrize("version", ["2.1.272", "2.1.283", "2.1.301", "2.1.322"])
def test_both_seen_off_refuses_nothing_on_any_pin(version: str) -> None:
    assert traffic_refusal(OFF, version) is None


def test_off_by_the_documented_setting_still_passes_on_2_1_301() -> None:
    by_setting = OFF.model_copy(update={"feature_flags": FLAGS_OFF_BY_SETTING})
    assert traffic_refusal(by_setting, "2.1.301") is None


@pytest.mark.parametrize("seen", [FLAGS_ON, BOTH_ON], ids=["flags", "catalog and flags"])
def test_on_the_new_pin_the_state_is_recorded_not_refused(seen: ObservedTraffic) -> None:
    assert traffic_refusal(seen, "2.1.322") is None
