# Run 4's nodes, as data

The design-state nodes of G11 run 4 (03.11.2026, the reference brief `briefs/balboa-32u4.md`), copied
unchanged as test fixtures and nothing else:

- `plan_interfaces.json`: the three interface nodes the run's decomposition wrote (journal revisions 1
  to 3);
- `sizing.drivetrain_result.json`: sizing's node as its opening pass proposed it at its merged attempt.
- `values.json`: every value the run wrote, one row per distinct node, name, value and unit across its
  124 node files (203 rows, 174 names), kept as name, value and unit only. The catalogue-widening rows
  (M-198) hold the gate to all of them; this file has no node id and no path.

No trajectory, stream, review text or session id is here. The rows that read them hold the gate to what
a real plan wrote: on these nodes, before M-196's fix, the magnitude and power checks judged nothing.
