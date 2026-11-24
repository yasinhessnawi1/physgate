"""One drawing made from one part, checked, and stale when the part changes (ARCH-110, ARCH-111).

A slice that is shown, not measured. From a part as the tool environment's geometry helper
records it (its ``<part>.result.json`` and the STEP file that record names), the CAD kernel's own
hidden-line projection gives the standard views; they are placed on one sheet as SVG with the
overall dimensions and a title block carrying the part's name, the units, the scale and the
part's ``geometry_hash``, and a record is written beside it. A checker with no kernel reads the
drawing, its record and projection, and the part's record, and gives a verdict per check; it
redraws nothing, and its help says what that leaves uncaught. When the part's hash
is no longer the one the drawing was made from, the drawing reads stale. A drawing is made again
from the part, never patched (ARCH-111).

- :mod:`.record`: the part's record as read here, the projection and the drawing's record.
- :mod:`.kernel`: the two scripts run on the tool environment's interpreter.
- :mod:`.sheet`: the SVG and the record composed from the projection.
- :mod:`.check`: the checker's rules.
- :mod:`.cli`: ``physgate drawing example-part``, ``make`` and ``check``.

Deliberately not here: STEP AP242 with product manufacturing information, ISO 286 fits,
geometric tolerances and datums, the assembly manual, a PDF, and the person's sign-off through
the approval queue that ARCH-110 asks before a drawing is released. Nothing here claims a
drawing is fit to manufacture from, and no model is called.
"""
