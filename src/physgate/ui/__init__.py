"""The operator UI's server: a read-only, loopback-only view of runs and the design graph.

It owns the route table, the allowlist of readable roots, the per-request guard,
and serving the built app. It owns no reader of any record format: every
response is built by the same functions the command line uses, and a gap in one
of those is fixed where it lives, not worked around here. The app itself lives
in the repository's ``ui`` directory.
"""
