"""What the design helper's writer puts in an export, measured: free text is counted against it.

Measured on Linux x86_64 (13.11.2026) from the exports the design helper wrote with build123d
0.13.0 and cadquery-ocp-novtk 8.0.1.1.0, as ``toolenv/pins.json`` pins them: the three chassis
fixtures of the offline proof (a plate, a motor mount, a battery holder) and a probe of the other
kinds of shape a part may have (a sphere, a torus, a cone, a filleted, a chamfered, a lofted, a
splined and a revolved solid, a labelled box, a two-part assembly). Every string, keyword and
enumeration those files hold is here, except the four labels the probe gave its shapes, which a
session chooses. A pin change that makes the writer write other words fails the offline proof's
row that holds the fixtures to no free text, and the words are measured again.

What the fixtures hold, counted as ``exports.FreeText`` counts it: no free text at all. The
ruling's first measure, string bytes outside a STEP header, was 619 bytes in each fixture and up
to 1,003 in the probe (``'2D SPACE'`` once for every curve on a face), so it grows with the shape
and cannot be a budget; the bytes outside the writer's own strings and words do not grow.
"""

from __future__ import annotations

#: Every string the writer gives a STEP file, its header's included, as written between quotes.
STEP_WRITER_STRINGS: frozenset[str] = frozenset(
    {
        "", "1", "2", "2000-01-01T00:00:00", "2;1", "2D SPACE",
        "3D Context with UNIT and UNCERTAINTY", "AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }",
        "Author", "COMPOUND", "Context #1", "Open CASCADE", "Open CASCADE Model",
        "Open CASCADE STEP processor 8.0", "Open CASCADE Shape Model", "Placement",
        "Placement of an item", "Unknown", "automotive_design", "build123d", "confusion accuracy",
        "core data for automotive mechanical design processes", "design",
        "distance_accuracy_value", "international standard", "mechanical", "part",
        "part definition",
    }
)  # fmt: skip

#: Every keyword and enumeration (with its dots) the writer gives a STEP file.
STEP_WRITER_WORDS: frozenset[str] = frozenset(
    {
        ".F.", ".METRE.", ".MILLI.", ".PCURVE_S1.", ".PIECEWISE_BEZIER_KNOTS.", ".RADIAN.",
        ".STERADIAN.", ".T.", ".UNSPECIFIED.",
        "ADVANCED_BREP_SHAPE_REPRESENTATION", "ADVANCED_FACE", "APPLICATION_CONTEXT",
        "APPLICATION_PROTOCOL_DEFINITION", "AXIS2_PLACEMENT_2D", "AXIS2_PLACEMENT_3D",
        "B_SPLINE_CURVE_WITH_KNOTS", "B_SPLINE_SURFACE_WITH_KNOTS", "CARTESIAN_POINT", "CIRCLE",
        "CLOSED_SHELL", "CONICAL_SURFACE", "CONTEXT_DEPENDENT_SHAPE_REPRESENTATION",
        "CYLINDRICAL_SURFACE", "DATA", "DEFINITIONAL_REPRESENTATION", "DIRECTION", "EDGE_CURVE",
        "EDGE_LOOP", "END", "ENDSEC", "FACE_BOUND", "FILE_DESCRIPTION", "FILE_NAME",
        "FILE_SCHEMA", "GEOMETRIC_REPRESENTATION_CONTEXT", "GLOBAL_UNCERTAINTY_ASSIGNED_CONTEXT",
        "GLOBAL_UNIT_ASSIGNED_CONTEXT", "HEADER", "ISO", "ITEM_DEFINED_TRANSFORMATION",
        "LENGTH_MEASURE", "LENGTH_UNIT", "LINE", "MANIFOLD_SOLID_BREP", "NAMED_UNIT",
        "NEXT_ASSEMBLY_USAGE_OCCURRENCE", "ORIENTED_EDGE", "PARAMETRIC_REPRESENTATION_CONTEXT",
        "PCURVE", "PLANE", "PLANE_ANGLE_UNIT", "PRODUCT", "PRODUCT_CONTEXT", "PRODUCT_DEFINITION",
        "PRODUCT_DEFINITION_CONTEXT", "PRODUCT_DEFINITION_FORMATION", "PRODUCT_DEFINITION_SHAPE",
        "PRODUCT_RELATED_PRODUCT_CATEGORY", "REPRESENTATION_CONTEXT",
        "REPRESENTATION_RELATIONSHIP", "REPRESENTATION_RELATIONSHIP_WITH_TRANSFORMATION",
        "SEAM_CURVE", "SHAPE_DEFINITION_REPRESENTATION", "SHAPE_REPRESENTATION",
        "SHAPE_REPRESENTATION_RELATIONSHIP", "SI_UNIT", "SOLID_ANGLE_UNIT", "SPHERICAL_SURFACE",
        "SURFACE_CURVE", "SURFACE_OF_LINEAR_EXTRUSION", "TOROIDAL_SURFACE",
        "UNCERTAINTY_MEASURE_WITH_UNIT", "VECTOR", "VERTEX_LOOP", "VERTEX_POINT",
    }
)  # fmt: skip

#: The header the writer gives every binary STL file: its text, then zeros to 80 bytes. The
#: same in all thirteen measured; no other header was seen, so no other is the writer's.
STL_WRITER_HEADERS: frozenset[bytes] = frozenset(
    {b"STL Exported by Open CASCADE Technology [dev.opencascade.org]".ljust(80, b"\0")}
)

#: The most free text any of the three chassis fixtures' exports holds, in bytes.
FIXTURES_FREE_TEXT = 0
#: The stated margin: one label as long as the design helper's part names may be (64
#: characters), so a part a session names is still shown as one line.
FREE_TEXT_MARGIN = 64
#: The most free text an export may hold and still be shown to its reviewer as one line.
FREE_TEXT_BUDGET = FIXTURES_FREE_TEXT + FREE_TEXT_MARGIN
