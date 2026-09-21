"""The design-state graph and the task ledger.

This package owns the durable record of what has been designed: one JSON file
per graph node, an append-only journal that is the authority those files are
derived from, and a separate append-only ledger of dispatched subtasks. See
``README.md`` in this directory for what it deliberately does not own.
"""
