# Run 4's nodes, as data

The design-state nodes of the fourth slice run on the reference brief (03.11.2026,
`briefs/balboa-32u4.md`), copied unchanged as test fixtures and nothing else:

- `plan_interfaces.json`: the three interface nodes the run's decomposition wrote (journal revisions 1
  to 3);
- `sizing.drivetrain_result.json`: sizing's node as its opening pass proposed it at its merged attempt.
- `values.json`: every value the run wrote, one row per distinct node, name, value and unit across its
  124 node files (203 rows, 174 names), kept as name, value and unit only. The catalogue-widening rows
  hold the gate to all of them; this file has no node id and no path.

No trajectory, stream, review text or session id is here. The rows that read them hold the gate to what
a real plan wrote: on these nodes, before the gate was made to judge where a real plan writes, the
magnitude and power checks judged nothing.
