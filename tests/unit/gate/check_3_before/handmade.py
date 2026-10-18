"""The hand-made statics graphs the record holds, written here so a clean clone remakes it.

Three ways of writing one small robot's statics (S1 placed the way the check reads them,
S2 with forces and masses and no positions, S3 with the structure naming its supports),
each with correct revisions and errors written by hand; then the probe shapes a review of
the equilibrium fix wrote: load forces in refused units beside a failing mount, a stale
load force, dummy reaction pairs, reactions that carry the wheels' own weight, reactions
of the other sign, a sideways reaction, sub-assemblies, and a two-standoff split that
balances in total and is wrong support by support. Every design and every error here is
invented; none is taken from any corpus.
"""

from __future__ import annotations

import copy
from typing import Any

URL = "https://example.org/hand-made-sheet"
OWNER = {"mechanical": "mechanical", "electrical": "electrical", "control": "control"}


def q(value: float, unit: str, role: str) -> dict[str, Any]:
    return {"value": value, "unit": unit, "source": URL, "written_by": role}


def node(
    nid: str,
    domain: str,
    quantities: dict[str, tuple[float, str]],
    constrains: list[str],
    kind: str = "component",
) -> dict[str, Any]:
    role = OWNER[domain]
    return {
        "id": nid,
        "kind": kind,
        "domain": domain,
        "owner_role": role,
        "quantities": {k: q(v, u, role) for k, (v, u) in quantities.items()},
        "requirements": [],
        "constrains": constrains,
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-09-28T10:00:00Z",
    }


CH = "mechanical.carrier"

# ---------------------------------------------------------------------------------------
# Style S1: written the way the check reads statics. Lateral axis, wheels as two pins.
# Loads 0.30 kg; moments about 0 = 0.01 kg * 0.03 m ... worked out by hand:
#   W = 0.30 * 9.80665 = 2.942 N; sum(W_i x_i) = 9.80665 * 0.0003 = 0.002942 N*m
#   R_R - R_L = 0.002942 / 0.05 = 0.05884; R_R = 1.500, R_L = 1.442 -> 1.50 / 1.44 N
# ---------------------------------------------------------------------------------------


def s1_nodes() -> list[dict[str, Any]]:
    return [
        node(CH, "mechanical", {"mass": (0.34, "kg")}, [], kind="module"),
        node(
            "mechanical.wheel_left",
            "mechanical",
            {"support_position": (-0.05, "m"), "reaction_force": (1.44, "N"), "mass": (0.02, "kg")},
            [CH],
        ),
        node(
            "mechanical.wheel_right",
            "mechanical",
            {"support_position": (0.05, "m"), "reaction_force": (1.50, "N"), "mass": (0.02, "kg")},
            [CH],
        ),
        node(
            "mechanical.frame",
            "mechanical",
            {"mount_position": (0.0, "m"), "mass": (0.10, "kg")},
            [CH],
        ),
        node(
            "electrical.cell_pack",
            "electrical",
            {"mount_position": (0.0, "m"), "mass": (0.15, "kg")},
            [CH],
        ),
        node(
            "electrical.motor_left",
            "electrical",
            {"mount_position": (-0.03, "m"), "mass": (0.01, "kg")},
            [CH],
        ),
        node(
            "electrical.motor_right",
            "electrical",
            {"mount_position": (0.03, "m"), "mass": (0.01, "kg")},
            [CH],
        ),
        node(
            "electrical.board",
            "electrical",
            {"mount_position": (0.01, "m"), "mass": (0.03, "kg")},
            [CH],
        ),
    ]


# ---------------------------------------------------------------------------------------
# Style S2: the same robot written with forces and masses but no positions at all
# (the vocabulary offers positions; nothing in the brief says the check needs them).
# ---------------------------------------------------------------------------------------


def s2_nodes() -> list[dict[str, Any]]:
    out = []
    for n in s1_nodes():
        n = copy.deepcopy(n)
        n["quantities"].pop("support_position", None)
        n["quantities"].pop("mount_position", None)
        out.append(n)
    # Symmetric now, so both reactions are half the carried weight: 1.47 N each.
    for n in out:
        if n["id"].startswith("mechanical.wheel_"):
            n["quantities"]["reaction_force"]["value"] = 1.47
    return out


# ---------------------------------------------------------------------------------------
# Style S3: the axle as a support of the body, written top-down: the structure names
# what holds it (chassis constrains the wheels) rather than the loads naming the structure.
# ---------------------------------------------------------------------------------------


def s3_nodes() -> list[dict[str, Any]]:
    out = copy.deepcopy(s2_nodes())
    for n in out:
        if n["id"] == CH:
            n["constrains"] = ["mechanical.wheel_left", "mechanical.wheel_right"]
        if n["id"].startswith("mechanical.wheel_"):
            n["constrains"] = []
    return out


def by_id(nodes: list[dict[str, Any]], nid: str) -> dict[str, Any]:
    return next(n for n in nodes if n["id"] == nid)


def setq(
    nodes: list[dict[str, Any]], nid: str, name: str, value: float, unit: str | None = None
) -> dict[str, Any]:
    n = copy.deepcopy(by_id(nodes, nid))
    if name in n["quantities"]:
        n["quantities"][name]["value"] = value
        if unit:
            n["quantities"][name]["unit"] = unit
    else:
        n["quantities"][name] = q(value, unit or "N", n["owner_role"])
    return n


def repro_cases() -> list[tuple[str, list[dict[str, Any]], list[dict[str, Any]] | None, str]]:
    s1, s2, s3 = s1_nodes(), s2_nodes(), s3_nodes()
    out: list[tuple[str, list[dict[str, Any]], list[dict[str, Any]] | None, str]] = []
    # --- S1 baseline and clean revision -------------------------------------------------
    out.append(("s1_base", s1, None, "S1 base alone"))
    clean = [setq(s1, "electrical.board", "mass", 0.03)]  # identical numbers: a re-save
    out.append(("s1_clean_resave", s1, clean, "S1 clean re-save of the board"))
    # A correct revision: battery 0.15 -> 0.20 kg at x=0, chassis 0.39 kg, reactions +0.245 N each
    out.append(
        (
            "s1_clean_heavier_battery",
            s1,
            [
                setq(s1, "electrical.cell_pack", "mass", 0.20),
                setq(s1, CH, "mass", 0.39),
                setq(s1, "mechanical.wheel_left", "reaction_force", 1.69),
                setq(s1, "mechanical.wheel_right", "reaction_force", 1.75),
            ],
            "S1 correct heavier battery, everything re-derived",
        )
    )
    # --- S1 errors in quantities the check reads ----------------------------------------
    out.append(
        (
            "s1_e1_mass_up_reactions_stale",
            s1,
            [
                setq(s1, "electrical.cell_pack", "mass", 0.25),
                setq(s1, CH, "mass", 0.44),
            ],
            "battery mass raised, module total updated, reactions left",
        )
    )
    out.append(
        (
            "s1_e2_reaction_off",
            s1,
            [setq(s1, "mechanical.wheel_right", "reaction_force", 1.80)],
            "one reaction raised",
        )
    )
    out.append(
        (
            "s1_e3_load_moved",
            s1,
            [setq(s1, "electrical.board", "mount_position", 0.04)],
            "board moved off-centre, reactions left",
        )
    )
    out.append(
        (
            "s1_e4_support_moved",
            s1,
            [setq(s1, "mechanical.wheel_right", "support_position", 0.08)],
            "right wheel moved outward, reactions left",
        )
    )
    out.append(
        (
            "s1_e5_reactions_swapped",
            s1,
            [
                setq(s1, "mechanical.wheel_left", "reaction_force", 1.50),
                setq(s1, "mechanical.wheel_right", "reaction_force", 1.44),
            ],
            "left/right reactions swapped (moment wrong, sum right)",
        )
    )
    out.append(
        (
            "s1_e6_small_0p8pct",
            s1,
            [setq(s1, "mechanical.wheel_right", "reaction_force", 1.512)],
            "reaction off by 0.8 per cent",
        )
    )
    # --- S1 errors in quantities the check does not read --------------------------------
    out.append(
        (
            "s1_e7_load_force_beside_mass",
            s1,
            [
                setq(s1, "electrical.cell_pack", "load_force", 3.0, "N"),
            ],
            "battery given an extra 3 N load_force beside its mass",
        )
    )
    out.append(
        (
            "s1_e8_mass_in_grams_as_new_name",
            s1,
            [
                setq(s1, "electrical.board", "payload_mass", 0.5, "kg"),
            ],
            "board given an uncatalogued payload mass",
        )
    )
    # --- S2: forces and masses, no positions --------------------------------------------
    out.append(("s2_base", s2, None, "S2 base alone"))
    out.append(
        (
            "s2_e1_reaction_off",
            s2,
            [setq(s2, "mechanical.wheel_right", "reaction_force", 2.40)],
            "one reaction raised by 0.93 N",
        )
    )
    out.append(
        (
            "s2_e2_mass_up_reactions_stale",
            s2,
            [
                setq(s2, "electrical.cell_pack", "mass", 0.25),
                setq(s2, CH, "mass", 0.44),
            ],
            "battery mass raised, module total updated, reactions left",
        )
    )
    # --- S3: structure names its supports -----------------------------------------------
    out.append(("s3_base", s3, None, "S3 base alone"))
    out.append(
        (
            "s3_e1_reaction_off",
            s3,
            [setq(s3, "mechanical.wheel_right", "reaction_force", 2.40)],
            "one reaction raised by 0.93 N",
        )
    )
    return out


G = 9.80665
B = "mechanical.body"


def _node(
    nid: str,
    domain: str = "electrical",
    kind: str = "component",
    q: dict[str, tuple[float, str]] | None = None,
    constrains: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "id": nid,
        "kind": kind,
        "domain": domain,
        "owner_role": domain,
        "quantities": {
            k: {"value": v, "unit": u, "source": "datasheet", "written_by": domain}
            for k, (v, u) in (q or {}).items()
        },
        "requirements": [],
        "constrains": list(constrains),
        "model": None,
        "geometry_hash": "sha256:" + "0" * 64,
        "updated": "2026-10-18T12:00:00Z",
    }


def _body(kg: float, kind: str = "module") -> dict[str, Any]:
    return _node(B, "mechanical", kind, {"mass": (kg, "kg")})


def _wheel(
    side: str,
    f: float,
    x: float | None = None,
    kg: float | None = 0.02,
    cons: tuple[str, ...] = (B,),
) -> dict[str, Any]:
    q: dict[str, tuple[float, str]] = {"reaction_force": (f, "N")}
    if kg is not None:
        q["mass"] = (kg, "kg")
    if x is not None:
        q["support_position"] = (x, "m")
    return _node(f"mechanical.wheel_{side}", "mechanical", "component", q, cons)


def _part(
    name: str,
    kg: float | None = None,
    x: float | None = None,
    lf: tuple[float, str] | None = None,
    cons: tuple[str, ...] = (B,),
    dom: str = "electrical",
) -> dict[str, Any]:
    q: dict[str, tuple[float, str]] = {}
    if kg is not None:
        q["mass"] = (kg, "kg")
    if x is not None:
        q["mount_position"] = (x, "m")
    if lf is not None:
        q["load_force"] = lf
    return _node(f"{dom}.{name}", dom, "component", q, cons)


def probe_cases() -> list[tuple[str, list[dict[str, Any]]]]:
    """The probe shapes, by name."""
    unpl = [_part("frame", 0.10), _part("board", 0.05)]
    pl = [_part("frame", 0.10, 0.0), _part("board", 0.05, 0.0)]
    c: dict[str, list[dict[str, Any]]] = {}
    for tag, lf in [
        ("kg", (3.0, "kg")),
        ("degC", (3.0, "degC")),
        ("bogus", (3.0, "flibbet")),
        ("Nm", (3.0, "N*m")),
        ("ok3N", (3.0, "N")),
    ]:
        c[f"L1_pos_fail_mixed_lf_{tag}"] = [
            _body(0.34),
            _wheel("left", 1.47, -0.05),
            _wheel("right", 2.40, 0.05),
            _part("cell_pack", 0.15, 0.0, lf),
            *pl,
        ]
        c[f"L1_nopos_fail_mixed_lf_{tag}"] = [
            _body(0.34),
            _wheel("left", 1.47),
            _wheel("right", 2.40),
            _part("cell_pack", 0.15, None, lf),
            *unpl,
        ]
    c["L1_pos_fail_stray_badunit"] = [
        _body(0.34),
        _wheel("left", 1.47, -0.05),
        _wheel("right", 2.40, 0.05),
        _part("cell_pack", 0.15, 0.0),
        *pl,
        _node("mechanical.prop", "mechanical", "component", {"reaction_force": (1.0, "kg")}, (B,)),
    ]
    w_old = round(0.15 * G, 3)
    c["L2_nopos_mass_up_stale_lf"] = [
        _body(0.44),
        _wheel("left", 1.47),
        _wheel("right", 1.47),
        _part("cell_pack", 0.25, None, (w_old, "N")),
        *unpl,
    ]
    c["L2_pos_mass_up_stale_lf"] = [
        _body(0.44),
        _wheel("left", 1.47, -0.05),
        _wheel("right", 1.47, 0.05),
        _part("cell_pack", 0.25, 0.0, (w_old, "N")),
        *pl,
    ]
    c["L2b_nopos_reaction_up_wheel_mass_matches"] = [
        _body(0.30 + 2 * 0.0474),
        _wheel("left", 1.47, kg=0.0474),
        _wheel("right", 1.47 + 0.93, kg=0.0474),
        _part("cell_pack", 0.15),
        *unpl,
    ]
    big = 200.0
    ball = round(big / G, 4)
    c["L3_nopos_dummy_pair"] = [
        _body(0.34 + ball),
        _wheel("left", 1.47),
        _wheel("right", 2.40),
        _part("cell_pack", 0.15),
        *unpl,
        _wheel("rest", big, kg=None),
        _part("ballast", ball, dom="mechanical"),
    ]
    c["L3_pos_dummy_pair"] = [
        _body(0.34 + ball),
        _wheel("left", 1.47, -0.05),
        _wheel("right", 2.40, 0.05),
        _part("cell_pack", 0.15, 0.0),
        *pl,
        _wheel("rest", big, 0.0, kg=None),
        _part("ballast", ball, 0.0, dom="mechanical"),
    ]
    c["L4_nopos_plus_minus_pair"] = [
        _body(0.34),
        _wheel("left", 1.47),
        _wheel("right", 2.40),
        _part("cell_pack", 0.15),
        *unpl,
        _wheel("up", big, kg=None),
        _wheel("down", -big, kg=None),
    ]
    r = round((0.30 + 0.04) * G / 2, 4)
    c["C1_pos_reactions_include_wheel_weight"] = [
        _body(0.34),
        _wheel("left", r, -0.05),
        _wheel("right", r, 0.05),
        _part("cell_pack", 0.15, 0.0),
        *pl,
    ]
    c["C1_nopos_reactions_include_wheel_weight"] = [
        _body(0.34),
        _wheel("left", r),
        _wheel("right", r),
        _part("cell_pack", 0.15),
        *unpl,
    ]
    c["FP1_nopos_subassembly"] = [
        _body(0.39),
        _wheel("left", 1.716),
        _wheel("right", 1.716),
        _part("bracket", 0.05, dom="mechanical"),
        _part("cell_pack", 0.15, cons=("mechanical.bracket",)),
        *unpl,
    ]
    c["FP3_nopos_reactions_negative"] = [
        _body(0.34),
        _wheel("left", -1.47),
        _wheel("right", -1.47),
        _part("cell_pack", 0.15),
        *unpl,
    ]
    c["FP6_nopos_bumper_sideways"] = [
        _body(0.36),
        _wheel("left", 1.47),
        _wheel("right", 1.47),
        _part("cell_pack", 0.15),
        *unpl,
        _node(
            "mechanical.bumper",
            "mechanical",
            "component",
            {"reaction_force": (5.0, "N"), "mass": (0.02, "kg")},
            (B,),
        ),
    ]
    c["FP7_nopos_wheel_names_motor"] = [
        _body(0.34),
        _wheel("left", 1.47, cons=(B, "electrical.motor_left")),
        _wheel("right", 2.40),
        _part("cell_pack", 0.15),
        *unpl,
        _part("motor_left", 0.03, cons=()),
    ]
    # Two standoffs whose reactions sum to the load but are split the wrong way round.
    c["SPLIT_two_standoffs_wrong_way_round"] = [
        _body(0.0),
        _wheel("a", 9.806, 0.0, kg=None),
        _wheel("b", 9.807, 0.2, kg=None),
        _part("pcb", 2.0, 0.05),
    ]
    return [(f"probe:{k}", v) for k, v in c.items()]


def handmade() -> list[tuple[str, list[dict[str, Any]]]]:
    """Every hand-made graph, each revision written over its base."""
    found = []
    for name, base, patch, _ in repro_cases():
        merged = {n["id"]: n for n in base}
        for n in patch or []:
            merged[n["id"]] = n
        found.append((f"handmade:{name}", list(merged.values())))
    return found + probe_cases()
