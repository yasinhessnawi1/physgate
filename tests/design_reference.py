"""A recorded script that measures Pololu's published model of the assembled Balboa 32U4.

The chassis brief asks for two dimensions no drawing gives (criteria 21 and 23): where each
gearmotor sits relative to the board's holes, and the centre distance between each motor shaft
and its wheel axle. The script reads the model the environment carries (``reference/``, fetched
by its pinned digest), finds the features by the rules in :data:`BALBOA_RULES`, and writes one
result through the geometry helper. From the model's volumes under the stated masses
(:data:`BALBOA_MASSES`) and the assumptions in :data:`BALBOA_ASSUMPTIONS` it also writes the
body's centre of mass above the axle and its inertia about the axle, with a low and a high case.

The script takes the helpers' folder and, for a run from a checkout, the environment's root:
``python -I balboa.py [<helpers> [<environment>]]``. :data:`BALBOA_RECORDED` holds the numbers of
its first run (macOS arm64), which every platform must repeat.
"""

from __future__ import annotations

import json

BALBOA_FILE = "balboa-balancing-robot-kit.step"
BALBOA_RESULT = "balboa.result.json"

#: How each feature is found, in the order the script applies them; written into the result.
BALBOA_RULES = (
    "The model's bodies are taken by their own names: 'chassis' (one solid of 12 shells, the "
    "chassis with both gearmotors merged in), 'battery-cover', the two 'wheel_black' bodies, and "
    "the two solids of 'bal01a01' (the control board). Lengths are the model's millimetres; the "
    "model's y axis points up (the wheels stand on y = -59.86 mm) and x runs along the axle.",
    "A gearmotor is the group of x-parallel cylindrical faces of the chassis of radius 6.0 mm "
    "(the motor can, within 0.01 mm) on one side of x = 0; its axis is theirs.",
    "The wheel axle on each side is the x-parallel convex cylindrical face of the chassis of "
    "radius 1.5 mm (the 3 mm shaft) whose x span reaches into that side's wheel body.",
    "A motor's output shaft is the cylindrical face of radius 1.5 mm (the shaft, or the bore it "
    "sits in) on the motor's axis within 0.001 mm, beyond the motor can's outer end; the "
    "script requires one on each motor axis and measures from the motor axis.",
    "The centre distance of a side is the distance between its motor axis and its axle axis, "
    "both parallel to x; the gear module follows as the mean of the two over 33 (each of the "
    "kit's five gear pairs has 66 teeth together).",
    "A motor's encoder disc is the x-parallel cylindrical face of radius 3.825 mm on its axis; "
    "the motor's point of reference is the centre of the disc's end face nearer x = 0.",
    "The board's mounting holes are its z-parallel holes of radius above 1.0 mm on whose axis "
    "the chassis has a cylinder of the same radius (within 0.001 mm). The PCB's faces are the "
    "board's z-normal planes of area above 1000 mm**2.",
    "A motor's reference hole is the mounting hole on its side of x = 0 whose axis is nearest "
    "its axis; its position is the reference point less the point where the hole's axis meets "
    "the PCB face nearer the motor, along the model's x, y and z.",
    "The cell cradles are the battery cover's x-parallel cylindrical faces of its one radius "
    "that has six distinct axes; each cell is placed on a cradle's axis, centred at x = 0.",
)

#: What the script assumes; written into the result.
BALBOA_ASSUMPTIONS = (
    "Each body has a uniform density; the model's bodies are the robot as assembled.",
    "The model holds no cells: six AA cells are added as uniform cylinders of 14.5 mm diameter "
    "and 50.5 mm length (the largest R6 size) on the cover's cradles.",
    "Each gearmotor is a uniform cylinder of the can's radius on the motor axis, from the can's "
    "inner end to the output shaft's start, carved out of the chassis's volume.",
    "The kit's mass less the wheels and the gearmotors is spread over the chassis, the cover and "
    "the board by volume; the low and high cases give the board half and twice the density of "
    "the plastic and the kit 10 g less and more, and the bounds are the extremes of those cases.",
    "The gears, shafts, bearings, screws and a bumper cage are inside the kit's mass and the "
    "chassis's volume, as the model merges them; none is placed on its own.",
    "The body is the robot without its two wheels: it is what pitches about the axle.",
)

#: The stated masses, each with its source: (value in kg or a count, unit, source).
BALBOA_MASSES = {
    "kit_without_cells": (
        0.200,
        "kg",
        "pololu.com/product/3575/specs, Weight: 200 g, assembled with motors, wheels and "
        "bumper cage, without batteries",
    ),
    "kit_mass_range": (0.010, "kg", "the chassis brief, criterion 7: +/- 10 g"),
    "wheel": (0.01984, "kg", "pololu.com/product/1430/specs: 0.7 oz per wheel, with tire"),
    "gearmotor": (0.0095, "kg", "pololu.com/product/3073/specs: 9.5 g"),
    "cell": (0.027, "kg", "Panasonic BK-3MCC datasheet, Weight: approx. 27 g"),
    "cells": (6, "cell", "Balboa 32U4 User's Guide: six AA cells"),
}

_SCRIPT = r'''"""Measure the published Balboa 32U4: criteria 21 and 23, and the body's masses."""

import itertools
import json
import math
import os
import sys

# The helpers' folder as named, or beside the environment's interpreter: a session's command
# may not name the environment, so the script finds them from where it runs.
here = os.path.join(os.path.dirname(sys.prefix), "helpers")
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else here)
import geometry  # noqa: E402
import result_file  # noqa: E402
from build123d import Cylinder, Pos, Rot  # noqa: E402
from OCP.BRepAdaptor import BRepAdaptor_Surface  # noqa: E402

RULES = json.loads(__RULES__)
ASSUMPTIONS = json.loads(__ASSUMPTIONS__)
MASSES = json.loads(__MASSES__)
FILE = __FILE__
MM = 1e-3
CAN, SHAFT, DISC = 6.0, 1.5, 3.825
AA_DIAMETER, AA_LENGTH = 14.5, 50.5

root = sys.argv[2] if len(sys.argv) > 2 else None
model, entry = geometry.import_reference(FILE, root)
bodies = {}
for child in model.children:
    for index, solid in enumerate(child.solids()):
        bodies.setdefault(child.label, []).append(solid)
(chassis,) = bodies["chassis"]
(cover,) = bodies["battery-cover"]
wheels = bodies["wheel_black"]
board = bodies["bal01a01"]
assert len(wheels) == 2 and len(board) == 2, (len(wheels), len(board))


def cylinders(solid, direction):
    """Each cylindrical face of ``solid`` whose axis is parallel to ``direction`` (0, 1, 2)."""
    found = []
    for face in solid.faces():
        if face.geom_type.name != "CYLINDER":
            continue
        surface = BRepAdaptor_Surface(face.wrapped).Cylinder()
        axis = surface.Axis()
        d = axis.Direction()
        if abs(abs((d.X(), d.Y(), d.Z())[direction]) - 1) > 1e-9:
            continue
        p = axis.Location()
        box = face.bounding_box()
        span = ((box.min.X, box.max.X), (box.min.Y, box.max.Y), (box.min.Z, box.max.Z))
        found.append({
            "radius": surface.Radius(),
            "point": (p.X(), p.Y(), p.Z()),
            "span": span[direction],
            "convex": face.wrapped.Orientation().name == "TopAbs_FORWARD",
        })
    return found


def across(cyl, direction):
    """The two coordinates of the axis across ``direction``."""
    return tuple(c for k, c in enumerate(cyl["point"]) if k != direction)


def near(a, b, within):
    return math.dist(a, b) <= within


x_cylinders = cylinders(chassis, 0)
motors, axles, shafts, discs = {}, {}, {}, {}
for side, sign in (("left", -1), ("right", 1)):
    cans = [c for c in x_cylinders
            if abs(c["radius"] - CAN) <= 0.01 and sign * sum(c["span"]) > 0]
    axes = {round(v, 6) for c in cans for v in across(c, 0)}
    assert cans and len(axes) == 2, (side, axes)
    motor = across(cans[0], 0)
    motors[side] = motor
    can_outer = max(sign * x for c in cans for x in c["span"])
    wheel = next(w for w in wheels if sign * w.center().X > 0)
    wb = wheel.bounding_box()
    found = [c for c in x_cylinders
             if abs(c["radius"] - SHAFT) <= 1e-6 and c["convex"]
             and c["span"][1] > wb.min.X and c["span"][0] < wb.max.X]
    axle_axes = {tuple(round(v, 6) for v in across(c, 0)) for c in found}
    assert len(axle_axes) == 1, (side, axle_axes)
    axles[side] = across(found[0], 0)
    on_motor = [c for c in x_cylinders
                if abs(c["radius"] - SHAFT) <= 1e-6 and near(across(c, 0), motor, 1e-3)
                and min(sign * x for x in c["span"]) >= can_outer - 1e-6]
    assert on_motor, side
    shafts[side] = min(min(sign * x for x in c["span"]) for c in on_motor)
    disc = [c for c in x_cylinders
            if abs(c["radius"] - DISC) <= 1e-6 and near(across(c, 0), motor, 1e-3)]
    assert disc, side
    discs[side] = sign * min(min(sign * x for x in c["span"]) for c in disc)

# The board: its mounting holes (with a chassis cylinder on the same axis) and its PCB faces.
chassis_z = cylinders(chassis, 2)
pcb, *parts = sorted(board, key=lambda s: -s.volume)
holes = []
for c in cylinders(pcb, 2):
    if c["radius"] <= 1.0:
        continue
    xy = across(c, 2)
    if any(abs(o["radius"] - c["radius"]) <= 1e-3 and near(across(o, 2), xy, 1e-3)
           for o in chassis_z):
        if not any(near(xy, h, 1e-6) for h in holes):
            holes.append(xy)
faces = sorted({round(f.center().Z, 9) for f in pcb.faces()
                if f.geom_type.name == "PLANE" and f.area > 1000})
assert len(faces) == 2, faces
values = {}
for side, sign in (("left", -1), ("right", 1)):
    my, mz = motors[side]
    ay, az = axles[side]
    distance = math.hypot(my - ay, mz - az)
    values[f"gear_centre_distance_{side}"] = result_file.quantity(distance * MM, "m")
    mine = [h for h in holes if sign * h[0] > 0]
    hole = min(mine, key=lambda h: abs(h[1] - my))
    face = min(faces, key=lambda z: abs(mz - z))
    values[f"motor_position_{side}"] = result_file.quantity(
        [(discs[side] - hole[0]) * MM, (my - hole[1]) * MM, (mz - face) * MM], "m",
        about="the encoder disc's inner face centre, from the reference hole on the PCB face",
    )
    values[f"reference_hole_{side}"] = result_file.quantity(
        [hole[0] * MM, hole[1] * MM, face * MM], "m")
    values[f"motor_axis_{side}"] = result_file.quantity([my * MM, mz * MM], "m",
                                                        about="y and z of the axis")
    values[f"axle_axis_{side}"] = result_file.quantity([ay * MM, az * MM], "m",
                                                       about="y and z of the axis")
values["mounting_holes"] = result_file.quantity(len(holes), "hole")
values["gear_module_from_centre_distance"] = result_file.quantity(
    (values["gear_centre_distance_left"]["value"] + values["gear_centre_distance_right"]["value"])
    / 2 / 33, "m")

# ---- mass properties: each piece's volume and its moments about the axle, at unit density ----
axle_y = (axles["left"][0] + axles["right"][0]) / 2
axle_z = (axles["left"][1] + axles["right"][1]) / 2
UNIT = {"value": 1, "unit": "kg/m**3"}


def moments(shape):
    """Volume (m**3), first moments about the axle in y and z (m**4), second moment (m**5)."""
    found = geometry.mass_properties(shape, density=UNIT, density_source="unit density")
    v = found["volume"]["value"]
    _, cy, cz = found["centre_of_mass"]["value"]
    dy, dz = cy - axle_y * MM, cz - axle_z * MM
    inertia = found["inertia"]["value"][0][0]
    return (v, v * dy, v * dz, inertia + v * (dy * dy + dz * dz))


def gearmotor(side, sign):
    my, mz = motors[side]
    inner = min(abs(x) for c in x_cylinders if abs(c["radius"] - CAN) <= 0.01
                and sign * sum(c["span"]) > 0 for x in c["span"])
    length = shafts[side] - inner
    middle = sign * (inner + length / 2)
    return Pos(middle, my, mz) * Rot(0, 90, 0) * Cylinder(CAN, length)


cradles = {}
for c in cylinders(cover, 0):
    cradles.setdefault(round(c["radius"], 6), set()).add(tuple(round(v, 6) for v in across(c, 0)))
six = [axes for axes in cradles.values() if len(axes) == 6]
assert len(six) == 1, {r: len(a) for r, a in cradles.items()}
cells = [Pos(0, y, z) * Rot(0, 90, 0) * Cylinder(AA_DIAMETER / 2, AA_LENGTH)
         for y, z in sorted(six[0])]

piece = {
    "chassis": moments(chassis),
    "cover": moments(cover),
    "board": tuple(map(sum, zip(*(moments(s) for s in board)))),
    "gearmotors": tuple(map(sum, zip(moments(gearmotor("left", -1)),
                                      moments(gearmotor("right", 1))))),
    "cells": tuple(map(sum, zip(*(moments(c) for c in cells)))),
}
wheel_moments = [moments(w) for w in wheels]
plastic = tuple(a - b for a, b in zip(piece["chassis"], piece["gearmotors"]))
kit, spread = MASSES["kit_without_cells"][0], MASSES["kit_mass_range"][0]
wheel_mass, motor_mass = MASSES["wheel"][0], MASSES["gearmotor"][0]
cell_mass = MASSES["cell"][0] * MASSES["cells"][0]


def body(kit_mass, board_factor):
    """Mass, centre of mass above and forward of the axle, inertia about it: the body."""
    rest = kit_mass - 2 * wheel_mass - 2 * motor_mass
    volume = plastic[0] + piece["cover"][0] + board_factor * piece["board"][0]
    rho = rest / volume
    weighted = [
        (rho, plastic), (rho, piece["cover"]), (rho * board_factor, piece["board"]),
        (2 * motor_mass / piece["gearmotors"][0], piece["gearmotors"]),
        (cell_mass / piece["cells"][0], piece["cells"]),
    ]
    mass = sum(d * m[0] for d, m in weighted)
    up = sum(d * m[1] for d, m in weighted) / mass
    forward = sum(d * m[2] for d, m in weighted) / mass
    inertia = sum(d * m[3] for d, m in weighted)
    return mass, up, forward, inertia


nominal = body(kit, 1.0)
cases = [body(k, f) for k, f in itertools.product((kit - spread, kit, kit + spread), (0.5, 1, 2))]
names = ("body_mass", "centre_of_mass_above_axle", "centre_of_mass_forward_of_axle",
         "inertia_about_axle")
units = ("kg", "m", "m", "kg*m**2")
for k, (name, unit) in enumerate(zip(names, units)):
    found = [case[k] for case in cases]
    values[name] = result_file.quantity([min(found), nominal[k], max(found)], unit,
                                        cases="low, nominal, high")
values["wheel_inertia_about_axle"] = result_file.quantity(
    [wheel_mass / w[0] * w[3] for w in wheel_moments], "kg*m**2", about="each wheel, by volume")
inputs = {name: result_file.quantity(v, unit, source=source)
          for name, (v, unit, source) in MASSES.items()}
result = geometry.reference_result(
    "the gearmotors' position and gear centre distance, and the body's mass properties",
    entry, method=RULES, values=values, inputs=inputs, assumptions=ASSUMPTIONS)
result_file.write(os.path.join(os.getcwd(), __RESULT__), result)
print("BALBOA " + json.dumps({k: v["value"] for k, v in values.items()}))
'''

#: The script, as a role writes it into its module.
BALBOA = (
    _SCRIPT.replace("__RULES__", repr(json.dumps(list(BALBOA_RULES))))
    .replace("__ASSUMPTIONS__", repr(json.dumps(list(BALBOA_ASSUMPTIONS))))
    .replace("__MASSES__", repr(json.dumps(BALBOA_MASSES)))
    .replace("__FILE__", repr(BALBOA_FILE))
    .replace("__RESULT__", repr(BALBOA_RESULT))
)

#: The numbers of the first run, by name: (value, unit). Filled from that run's result.
BALBOA_RECORDED: dict[str, tuple[object, str]] = {
    "axle_axis_left": ([-0.01985992193816534, -0.009681921938164832], "m"),
    "axle_axis_right": ([-0.01985992193816532, -0.009681921938165588], "m"),
    "body_mass": ([0.31232000000000004, 0.32232000000000005, 0.33232000000000006], "kg"),
    "centre_of_mass_above_axle": (
        [0.015976242309414794, 0.016485176582983457, 0.017237565979651055],
        "m",
    ),
    "centre_of_mass_forward_of_axle": (
        [0.0021421327773803443, 0.0024034018307457056, 0.0028601692405155173],
        "m",
    ),
    "gear_centre_distance_left": (0.016499999999999692, "m"),
    "gear_centre_distance_right": (0.016500075757402168, "m"),
    "gear_module_from_centre_distance": (0.0005000011478394222, "m"),
    "inertia_about_axle": (
        [0.0003150260747461112, 0.0003340984514253785, 0.00036055884764437507],
        "kg*m**2",
    ),
    "motor_axis_left": ([-0.01985992193816528, 0.006818078061834859], "m"),
    "motor_axis_right": ([-0.019909921938165237, 0.006818078061834739], "m"),
    "motor_position_left": (
        [0.0033749855000000674, 0.01009999960000004, 0.005203199999834859],
        "m",
    ),
    "motor_position_right": (
        [-0.00337499469999999, 0.010049999600000081, 0.00520319999983474],
        "m",
    ),
    "mounting_holes": (10, "hole"),
    "reference_hole_left": (
        [-0.0049999853999999795, -0.02995992153816532, 0.0016148780620000001],
        "m",
    ),
    "reference_hole_right": (
        [0.00499999460000002, -0.02995992153816532, 0.0016148780620000001],
        "m",
    ),
    "wheel_inertia_about_axle": ([2.254053090737425e-05, 2.254053090737427e-05], "kg*m**2"),
}
