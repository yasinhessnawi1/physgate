"""The per-role report has a section for control and one for firmware, and none for a whole run."""

from __future__ import annotations

import json

import pytest
from report_fixtures import design

from physgate.evaluation.per_role.report import ReportError, parse_design


def test_the_per_role_report_has_no_whole_run_section_and_refuses_such_a_suite() -> None:
    spec = design()
    spec["suites"][0]["role"] = "whole_run"
    named = "the suite 'control_visible' is of a whole run: this report has no whole-run section"
    with pytest.raises(ReportError, match=named):
        parse_design(json.dumps(spec).encode())
