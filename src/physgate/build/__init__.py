"""Buildability: what a design needs before it can be bought and built (ARCH-120, ARCH-121).

Each concern is a package of its own: :mod:`physgate.build.bom` checks the parts to buy against
a price sheet. Nothing here orders, writes into a run, or calls the network.
"""
