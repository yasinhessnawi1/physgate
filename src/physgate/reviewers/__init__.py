"""Paired reviewers: one per producing role, on a different model, reading the whole trajectory.

A reviewer judges an attempt the physics gate has already let through (ARCH-031),
against its role's rubric (ARCH-062), from everything the implementing session did
(ARCH-060). This package owns where a review is read from, what it is shown, and
the verdict's shape. It does not own when a review runs or what follows from it:
that is the loop's, in code.
"""
