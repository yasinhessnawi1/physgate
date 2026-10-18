"""Engines: the agent harness and model provider a session runs on.

``base`` is the interface every part of the system that runs a session depends on: start a
session, read its stream, take its verdict and its cost, stop it, and say which of the
system's layers hold around it. It names no harness and no vendor. Each harness is a package
beside it that implements the interface; adding a harness or a provider adds a package and
edits nothing in ``base``.
"""
