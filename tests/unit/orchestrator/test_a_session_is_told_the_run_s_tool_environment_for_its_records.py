"""A session's scripts are told the run's tool environment; the collector is told how it stood.

The session's environment names the run's recorded roots and manifest digest, as the writer
reads them to name the environment's code once. What the collector is told says, beside the
same roots and digest, whether the environment was held to the record before the session and
whether the OS layer ran around it. A run that names no environment tells neither anything.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_a_run_s_tool_environment_is_measured_recorded_and_held_before_every_session import (
    _environment,
)

from physgate.orchestrator.exceptions import InvocationError
from physgate.orchestrator.tool_environment import (
    measure_named,
    sealing_environment,
    series_environment,
)
from physgate.series.collect import SeriesEnvironment
from physgate.series.writer import ENVIRONMENT_VARIABLE


def test_the_session_s_environment_names_the_run_s_roots_and_digest(tmp_path: Path) -> None:
    recorded = measure_named(_environment(tmp_path), forbidden={})
    env = {"PATH": "/usr/bin", "HOME": "/h"}
    told = series_environment(env, recorded)
    assert ENVIRONMENT_VARIABLE in told, told
    assert json.loads(told[ENVIRONMENT_VARIABLE]) == {
        "roots": list(recorded.roots),
        "sha256": recorded.manifest_digest,
    }
    assert {k: v for k, v in told.items() if k != ENVIRONMENT_VARIABLE} == env
    assert ENVIRONMENT_VARIABLE not in env


def test_a_session_environment_that_already_holds_the_variable_is_refused(tmp_path: Path) -> None:
    recorded = measure_named(_environment(tmp_path), forbidden={})
    env = {"PATH": "/usr/bin", ENVIRONMENT_VARIABLE: '{"roots": ["/elsewhere"]}'}
    with pytest.raises(InvocationError, match="already holds"):
        series_environment(env, recorded)


@pytest.mark.parametrize(("held", "layer"), [(True, True), (True, False), (False, True)])
def test_the_collector_is_told_the_roots_the_digest_and_how_the_environment_stood(
    tmp_path: Path, held: bool, layer: bool
) -> None:
    recorded = measure_named(_environment(tmp_path), forbidden={})
    assert sealing_environment(recorded, held=held, layer=layer) == SeriesEnvironment(
        roots=tuple(recorded.roots), sha256=recorded.manifest_digest, held=held, layer=layer
    )


def test_a_run_that_names_no_environment_tells_the_collector_none() -> None:
    assert sealing_environment(None, held=True, layer=True) is None
