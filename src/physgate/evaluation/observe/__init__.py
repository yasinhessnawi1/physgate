"""Run observability and reproducibility: every number a run produces, with its provenance.

A read-and-record layer over run directories. Nothing here writes into a run: the
manifest, the traces, the sequences and the variance are all read from the files
the orchestrator wrote. The one file this package writes is the cost trend, which
belongs to no single run. ``README.md`` in this directory lists each format and the
one reader every consumer, the command included, goes through.
"""
