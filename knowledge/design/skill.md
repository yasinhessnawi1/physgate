# Design — skill

> Procedures and antipatterns for a plan (the decomposition of a brief into modules, their
> specifications and the interface nodes between them), researched and drafted from published
> sources by an agent and approved by a person before use. Rule numbers (§N) refer to
> `knowledge/design/standards.md`; read `knowledge/cross/standards.md` first.

## Procedure: the trace table

1. Number every requirement the brief states, in its own words: each function, performance figure,
   constraint and named part (§1).
2. For each, list the module criteria, interface quantities or sizing quantities it is allocated to,
   or the reason it is not allocated (recorded in a specification, §1):

   | Brief requirement | Allocated to | Verified by (method, level) | Note |
   |---|---|---|---|
   | e.g. "balances upright on a flat floor" | control criterion 3, firmware criterion 2 | test, system level: integration | system behaviour: in the plan's list for integration (§6) |

3. Read the table back from the other side: each module criterion has a row, or is marked derived
   with its reason (§1).

## Procedure: finding the interfaces

1. Write the modules as rows and columns of a square table; in each cell, what the row's module
   produces that the column's module reads [SEBoK authors, "System Integration", *Guide to the
   Systems Engineering Body of Knowledge*, v. 2.14, 2026, "Use coupling matrix", Table 5].
2. Each non-empty cell is one or more quantities. A quantity two or more domains read is a sizing
   quantity when the run has sizing (§4); every other one goes on an interface node owned by the
   producer, with the consumers named where the plan names them (§3).
3. Give each interface quantity a value, unit, source and writer; a value not yet known is a best
   estimate marked to be resolved, with who resolves it (§8).
4. Reorder the table so that modules that share many cells sit together; a boundary crossed by
   many quantities is a candidate to move (§2).

## Procedure: writing a module specification

1. Purpose, in one or two sentences, and the brief requirements it serves (from the trace table).
2. Inputs: each quantity it reads, by interface or sizing node, never restated with a value of its
   own (§5).
3. Outputs: each quantity it owes, to which node, and who reads it.
4. Fixed choices: parts and values the brief names, each with its source; any fixed method with
   its rationale (§7).
5. Operating conditions: ranges, rates and load cases the module must meet (§11).
6. A heading "Acceptance criteria" with numbered criteria. Each: "The <module> shall <verb>
   <what>, <threshold with unit and tolerance>, verified by <analysis | demonstration |
   inspection | test>." One thought each; no "as appropriate", "etc.", "and/or" (§6, §7).
7. Assumptions and items to be resolved, each with its rationale and who resolves it (§8).
8. Keep it under 32,768 characters and complete without any other module's specification (§9).

## Procedure: checking the plan before it is submitted

1. Every brief requirement has a row; every criterion traces back (§1).
2. Every cell of the interface table is on a node or with sizing (§3, §4).
3. Every number that appears twice has one value and one unit (§5).
4. Every criterion is numbered under its heading, has a threshold, a tolerance and a method, and is
   verifiable at its module's level; system-level requirements are in the plan's list for
   integration with their contributing criteria, where the plan has one (§6, §11).
5. No criterion is looser than the brief requirement it traces to, and none is tighter without a
   reason (§10).
6. Each contradiction in the brief is recorded with how the plan treats it, in the specification
   of the module it concerns (§1, §8).
7. Every quantity has one producer: no two modules owe it, no two interface nodes of different
   owners carry it (§3).

## Antipatterns

- **A requirement of the brief with no home.** Dropped in decomposition, it is never built and
  never checked (§1).
- **A criterion with no parent.** Unrequested work, or a derived requirement whose reason is lost
  (§1).
- **Modules as processing steps.** Splitting by the order things happen exposes every module to
  the others' decisions (§2).
- **A shared quantity in two specifications.** Two copies drift; nobody owns the difference (§4,
  §5).
- **A quantity that crosses a boundary with no interface node.** The consumer reads a number the
  producer never committed to (§3).
- **A different unit for the same value in two places.** The Mars Climate Orbiter's interface
  failed this way (§5).
- **Criteria that cannot fail.** "Works well", "is robust", "as appropriate": nothing a reviewer
  can judge (§6, §7).
- **A system behaviour asked of one module.** A module cannot show what only the assembly does
  (§6).
- **A how where a what is needed.** A method fixed without a reason closes off better designs (§7).
- **An invented number.** A value the brief does not give, stated as if it did, hides an
  assumption (§8).
- **A specification that leans on another.** The implementer reads only its own (§9).
- **A looser criterion than the brief.** Each module passes and the system does not (§10).
- **Operating conditions left out of a specification.** Ariane 501's inertial system was never
  given its trajectory (§11).
