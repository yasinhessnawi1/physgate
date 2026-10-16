"""A stand-in control session's recording script, shared by the stand-in and real-binary tests.

Standard library only, as a role's own script is. It simulates a small stable loop, ``L(s) =
K / (s (s + 1) (0.1 s + 1))`` under unity feedback, with a fourth-order Runge-Kutta step; it
is a stand-in, not the robot. Through the run's series writer it records:

- the nominal step response (group ``step``);
- the loop's frequency response, broken at the plant input (group ``frequency_response``);
- four edge-of-region step responses, one per gain (group ``edge_runs``).

Then it reads the phase margin and the step's peak off its own records with the published
extractors and prints them, each with the record it was read off, as JSON. Given a node id as
its argument, it also writes the node proposal carrying them, as a session reporting what it
read would.
"""

from __future__ import annotations

#: The records the script writes, by id.
RECORD_IDS = ("step_nominal", "edge_01", "edge_02", "edge_03", "edge_04", "loop_nominal")

CONTROL_SCRIPT = """import json, math, os, sys
here = os.path.dirname(os.path.abspath(__file__))
while not os.path.isfile(os.path.join(here, ".physgate", "lib", "series_writer.py")):
    here = os.path.dirname(here)
sys.path.insert(0, os.path.join(here, ".physgate", "lib"))
import series_writer

seed = int(os.environ.get("STAND_IN_SEED", "7"))
NOMINAL = 2.0


def step(k, t_end=10.0, dt=0.001, every=20):
    # 0.1 y''' + 1.1 y'' + y' = k (r - y), r = 1: a unit step, through RK4.
    def f(x):
        y, v, a = x
        return (v, a, (k * (1.0 - y) - v - 1.1 * a) / 0.1)

    x = (0.0, 0.0, 0.0)
    times, ys, errors = [0.0], [0.0], [1.0]
    for n in range(1, int(round(t_end / dt)) + 1):
        k1 = f(x)
        k2 = f(tuple(xi + dt / 2 * ki for xi, ki in zip(x, k1)))
        k3 = f(tuple(xi + dt / 2 * ki for xi, ki in zip(x, k2)))
        k4 = f(tuple(xi + dt * ki for xi, ki in zip(x, k3)))
        x = tuple(
            xi + dt / 6 * (a + 2 * b + 2 * c + d) for xi, a, b, c, d in zip(x, k1, k2, k3, k4)
        )
        if n % every == 0:
            times.append(n * dt)
            ys.append(x[0])
            errors.append(1.0 - x[0])
    return times, ys, errors


def record_step(record_id, k, group):
    times, ys, errors = step(k)
    series_writer.record(
        record_id,
        title="Stand-in loop, unit step at gain %g, not the robot" % k,
        axis="time",
        x=("time", "s", times),
        traces=[("position", "m", ys), ("error", "m", errors)],
        inputs={"seed": (seed, "dimensionless"), "gain": (k, "dimensionless"), "step": (1.0, "m")},
        group=group,
    )
    return ys


ys = record_step("step_nominal", NOMINAL, "step")
for number, k in enumerate((1.0, 1.5, 2.5, 3.0), start=1):
    record_step("edge_%02d" % number, k, "edge_runs")

ws = [0.01 * 10 ** (4.0 * i / 799) for i in range(800)]
mags = [NOMINAL / (w * math.hypot(1.0, w) * math.hypot(1.0, 0.1 * w)) for w in ws]
phases = [-math.pi / 2 - math.atan(w) - math.atan(0.1 * w) for w in ws]
series_writer.record(
    "loop_nominal",
    title="Stand-in loop gain K/(s(s+1)(0.1s+1)), broken at the plant input, not the robot",
    axis="frequency",
    x=("angular_frequency", "rad/s", ws),
    traces=[("loop_magnitude", "dimensionless", mags), ("loop_phase", "rad", phases)],
    inputs={"seed": (seed, "dimensionless"), "gain": (NOMINAL, "dimensionless")},
    group="frequency_response",
)

reported = {
    "phase_margin": {
        "value": series_writer.extract("phase_margin", omega=ws, magnitude=mags, phase=phases),
        "unit": "rad",
        "series": {"record": "loop_nominal", "extract": "phase_margin"},
    },
    "step_peak": {
        "value": series_writer.extract("max_abs", values=ys),
        "unit": "m",
        "series": {"record": "step_nominal", "extract": "max_abs", "trace": "position"},
    },
}
if len(sys.argv) > 1:
    node_id = sys.argv[1]
    role = node_id.split(".")[0]
    for quantity in reported.values():
        quantity.update(source="read off the session's own record", written_by=role)
    node = {
        "id": node_id, "kind": "component", "domain": role, "owner_role": role,
        "quantities": reported, "requirements": [], "constrains": [], "model": None,
        "geometry_hash": "sha256:0", "updated": "2026-10-16T00:00:00Z",
    }
    proposals = os.path.join(here, ".physgate", "proposals")
    os.makedirs(proposals, exist_ok=True)
    with open(os.path.join(proposals, node_id + ".json"), "w") as out:
        json.dump(node, out)
else:
    print(json.dumps(reported))
"""
