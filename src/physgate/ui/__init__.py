"""The operator UI's server: a loopback-only view of runs and the design graph, and one action.

It owns the route table, the allowlist of readable roots, the per-request guard, and serving
the built app. It owns no reader of any record format: every response is built by the same
functions the command line uses, and a gap in one of those is fixed where it lives, not worked
around here. Its one action, a decision on an approval-queue item, is a call into the queue's
own decision function, the one ``physgate queue resolve`` calls. The app itself lives in the
repository's ``ui`` directory.
"""
