"""The same graph and the same law table give the same law records, byte for byte, every time.

A law record is evidence a later measurement counts, so it may not depend on anything but the
graph and the table: not on the order a dictionary or a set happened to iterate in, not on the
process, not on the hash seed. The laws check is run twice in one process, and in two further
processes with different hash seeds, over a graph on which every pattern forms instances that
pass, fail and cannot be judged; every run writes the same lines.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from gate_fixtures import graph, node
from law_cases import every_case, laws_records, table

from physgate.gate.graph import GraphView

HERE = Path(__file__).parent

#: Every pattern, each passing somewhere, failing somewhere and unjudged somewhere.
PAYLOADS = [
    node(
        "electrical.imu",
        quantities={
            "power_draw": (12.9, "mW"),
            "supply_voltage": (3.3, "V"),
            "current_draw": (3.9, "mA"),
            "current_limit": (2, "mA"),
            "output_data_rate": (200, "Hz"),
        },
    ),
    node("electrical.gps", quantities={"output_data_rate": (10, "Hz"), "power_draw": (19.5, "mW")}),
    node("iface.sensor_bus", kind="interface", quantities={"output_data_rate": (50, "Hz")}),
    node(
        "firmware.estimator",
        domain="firmware",
        quantities={"update_rate": (100, "Hz")},
        constrains=["electrical.imu", "electrical.gps", "iface.sensor_bus", "electrical.missing"],
    ),
    node(
        "mechanical.chassis",
        kind="module",
        domain="mechanical",
        quantities={"reaction_moment": (3, "N*m")},
    ),
    node(
        "mechanical.arm",
        kind="module",
        domain="mechanical",
        quantities={"reaction_moment": (9, "N*m")},
    ),
    *(
        node(
            f"mechanical.{name}",
            domain="mechanical",
            quantities={"reaction_moment": (moment, "N*m")},
            constrains=[carrier],
        )
        for name, moment, carrier in (
            ("left", 1, "mechanical.chassis"),
            ("right", 2, "mechanical.chassis"),
            ("wrist", 4, "mechanical.arm"),
        )
    ),
    node(
        "electrical.motor",
        quantities={
            "stall_current": (3, "A"),
            "rated_voltage": (12, "V"),
            "motor_resistance": (6, "ohm"),
            "heat_dissipation": (4, "W"),
            "current_draw": (2, "A"),
            "duty_cycle": (0.5, "dimensionless"),
        },
    ),
    node(
        "electrical.brake",
        quantities={
            "stall_current": (1, "A"),
            "rated_voltage": (12, "V"),
            "motor_resistance": (0, "ohm"),
        },
    ),
]


def lines(root: Path) -> list[str]:
    """The laws check's records over the graph, at module and system scope, as lines."""
    laws = table(root / "t", every_case())
    graph(root / "g", *PAYLOADS)
    view = GraphView.read(root / "g", base_revision=0)
    return [r.model_dump_json() for r in laws_records(laws, view, ("module", "system"))]


def test_the_graph_draws_every_outcome(tmp_path: Path) -> None:
    outcomes = {line.split('"outcome":"')[1].split('"')[0] for line in lines(tmp_path)}
    assert outcomes == {"pass", "warn", "unchecked"}


def test_twice_in_one_process_the_records_are_identical(tmp_path: Path) -> None:
    first = lines(tmp_path / "a")
    assert first and first == lines(tmp_path / "b")


def test_in_two_processes_with_different_hash_seeds_the_records_are_identical(
    tmp_path: Path,
) -> None:
    here = lines(tmp_path / "here")
    script = (
        "import sys; from pathlib import Path; "
        f"sys.path[:0] = [{str(HERE)!r}, {str(HERE.parents[1])!r}]; "
        "import test_the_laws_check_writes_the_same_records_every_time as t; "
        "print('\\n'.join(t.lines(Path(sys.argv[1]))))"
    )
    for seed in ("1", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        done = subprocess.run(
            [sys.executable, "-c", script, str(tmp_path / f"seed-{seed}")],
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=600,
        )
        assert done.returncode == 0, done.stderr[-2000:]
        assert done.stdout.splitlines() == here
