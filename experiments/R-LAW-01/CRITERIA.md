# R-LAW-01 — pre-registration: the ceiling of a deterministic law library for the physics gate

> Git-tracked and public. `ARCH-nnn` and experiment IDs only.

**Status:** frozen and committed before any code of this experiment exists. Three facts are filled
later, each in its own dated commit and before the first coding session of the measured set: the
input digests ("Inputs filled", §2.4), the calibration slice's pair ids ("Slice filled", §6), and the
final coder and adjudicator prompts with their sha256 ("Prompt filled", §6). Every `[FILL AT
FREEZE]` is a fact, never a choice.
**Written:** 22.10.2026 (draft); revised the same day after an adversarial review and its delta review.
**The numbers the owner sets:** approved by the owner on 22.10.2026, every value as suggested, with the
cross-model audit added (§7, §14).
**Cites:** R-PG-02 (`experiments/R-PG-02/`), whose review records are this experiment's input.
Nothing in R-PG-02 is changed, re-scored or re-read beyond the records named in §2.
**Excluded entirely:** R-PG-01 and everything of it, including R-PG-02's run on R-PG-01's corpus
(its old-set arm). No such file is read by any script, session or person in this experiment. The
scripts read only the two corpora and seven runs allowlisted in §2.1, by digest, and refuse anything
else.
**Rule:** nothing in this file may change after the first metric is produced.
- A measurement that turns out to be impossible as specified is recorded in `RESULT.md` as a
  deviation, with its reason, and the decision it feeds is scored as **not taken** rather than
  rewritten (§12 lists the cases fixed now).
- An amendment is a new experiment (`R-LAW-02`) that cites this one.

---

## 1. Question

Of the flaws the reviewers find, **what share could a deterministic, closed-form physical law over
the quantities the design-state nodes hold catch, beyond what the physics gate's seven existing
checks (ARCH-080) already catch?**

- That share is the **ceiling** for a law library added to the physics gate: curated closed-form
  relations between node quantities, checked with units and tolerances, deterministic, with no
  model in the gate (ARCH-004, ARCH-081). A ceiling, because it counts what a perfect library
  could catch on the data the designs actually carry; a built library catches at most that.
- It is measured before the library is built, so that the library's scope and priority follow a
  number fixed in advance.
- **What it is not:** a measurement of a built library, of the gate's catch rate (R-PG-02 measured
  that), or of the reviewers' accuracy. It says nothing about flaws no reviewer found.

## 2. The population

### 2.1 The sources (the allowlist)

Two corpora, both from R-PG-02, both authored from one sourced parts sheet (a labelled stand-in,
never the reference design):

| Corpus | Manifest sha256 | Pairs (injected + twin) | Where |
|---|---|---|---|
| R-PG-02's **practice set** | `ddc255ab538f134c2983edfb71d29cbeba3c0dc3dd23cc01df9415120d9ddfb0` | 20 + 20 | `experiments/R-PG-02/practice/corpus-v1/` |
| R-PG-02's **fresh set** (`fresh-v1`) | `e76a4904e7b42326a85a9a9267973518e6f79b510c8f2b8b3391e8b23d37620c` | 40 + 40 | `corpora/injected-errors/fresh-v1/`, the only path under `corpora/` any script opens |

The two sets have different base designs (11 node ids in common). A flaw is counted per set, so a
condition both bases share counts once in each set.

**Seven review runs, every one with the injected artefacts and the clean twins reviewed:**

| Label | Set | Reviewer | What it is | Commit | Run id |
|---|---|---|---|---|---|
| `practice-0` | practice | paired, configuration F | R-PG-02's first practice run, 18.10.2026 | `82cbf3b` | `practice-it0` |
| `practice-1` | practice | paired | R-PG-02's first calibration round (not kept), 19.10.2026 | `7f39327` | `practice-r1` |
| `practice-2` | practice | paired, configuration K | R-PG-02's second calibration round (the pick), 19.10.2026 | `48929eb` | `practice-r2` |
| `a-fresh` | fresh | paired, K | R-PG-02's arm A, attempt 2, 20.10.2026 | `0936f1f` | `rp2-2-a-fresh` |
| `b-fresh` | fresh | generalist, K | R-PG-02's arm B, attempt 2, 20.10.2026 | `0936f1f` | `rp2-2-b-fresh` |
| `repeat-K` | fresh | paired, K's rubrics | a repeat of arm A after R-PG-02, 22.10.2026 | `eae78c0` | in its `instrument.json` |
| `round-1` | fresh | paired, two rubric rules added | a later calibration round, 22.10.2026 | `8c51f48` | in its `instrument.json` |

All seven used `claude-sonnet-5` as reviewer and seed 11 (practice) or 13 (fresh). A void attempt
of the repeat (stopped at a usage limit, nothing scored) is not a source.

**Files read from each run directory, and nothing else:** `results.jsonl` (each artefact's two
subtask ids), `events.jsonl` (the injected artefacts' review lines), `controls/events.jsonl` (the
twins' review lines) and `instrument.json` (the reviewer kind, and the corpus manifest digest, which
must be one of the two above). Gate lines in these logs are read once, only to check the re-gate
(§5.6).

### 2.2 The unit: the finding line, then the flaw

**The finding line (the unit of extraction).** The records support one structured unit cleanly: a
rubric item that a review marked as failing, with its own evidence text.

- **Which review line:** for each subtask, the **last** `review_ran` or `review_unavailable` line
  in its log, as R-PG-02's frozen tally reads it. A `review_unavailable` line contributes nothing.
- **Which entries of it:** every entry of `result.items` whose `result` is `unmet` (sections 1–3:
  `acceptance_criteria`, `domain_standards`, `antipatterns`) or `confirmed` (section 4,
  `reward_hacking`), plus the entry for `result.failing_item` if that names an item not already
  among them (the prior blind adjudication's rejecting-line rule, §2.3).
- **Its text:** the entry's `evidence`, with every rubric item id of the role's rubric replaced by
  `[rule]` (the prior adjudication's stripping rule).
- **Its id:** lines are numbered `L0001…` in this order: set (practice, fresh), run (as listed in
  §2.1), side (injected, twin), pair id, the entry's position in `result.items`. Every seeded draw
  in this file starts from a list sorted by these ids.
- **Not finding lines,** each counted and reported, never coded: `result.criteria` entries (the
  specification's acceptance criterion, which restates the items and has no item id),
  `result.spec_defects` (claims that the specification lacks an input), `result.indicators` (the
  pre-review scan's indicators, which the reviewer only dispositions), and the free-text
  `result.finding` and `result.subject`.
- **Counted by the drafter on 22.10.2026, to be reproduced exactly (§12):** **993 finding lines**
  from 262 reviews, every one with verdict `fail`.

| Source | Injected side | Twin side | Total |
|---|--:|--:|--:|
| `practice-0` | 159 | 123 | 282 |
| `practice-1` | 71 | 21 | 92 |
| `practice-2` | 67 | 34 | 101 |
| **practice set** | 297 | 178 | **475** |
| `a-fresh` (paired) | 134 | 23 | 157 |
| `b-fresh` (generalist) | 59 | 3 | 62 |
| `repeat-K` | 121 | 34 | 155 |
| `round-1` | 119 | 25 | 144 |
| **fresh set** | 433 | 85 | **518** |
| **All** | 730 | 263 | **993** |

By section: domain standards 494, acceptance criteria (section 1) 258, reward hacking 164,
antipatterns 77.

**The flaw (the unit of counting).** The same defect appears many times: in several runs, on both
the injected artefact and its twin when it lies in what they share, under a section 1 line that
restates a section 2–4 line, and on many pairs when it is a condition of the base design. A flaw is
one defect, counted once. Lines are grouped by a deterministic rule that reads no model output:

- **The locus of a line.** The design pair's quantities are every (node id, quantity name) in its
  base, its clean patch and its injected patch. A line **names** a pair by R-PG-02's frozen rule
  (`names_pair` in its tally): the quantity name as a whole word, and the node id, or the part of
  it after its first dot as a whole word, case-folded. A line's locus is the set of pairs it names;
  it may be empty.
- **Step A, restatements within a review.** A section 1 line with a non-empty locus that shares at
  least one pair with a section 2, 3 or 4 line of **the same review** joins that line's flaw: the
  one sharing the most pairs, ties broken by the lower item id in string order.
- **Step B, the same rubric item on the same pair.** The remaining lines are grouped by
  (set, pair, item id), across runs, arms and both sides. Within a group, lines with a non-empty
  locus split into connected components by shared pairs; each component is one flaw. The lines of the
  group with an empty locus together form **one further flaw** of that (set, pair, item); they join no
  component. A group with no located line is therefore one flaw.
- **Step C, the same locus under different items.** Two flaws of the same (set, pair) whose locus
  unions are identical and non-empty are one flaw.
- **Step D, conditions of the base design.** A flaw is a **base flaw** if its locus is non-empty and
  every pair in it carries the base design's value unchanged: the base holds that (node, quantity),
  and neither patch of the pair writes that node with a different value or unit. Within one set, two
  base flaws merge (transitively) when they share a rubric item and at least one locus pair, or when
  their locus unions are identical. A merged base flaw counts once in its set.
- **Counted by the drafter on 22.10.2026, to be reproduced exactly (§12):** 214 of the 258 section 1
  lines are absorbed by step A; 427 flaws after step B; 367 after step C; **348 after step D**
  (practice 187, fresh 161). 36 flaws are base flaws; they merge into 17, of which 8 span more than
  one pair and the largest spans 3.
- **How the rule was chosen, disclosed:** before this file, its variants were counted on the real
  lines by script (counts only, no text read): a union over any shared pair (213 flaws), one flaw per
  (set, pair, item) (391), an earlier form of step B in which empty-locus lines joined the largest
  component (313, then 294 with step D), and the steps above. The drafting scripts are archived
  privately with their digests. The rule was chosen for what it merges, not for any share, since no
  code existed.
- **Its limits:** it under-merges one defect described with no shared pair under two items, and
  over-merges two defects one rubric item describes on overlapping quantities. Step D misses a base
  condition whose line also names a quantity a patch rewrote. Two of §8.3's readings test the unit.

### 2.3 Real findings only

A flaw counts only if it is **real**: the design as revised really has the defect. Every finding
line of the measured set (§6 removes the calibration slice) gets one reality verdict, `true_flaw`,
`not_a_flaw` or `undecidable`, from **one source**: an adjudication run under this file that extends
the prior blind adjudication of 21.10.2026 to every line.

- **The prior adjudication** judged 51 lines of the `a-fresh` and `b-fresh` runs (26 on 7 twins: 25
  `true_flaw`, 1 `undecidable`; 25 on their injected artefacts: 22 `true_flaw`, 3 `not_a_flaw`). Its
  verdicts are **not imported**: those 51 lines are adjudicated again with the rest, and the agreement
  between the two verdicts on each is reported (§8.2). No other adjudication made before or after the
  freeze is imported.
- **The extension**, in everything but its packets' scope the prior adjudication unchanged:
  - **the same system prompt and output schema, verbatim** (Appendix E; sha256 of the prompt's UTF-8
    bytes `41438ab78097d57a6e986b24f4f8071516fa36c1f0393f408874cd81adb23913`, of the schema as
    `json.dumps` writes it `57c3852f8aa0adf9450de3504509b0bf95f85e78c55ff77b199a9c0998172324`); the
    model `claude-opus-5-5`, effort high, no tools, no settings, no MCP, no session persistence, an
    empty working directory;
  - **one packet per design version** (a set, a pair, a side), pooling the lines of every run on that
    version, at most **12** per packet; lines are shuffled with `random.Random(37)` from line-id order
    and cut into consecutive packets; labelled F1…Fn; each packet holds the base design's nodes, the
    nodes the revision wrote, **the full parts sheet** (§2.5) and the findings, as the prior packets
    did except for the sheet, which the prior packets rendered from a lossy copy;
  - **a changed pair** of a design pair is a (node, quantity) whose value or unit differs between its
    clean and injected patches, or that one patch has and the other lacks; for a propagation item,
    every (node, quantity) of the injected edge's two end nodes;
  - **the injected versions are adjudicated first**, then the twin versions and the controls;
  - **a calibration control:** an injected design version is *calibrated* if at least one of its lines
    whose locus holds a changed pair is `true_flaw` with origin `introduced` or `both`. Bar: at least
    **70 %** of the injected versions holding such a line are calibrated (the prior run's bar, 5 of 7);
  - **a rejection control,** drawn after the injected versions' verdicts exist: the eligible lines
    are injected-side lines judged `true_flaw` with origin `introduced` **whose every locus pair is a
    changed pair**. For each injected version holding one, one is drawn (`random.Random(43)`, line-id
    order) and placed **in a packet of its own**, built for the **clean twin** of that pair (its
    base, its clean patch, the full parts sheet), with that single finding. The correct verdict is
    `not_a_flaw`, since the twin lacks the injected change. Bar: at least **70 %** of control lines
    come back `not_a_flaw`. Control verdicts are never reality verdicts;
  - **reliable** only if both bars are met.
- **From lines to flaws.** A flaw is **real** if at least one of its lines is `true_flaw`; **not real**
  if every line is `not_a_flaw`; **undecided** otherwise. Only real flaws enter the denominator; a real
  flaw's code is formed from its `true_flaw` lines only (§5.7).
- **If the extension is not reliable,** the primary reading presumes every line real, and `RESULT.md`
  says so beside the headline.

### 2.4 What is copied, and when

At "Inputs filled", before any script reads a finding line, `experiments/R-LAW-01/inputs/` records the
sha256 of every file of §2.1 (seven runs × four files), of both manifests (checked against §2.1), and
of the prior adjudication's output (read only for the agreement report). The scripts refuse any input
whose digest differs.

### 2.5 The full parts sheet

- **What the reviewers saw was incomplete.** The instrument handed every reviewer the corpus's
  `sources.json` as its parts sheet. In it, **62 of 163 rows have no value** (every row whose value in
  the authors' sheet is a range, a list, a min/typ/max triple or text), and **no row carries the notes
  column**. The authors wrote against the full sheet; the reviewers of all seven runs, and the prior
  adjudication's packets, saw the lossy copy. A code-level verification of this defect was running at
  the freeze; its outcome is reported in `RESULT.md`.
- **What this experiment shows instead:** the corpus's **`parts_sheet.md`**, verbatim, every row and the
  notes, sha256 `29f9568ce8465112ef0b0b164f05f3ba76f9702e3ccbc7a1dea96fbc3d057b3f`, identical in the
  practice set and the fresh set. It is in every reality packet (§2.3), every coder, adjudicator and audit
  packet (§4, §7), and the verification script (§5.5) refuses any session whose packet does not carry it
  at that digest.
- **Findings made against the incomplete sheet** are handled by reality, not by a rule of their own (§9,
  threat 10).

## 3. What each of the seven gate checks does today

**The gate under this experiment:** `src/physgate/gate/`, git tree
**`1e169aac5679d743d4b0585090a45bcd06ea1a63`**, the tree R-PG-02 froze and unchanged at `1a7bb0d`
(22.10.2026); its bounds tables `knowledge/electrical/bounds.toml` (blob `3bbdc33b…`) and
`knowledge/cross/bounds.toml` (blob `b68fd58f…`); the unit-spelling module (blob `eaa4ce69…`); the
catalogue digest `9bf73a7dfd74f49fc0b094a45df9564fdff5de129e170d06ce8d54851a841c88`. The re-gate script refuses any other.

ARCH-080 describes the seven checks; the code is narrower in places. Both are written down, because
G is judged against the code (§5.6) and the gap is reported (§9, threat 3).

**The rounding rule** (`tolerances.py`): an **equality** between separately declared numbers holds if
its residual is at most **0.5 % of the sum of the magnitudes of its terms** (each term taken as true to
three significant figures). **Inequalities get no allowance.**

| # | Check | ARCH-080 describes | As implemented at the tree above |
|---|---|---|---|
| 1 | Units | `pint`; the offending expression and both unit sides | Every unit parses (a bounded spelling first). A catalogued name must meet its kind: dimension, the radian's power, a torque's force × length shape, absolute temperatures only as absolutes, and sign: **power and mass at least 0, energy and thermal resistance above 0**; other kinds carry no sign rule. An uncatalogued name ending in `_voltage`, `_mass`, `_force`, `_torque`, `_frequency`, `_diameter`, `_radius` or `_thickness` has its unit and sign read against that suffix's kind, and a mismatch is recorded `unchecked`, never refused; any other uncatalogued name is `unchecked`. Each relation below must have comparable units on both sides. **It judges dimension and sign, never scale.** |
| 2 | Magnitude | a bounds table in a skill file | Each catalogued quantity is compared exactly with a sourced range for its name in the writer's domain, else an envelope for its kind. **The table holds one range** (electrical `sample_rate`, 0.78 Hz to 32 kHz) **and no envelope**; everything else is `unchecked`. |
| 3 | Static equilibrium and load path | closed form and CalculiX | Closed form only. **Positioned mounts** (a node others constrain as supports, with `support_position` and `reaction_force`, plus `reaction_moment` if fixed, and as loads, with `mount_position` and `mass` at standard gravity or `load_force`): force and moment balance, each declared force, weight and moment allowed to move within its own rounding, positions exact. **Instability,** on this path only: supports that are all pins at one position, with no fixed support, under a net load moment about that position, are refused. A determinate mount is also solved and its declared reactions compared. An **indeterminate** mount is refused if its sums miss and recorded **`unchecked`** if they balance (the split needs finite elements). **Forces only,** for a node of domain `mechanical` whose members declare reactions and no positions: the vertical sum under several readings, refused only if every reading misses. **Torque unit:** `reaction_moment` against `torque_peak` on one node, with gear-ratio readings. **Carrier:** `supported_mass` against the masses of the parts that name it. |
| 4 | Power balance | `sympy` and graph arithmetic | Exact, no allowance. **Power budget:** for a node with `power_supply`, or a module with consumers, the `power_draw` of the nodes constraining it ≤ its `power_supply`. **Sources:** a node with `power_supply` that declares `energy_capacity` or `rated_output_power` is a declared source, and its supply ≤ its rating (`max_discharge_power`, or `rated_output_power`) plus its own `power_draw`; a source without its rating is `unchecked`. A node with `power_supply` that declares neither must draw from a supply it constrains, declare `power_draw`, and supply ≤ that draw; otherwise it is refused. **Current headroom:** a consumer's `stall_current` ≤ its supply's `current_limit` (read as a peak rating). **Discharge rate:** a store's `max_discharge_power` ≤ its `energy_capacity` × the fastest store-class rate. |
| 5 | Energy and mass conservation | `sympy` | Equalities within the rounding rule. **Mass sum:** for a node of kind `module`, its `mass` = the sum of its members' `mass` (members are the nodes whose `constrains` edges name it). **Energy balance:** for any node declaring `input_power` or `output_power`, `input_power` = `output_power` + `heat_dissipation`; a missing term is `unchecked`. |
| 6 | Thermal budget | graph arithmetic | **Junction limit:** for any node declaring `thermal_resistance` or `max_temperature`, `ambient_temperature` + `thermal_resistance` × `heat_dissipation` ≤ `max_temperature`; a missing term is `unchecked`. **Heat budget:** for **any node** declaring `heat_rejection_capacity`, the `heat_dissipation` of the nodes constraining it ≤ that capacity. Warns at module scope; **fails at the integration call**. |
| 7 | Cross-domain propagation | graph traversal (ARCH-082) | Every node whose quantities changed owes a change to every node its `constrains` edges name, in the same change set or a later one, or that node's `no_change_justified` (recorded `unchecked`). An edge into an interface node or a missing node is `unchecked`. |

Every relation reads quantities **by their catalogue names** and nodes **by their `constrains` edges**.
A quantity under another name, or a relation whose edge is missing, is not formed. **Twelve catalogued
quantities sit in no relation** and are read only by checks 1 and 2: `current_draw`, `supply_voltage`,
`rated_voltage`, `stall_torque`, `no_load_speed`, `thermal_margin`, `loop_gain`, `phase_margin`,
`gain_crossover_frequency`, `delay_margin`, `step_peak`, `bore_diameter`.

## 4. The coders, and who sees what

- **Two blind, independent coders per finding line:** each a `claude-opus-5-5` session, effort high,
  no tools, no settings, no MCP, no session persistence, an empty working directory, a JSON output
  schema, the fixed system prompt of Appendix A. Coder 1 and coder 2 code the same lines in separate
  sessions, in different orders: per design version, lines shuffled from line-id order with
  `random.Random(29)` (coder 1) and `random.Random(31)` (coder 2), then cut into consecutive packets of
  at most **10**.
- **A coder sees** one design version's node data and the finding lines on it, nothing else:
  - the node data: every node of the version (the base with the revision's nodes applied: a written
    node replaces the base node of the same id, or is added), with every field except `updated`, each
    quantity with its `value`, `unit` and `source` but not `written_by`;
  - the findings: each line's text as in §2.2, labelled F1…Fn;
  - **the full parts sheet** (§2.5), so that a `derived:` source and a source lookup can be read.
- **A coder never sees:** the other coder; the arm, run, reviewer kind, role or rubric item id; whether
  the version is an injected artefact or a clean twin, its error class or expected check; any gate
  record; any reality verdict; any review verdict.
- **Disagreements go to a third session,** the adjudicator (Appendix B): same model and settings; per
  design version, the disputed lines shuffled with `random.Random(41)` from line-id order, at most
  **10** per packet, each with the node data and the two coders' forms labelled A and B in an order
  drawn by the same generator, never saying which coder wrote which.
- **The operators are blind too.** Whoever runs the sessions sees only counts of sessions, tokens and
  failures. No script prints a distribution of codes, verdicts or shares before the tally. The
  calibration slice (§6) is the only part of the population a person or agent reads before the tally.

## 5. The coding scheme

### 5.1 The codes

Each coder gives each line **exactly one** of five codes. G is a coder's **claim**, decided in the end
by the gate alone (§5.6).

| Code | Name | Holds when |
|---|---|---|
| **G** | a gate check catches it (claim) | The defect is an instance of a relation or rule one of the seven checks **as implemented** (§3) evaluates, every input it reads is a value on a node of this design under the name the check reads, the edges it needs exist, and on these values the rule is violated. |
| **L** | a closed-form law catches it | Not G, and a **textbook closed-form relation** (§5.2) over quantities that are **values on the nodes of this design**, with a **stated tolerance**, is violated by these values by more than the tolerance. This includes the physics of a gate relation that the gate does not form here because an input is under another name or an edge is missing. |
| **L-if-data** | a law the data could not feed | Such a relation would decide the defect, but at least one quantity it needs is **not a value on any node** of this design under any name. Counted apart, never as L. |
| **D** | deterministic, not a closed-form law over node quantities | Decidable by a fixed procedure of another kind: a **simulation** or model solve; a **table** of admissible values or ranges; a **source** lookup (a value against the document it cites); a **record** check (a field, source, annotation or record that a **written rule requires**, absent or malformed); an iterative **numeric** solution. |
| **N** | not deterministically checkable | Decided only by engineering **judgement** (adequacy, margins no requirement states, choice of part or method), **wording**, **process** (how the revision was made; whether values look chosen to pass a check), or **traceability** (whether a present rationale or reference is convincing or right, or whether a record no written rule requires should exist). |

Each form also records (Appendix A's schema): for G and L, the gate relation it instantiates or
`none`, the relation as an expression, the law's name, its kind (`law` or `limit`), its inputs, the
tolerance, the evaluation, the family (the ARCH-080 check whose purpose the relation falls under, or
`none`), and a **fallback code** (the code the procedure gives if this relation is set aside); for
L-if-data, the relation and what is missing; for D and N, the kind; for every code, a one-sentence
restatement of the defect, `multiple_defects`, and a reason. A line that states more than one defect
also gets, in `further`, a one-sentence restatement and a code for **up to two further defects**:
reported only (§8.2), never verified, never counted in a share.

### 5.2 What counts as a law, and the tolerances

- **A textbook relation** is one stated in a standard undergraduate engineering text as a general
  relation, not as a design guideline. Admissible families, as examples: Ohm's and Kirchhoff's laws,
  electrical power and Joule heating, energy and charge over time, motor torque and back-EMF constants,
  mechanical power, gear and pulley kinematics and the torque bound of a gear train, rolling and
  rotational kinematics, Newton's second law, weight, force and moment balance, stress as force over
  area, the standard closed-form beam deflections, thermal resistance, heat capacity, RC and LC time
  constants and resonance, first- and second-order system relations, the sampling theorem, efficiency
  ≤ 1, conservation of energy and mass, utilisation ≤ 1, rate × size ≤ throughput.
- **A `limit`:** one operating value against one rating or one requirement written in the graph,
  `a <= b` or `a >= b` with a single input on each side and **no numeric coefficient**, so that no
  derating or factor of safety can enter as a number. It passes the **pairing check** (§5.5) or it is
  not L. A **design rule of thumb** (ten times the bandwidth, a derating percentage, a factor of
  safety, a preferred margin band) is not a law; unless its threshold is written in the graph as a
  requirement, it is N (judgement). A `law` relation may hold numeric literals (a 2 in the sampling
  theorem, a 4 in a settling time); `RESULT.md` lists every literal of every L relation, per
  relation, so a rule of thumb passing as a law is visible.
- **Constants and literals:** only the allowlisted constants `pi` and `g_n` (standard gravity,
  9.80665 m/s²) and dimensionless numeric literals. A property a node could hold (a resistance, a
  density, a modulus, an efficiency) is data: absent, the relation is L-if-data, not D. A check whose
  essence is a lookup in a table of admissible values is D (table).
- **Requirement values** are addressed as (node id, `requirements` index): the requirement string must
  contain the number and a unit pint parses, and the form quotes both as they appear.
- **The tolerance classes, each with the comparators it admits:** `rounding`, with `==` only (the
  miss must exceed 0.5 % of the sum of the magnitudes of **every additive term** on both sides, the
  terms being split at the top-level `+` and `-` of each side: the gate's rule); `inequality`, with
  `<=`, `>=`, `<`, `>` only (any violation); `relative`, with `==` only (an idealised relation, a
  stated percentage of **at most 25 %**, the miss measured against the larger side's magnitude). A
  comparator outside its class makes the form invalid. A defect the law could decide only with a wider
  tolerance is not L.
- **Units before evaluation:** every input is converted to SI base units first; temperatures to
  kelvin, an absolute temperature as absolute; a unit spelled `delta_…` (for example `delta_degC`) is a
  temperature difference and converts as a difference.
- **The values must decide it.** L requires that the relation, on this design's values, misses by more
  than the tolerance. Otherwise the law does not catch this defect, and the fallback code applies.

### 5.3 The decision procedure (in order; the first that holds is the code)

0. **Restate the defect.** If the line asserts several, code the one its first sentence asserts, mark
   `multiple_defects`, and give up to two further defects in `further` (reported only).
1. **Is it about numbers?** If the defect is not a disagreement among numeric values of the design, or
   between such a value and a bound, go to step 5.
2. **G:** an instance of a §3 relation or rule, every input under the name the check reads, the edges
   present, violated on these values.
3. **L:** a §5.2 relation over present values, violated beyond a stated tolerance; including a gate
   relation's physics the gate does not form here (name the gate relation). If such a relation would
   decide it but an input is on no node under any name: **L-if-data**.
4. **D:** decidable by a simulation, a table, a source lookup or a numeric solution.
5. **Not about numbers:** a record a written rule requires, absent or malformed → **D** (record).
   Otherwise **N**, with its kind.

**Borderline rules, fixed now:**
- **G before L,** and the name rule: a value present under a name the gate does not read is present;
  the defect is L (with the gate relation named), never L-if-data.
- **L before D.** A scale error is L if a relation over present values exposes it, D (source) if only the
  datasheet does, D (table) if only a plausibility range does.
- **A bound can decide what an equality cannot:** a missing factor that physics bounds (an efficiency
  ≤ 1) still decides a claim that breaks the bound: L, `inequality`.
- **Source, not law:** "this value differs from the datasheet it cites" is D (source); code a law only if
  the line asserts that values disagree with each other.
- **Records:** absent and required by a written rule (the node format's own fields, a requirement in the
  graph, a rule the finding quotes) → D (record); absent with no such rule, or present but unconvincing
  → N (traceability).
- **Propagation:** "a changed node's constrained neighbour was not revisited" is G (check 7) when the
  edge exists; "the neighbour's value is now inconsistent" is coded by the relation that shows it.

### 5.4 Worked examples (invented; none is taken from the data)

1. **G.** Three sensor boards constrain a regulator node; their `power_draw` values sum to 4.10 W and
   the regulator's `power_supply` is 3.50 W. Check 4's power budget, every input under its name, edges
   present, violated → **G**, gate relation `power_budget`.
2. **L, law, rounding.** A heater node holds `supply_voltage` 12.0 V, `resistance` 6.00 Ω and
   `power_draw` 12.0 W. P = V²/R gives 24.0 W → **L**, Joule heating, family 4.
3. **L-if-data.** The same line, but no node holds a resistance under any name; the line cites the
   datasheet for it → **L-if-data**, missing resistance.
4. **L, inequality with an unknown factor.** A gearbox node holds an input torque of 0.100 N·m, a
   `gear_ratio` of 20.0 and an output torque of 3.00 N·m, no efficiency. τ_out ≤ r·τ_in = 2.00 N·m
   for any efficiency ≤ 1 → **L**, `inequality`. Had the output been 1.90 N·m and the line said "too
   high for an 85 % efficiency", deciding needs the efficiency → **L-if-data**.
5. **L, kinematics.** A winch node holds a drum radius of 0.0500 m, a no-load speed of 30.0 rad/s and a
   line speed of 2.00 m/s. v = ωr ≤ 1.50 m/s → **L**, `inequality`.
6. **L, sampling theorem, against N.** A loop node holds a sample rate of 100 Hz and a signal bandwidth
   of 80.0 Hz; the line says the signal aliases: f_s ≥ 2 f_max fails → **L**. "Should be ten times the
   bandwidth", with no such requirement in the graph → **N** (judgement).
7. **D, table.** A wire's gauge cannot carry the 3.00 A it carries: ampacity is a standards table →
   **D** (table). A mass implausible for its part class, with no relation to other values, is also
   **D** (table); it would be G only if check 2's table held a range for it.
8. **D, source.** A capacitor's `capacitance` differs from the datasheet page its source cites → **D**
   (source).
9. **D, simulation, against L.** "The controller would oscillate given the plant's inertia and the
   actuator lag", needing closed-loop poles of a model no single formula gives → **D** (simulation).
   A first-order plant's time constant and a claimed settling time both present, where the line says
   the settling is faster than the loop allows → **L**, `relative`, with its percentage.
10. **N against L, limit.** "Little margin for a heavier payload," no payload requirement in the graph →
    **N** (judgement). A requirement "payload ≥ 0.500 kg" on a node, and a torque and lever-arm
    relation over present values showing 0.400 kg → **L** (`limit`).
11. **D, record, against N.** A quantity with an empty `source` (the node format requires one) → **D**
    (record). "The design note given as source does not justify the value" → **N** (traceability).
12. **G, propagation, against L.** "The battery's capacity changed but the runtime node it constrains was
    not revisited" → **G**, check 7. "The runtime written is inconsistent with the capacity and the
    draw" (t = E/P, all present) → **L**.
13. **L by name.** A module's members hold their masses as `part_mass`; the module's `mass` differs from
    their sum. The gate's mass sum reads only `mass`, so it does not form → **L**, gate relation
    `mass_sum` (the script records it as unformed by name).
14. **N, process.** "The values look chosen to make the checks pass" → **N** (process), unless the line
    also shows a value breaking a law: code the law and mark `multiple_defects`.

### 5.5 Machine verification of every form (before agreement is computed)

A script, not a model, applies these to every coder's and the adjudicator's form:

- **The relation evaluates.** For G and L, `relation` is an expression over the symbols the form's
  `inputs` define, the allowlisted constants and numeric literals, with `+ - * / **`, `sqrt` and one
  comparison (`==`, `<=`, `>=`, `<`, `>`), parsed by a restricted syntax tree. Each input names a
  (node id, quantity name) or a (node id, requirement index) of this design version, and its value and
  unit **must equal the node's**; the script builds the quantities from the node data with pint, not from
  the form, converted as §5.2 says. The two sides must have one dimension. The script computes the miss
  and checks it against the tolerance (§5.2).
- **The pairing check for `limit`:** the §5.2 shape (one input each side, no numeric literal); both
  sides of one dimension; one side a requirement input or a quantity whose name, split on `_` into
  whole tokens, contains one of the tokens `max`, `min`, `rated`, `limit`, `capacity`, `peak` or
  `rating`; the two inputs on **one node or on two nodes joined by one direct `constrains` edge**
  (either direction).
- **Any failure** (unparsed, a symbol not defined, a value or unit that differs from the node, a
  dimension mismatch, a comparator outside its tolerance class, a failed pairing check, a miss within
  the tolerance, a `relative` tolerance above 25 %) means the form is **not G or L**: its
  `fallback_code` is used. An input that is on no node turns the code into **L-if-data**. Each case is
  counted per coder and per kind of failure.
- **L-if-data:** a listed missing quantity that exists on the named node keeps the code and is counted as
  an inconsistent form.
- **Required fields:** a form missing a field its code requires is invalid; the session is retried once,
  and a second invalid form leaves the line without that coder's form.

### 5.6 G is decided by the gate alone

- **The re-gate.** Each design version (base with that side's patch applied) is gated at §3's tree with
  the scopes R-PG-02's instrument used, which end in the **integration call**: there every check runs over
  the whole graph and the thermal budget fails rather than warns, so a module-scope warning is never
  counted as a catch. On the fresh set the records must equal the `a-fresh` run's gate lines byte for byte
  (same tree).
- **The record's nodes and relations.** A record's nodes are its `node`, its `module`, and every string
  value anywhere in its `details` that equals a node id of the version. Its relations are those rows of
  check k in Appendix C any of whose quantity names appears as a whole word in
  `json.dumps(record, sort_keys=True)`; for checks 1, 2 and 7, the check's single row.
- **The match.** A failing record of check k **matches** a line if both hold:
  - some locus pair (n, q) of the line has n among the record's nodes and q in the check's quantity
    set Q_k (Appendix C); for checks 1 and 7, whose set is every catalogued name, q must also appear as
    a whole word in the record's `message`;
  - the **deciding form's** input list is **non-empty**, and its `gate_relation` is one of the record's
    relations **or** every input of that form lies in the quantity set of one of them. (An L-if-data form
    with no present inputs therefore never becomes G.)
- **The deciding form** is the adjudicator's when the line was adjudicated; when the coders agreed, coder
  1's form if it passed §5.5, else coder 2's.
- **A line is G** if its final code (§5.7, rule 1) is G, L or L-if-data and some failing record of its
  version matches it. A D or N line is never turned into G.
- **A coder's G that the gate did not fail** is an L (gap), provided its form passed §5.5; otherwise its
  fallback code.
- **Mechanical fields of every L line** (from the form's inputs and the design data):
  - `relation_origin`: **existing relation the gate did not form** if the form names a gate relation,
    else **new relation**;
  - `unformed_by`: `name` if an input's quantity name is not in that gate relation's quantity set in
    Appendix C, else `edge` if a `constrains` edge it needs is absent, else `formed` (formed, and not
    failed on these values);
  - `joined`: the inputs are on **one node**, on **two nodes joined by one direct `constrains` edge**
    (either direction, as in the pairing check), or **neither**.

### 5.7 From line codes to the final code of a flaw

1. **A line's final code:** the two coders' codes after §5.5 if they agree; the adjudicator's code (after
   §5.5) if they do not; **uncoded** if a coder's form is missing after its retry. Then §5.6 turns it into
   G where the gate matches, and a G the gate did not fail into L (gap).
2. **A flaw's code, by its real lines:** **G** if any line is G; else **L** if any line is L; else
   **L-if-data** if any is; else **D** if any is; else **N**; a flaw whose real lines are all uncoded is
   **uncoded**, which is not L. (The majority rule is a reading, §8.3.)
3. **G's two parts are reported:** caught by the gate where the coders also claimed G, and caught where
   they coded L or L-if-data.

## 6. The calibration slice, and the prompt freeze

- **Drawn before any coding** with `random.Random(23)`: classes sorted by name and pairs by id; in the
  fresh set one pair of each error class (4 pairs); in the practice set two classes drawn with
  `sample(classes, 2)` and one pair from each (2 pairs). Eligible pairs have at least one finding line.
  The six ids are filled at "Slice filled".
- **The slice is removed at the line level:** every line of a slice pair (both sides, every run) is a
  calibration line. Grouping (§2.2) runs on all lines, so its counts stay fixed; a **measured flaw** is a
  flaw with at least one measured line, formed from its measured lines only.
- **Base flaws across the boundary (step D):** every slice pair shares a base with measured pairs of its
  set, so a base flaw can hold lines of both. It stays in the measured set, coded only from its measured
  lines, by sessions that never see the slice; its slice lines are calibration lines. The count of such
  flaws is reported, because whoever reads the calibration output has read a version of them.
- **The bank, pre-registered now (Appendix D):** eight candidate rewordings of named sentences of
  Appendix A, and eight invented worked examples, written blind (the drafter read no finding text), each
  tagged with the unordered pair of codes it addresses. Nothing outside the bank can enter the prompt.
- **The choice is mechanical.** Round 1 runs version 0 (Appendices A and B) on the slice: coder 1, coder
  2, the adjudicator and §5.5. A script counts the slice lines on which the two coders' codes (after §5.5)
  form each unordered pair. **A bank item is taken if and only if round 1 has 2 or more such disagreements
  on its pair**; no person or agent chooses. If any item is taken, the result is version 1 and round 2
  runs it; otherwise there is no round 2. **The final prompt is the last version run on the slice.** The
  "Prompt filled" commit records each version's text and sha256, the disagreement counts per pair, and the
  items taken.
- **Reported, never a result:** the slice's κ, its disagreement counts and its L share under each version.

## 7. Agreement, and when the result is unreliable

- **Cohen's κ between coder 1 and coder 2** on the measured lines, on their codes after §5.5 and before
  §5.6, **each line weighted by 1 / (the number of measured lines in its flaw)**, so that every flaw
  weighs one:
  - **κ₅** over the five codes;
  - **κ_L** over {G, L} against the rest, the coders' judgement the primary metric rests on (the split
    between G and L is the gate's).
  - A line missing a coder's form counts in a sixth category, `none`, so it is a disagreement.
  - Each with a 95 % interval by a bootstrap over §8.1's clusters (`random.Random(13)`, 10,000 draws), and
    beside it the unweighted κ, the raw agreement and the prevalence-adjusted κ (PABAK).
- **The floor: weighted κ₅ ≥ 0.60 and weighted κ_L ≥ 0.60** on the point estimates. Set by the owner at
  0.60 (22.10.2026): the lower edge of "substantial" agreement (Landis and Koch, 1977), close to
  Krippendorff's 0.667 for tentative conclusions.
- **Below the floor,** the result is reported as **unreliable, not as a ceiling**: shares are printed as
  descriptive. The floor bites only on the "priority" branch of §10: below it the library stays small and
  targeted whatever the share, which is also what a share below T gives.
- **Reported, never a floor:** κ at the flaw level (each coder's line codes aggregated by §5.7); for each
  coder, the share of G-caught lines it claimed G; §5.5's failures per coder; the adjudicator's choices.
- **The cross-model audit (reported only).** A third coder, `claude-fable-5-1` (a pinned parameter of this
  experiment, recorded per session), with the same settings, the same final prompt, packets and schema,
  and §5.5's checks, codes a seeded **20 %** of the measured coder packets: coder 1's packets, drawn with
  `random.Random(47)` from packet-id order, rounded up. Reported: its weighted κ₅ and κ_L against the
  final line codes (§5.7 rule 1, before §5.6), with intervals, and the L share on that subset by its codes
  and by the final codes. **It never changes a code, a share or the decision.**

## 8. Metrics

### 8.1 Primary

**The share L / (all real flaws)** in the measured set, with its **Wilson 95 %** interval and, beside
it, a **cluster bootstrap** interval (`random.Random(13)`, 10,000 draws), because flaws of one design are
not independent. The clusters are the design pairs, and **each base flaw (step D) is a cluster of its
own**, since it may span pairs; in every breakdown by role or class a base flaw counts under role and
class **"base"**. The denominator is every real flaw: G, L, L-if-data, D, N and uncoded.

### 8.2 Secondary (reported, never scored)

1. Shares of **G** (by its two parts), **L-if-data**, **D** (by kind), **N** (by kind) and uncoded.
2. **L + L-if-data,** the ceiling if the designs carried every quantity the laws need.
3. L split by **`relation_origin`** (new relation, existing relation the gate did not form), by
   **`unformed_by`**, by **`joined`**, by **kind** (`law`, `limit`; the strict-law share is also printed
   beside the decision, §10) and by **law** (a frequency table: what the library would contain).
4. All shares **by role**, **by error class**, **by set**, **by reviewer kind** (a flaw counts under
   each kind that found it), and **by origin**, each with its own cluster bootstrap interval:
   - *on the injection*: a flaw whose locus holds a changed pair (§2.3), **and** that has no twin-side
     line, **and** at least one of whose lines is `true_flaw` with origin `introduced`;
   - *elsewhere*: every other real flaw, base flaws included. A finding unrelated to the planted error
     is a real flaw, and it counts here.
   - The earlier definition (any injected-side line whose locus holds a changed pair) is printed as a
     count for description only.
5. **The false-positive audit:** each L relation of the measured set evaluated, with the same node and
   quantity addresses and tolerance, on every clean twin of its set whose data holds all its inputs; the
   number of twins it would block, per relation and in total. Clean twins can carry real flaws, so a
   block is not proven false; reported only.
6. **Reality:** verdicts per line and flaw, by side; both control bars; agreement with the prior
   adjudication on its 51 lines (by verdict, and Cohen's κ).
7. Counts: `multiple_defects` lines, and the codes of their `further` defects (reported only, never in a
   share); base flaws and how many span slice and measured pairs; the excluded records of §2.2 per run.
8. **The literals of every L relation,** listed per relation (§5.2).

### 8.3 Sensitivity readings (each beside the primary; all six count for "robust")

| # | Reading | What changes | Expected direction on L |
|---|---|---|---|
| S1 | Base flaws once per pair | step D undone (367 flaws before the slice) | towards the inherited conditions' own share; sign not known in advance |
| S2 | Every line its own unit | no grouping (993 lines before the slice) | weights defects found in every run (mostly injected ones); likely up |
| S3 | Majority aggregation | §5.7 rule 2 replaced by the most frequent line code, ties broken N, D, L-if-data, G, L | down or equal |
| S4 | Every line real | reality verdicts ignored | towards the share among not-real findings; small |
| S5 | Strict law | `limit` relations not counted as L | down or equal |
| S6 | Wider base merge | step D merges base flaws of a set on any shared unchanged pair, whatever the item (338 flaws before the slice) | towards the share of the rest; sign not known in advance |

## 9. Threats to validity (stated before the run)

1. **The corpus's injected-error mix.** Every injected error is one of four classes chosen because a
   deterministic check can see them, written by authors who used the gate's vocabulary (R-PG-02, R7 item
   4). Flaws on the injection are over-represented for G and L against real designs. All runs review one
   stand-in design per set and one parts sheet. **Mitigation:** the share *elsewhere* (§8.2 item 4), which
   decides a mix-dependent case (§10).
2. **Coder model bias.** Both coders are one model with one prompt, so their errors correlate and κ is an
   upper bound on independent agreement. A model may lean towards finding a formula. **Mitigation:** every
   L is recomputed by a script from the node data (§5.5); the coders are compared with the gate itself
   (§7); the false-positive audit (§8.2 item 5); and a **cross-model audit** (§7): a third coder on
   `claude-fable-5-1`, reported only. `claude-sonnet-5` is not used for it: it is independent of the
   Opus coders, but it wrote the findings, so it may favour its own.
3. **The checks as implemented against as described.** ARCH-080 describes CalculiX in check 3 and a bounds
   table in check 2; the code runs closed forms and holds one range. G is the code's own verdict (§5.6), so
   a relation ARCH-080 promises but the code lacks lands in L or D. `relation_origin` and the family field
   report how much of L is such a gap.
4. **Only what reviewers found.** A defect no reviewer flagged cannot count, and the rubrics shape what is
   flagged (section 4 items are mostly N by construction; the generalist has no section 2 or 3).
5. **The unit rule.** A deterministic grouping over- and under-merges; step D catches only base conditions
   whose every named quantity is untouched. **Mitigation:** S1, S2 and S6.
6. **The reality verdicts.** One model adjudicates reality and agreed with nearly every finding before.
   **Mitigation:** the rejection control (§2.3) and S4.
7. **Non-independence.** Flaws within one design are correlated. **Mitigation:** cluster bootstrap
   intervals, which decide "resolved" when wider (§10), and flaw-weighted κ.
8. **Exposure before the freeze.** The drafter read the structure of the review records and counted lines
   by script without reading their text. The drafter also read a private diagnosis that describes, in kinds
   and counts, the findings on 11 fresh-set twins, and that reports **counts of rubric item ids cited on
   R-PG-02's old-set twins** (R-PG-01's corpus). It read the key names, and no message, of one failing gate
   record of the `a-fresh` run, to specify the G match. The unit rule was iterated on real-data counts before the
   freeze (§2.2). The worked examples and the bank are invented and avoid the kinds that diagnosis names. The
   agents that made the prior adjudication and the diagnosis read the `a-fresh` and `b-fresh` records in
   full; no person or agent tunes the prompt, since the bank's items are taken by a counting rule (§6).
9. **Practice runs carry tuning.** The practice runs are the rubric calibration's own iterations, one not
   kept. Their findings are real reviewer output; the share by set is reported.
10. **Some findings were made against an incomplete parts sheet** (§2.5). A reviewer who could not see a
    range, a min/typ/max triple or a note may have flagged a value the full sheet supports, or argued from
    memory. Such a finding is a real flaw if the flaw is real given the full sheet; otherwise the reality
    adjudication, which sees the full sheet, rules it `not_a_flaw`, and it leaves the denominator. The
    prior adjudication saw the lossy copy too, which is one more reason its verdicts are not imported and
    its agreement with the extension is reported (§8.2).

## 10. Decision use, fixed now

**The threshold T on the primary share L / (real flaws): 15 %,** set by the owner (22.10.2026).

| Deciding share | What it means for the law library |
|---|---|
| **below T** | **A small, targeted library.** Only the laws that L flaws name, ordered by how many flaws each catches, each drafted from the literature and approved by the owner. Built in its planned place; not moved forward. |
| **T or above** | **A priority.** The library is the gate's next extension, scoped from the law frequency table, with the existing relations the gate did not form fixed first. |

- **The deciding share** is the primary share, unless the decision is **mix-dependent**: the share on the
  injection and the share elsewhere (both after step D) fall on different sides of T. Then the deciding
  share is **the share elsewhere**, because a deployed design carries no injected error.
- **Resolved or not:** the decision follows the deciding share's point estimate. It is **resolved** if the
  **wider** of its Wilson and cluster-bootstrap intervals lies wholly on one side of T, and **not resolved
  at this size** otherwise. It stands either way, labelled.
- **Robust or not:** **robust** if all six readings of §8.3, computed on the deciding share, fall on the
  same side of T; otherwise each reading that crosses is named.
- **Printed beside it:** the strict-law share (S5); beside that, the **count of L flaws whose relation
  has one input on each side and a non-integer literal** (so that a derating labelled as a law shows);
  and L + L-if-data. If L is below T but L + L-if-data
  is T or above, the library's first specification also includes the data side (the role standards require the
  quantities the missing laws need): a scope note, not a change of priority.
- **Below the κ floor** (§7) or under a deviation (§12), no "priority" decision is taken; the library stays
  small and targeted.

**Why 15 %.**
- **Resolution.** About 310 real flaws are expected in the measured set (348 less the slice and the
  not-real ones). At 15 % the Wilson half-width is about ±4 points; the cluster interval will be wider by
  an amount not known before the run, which is why "resolved" uses the wider one.
- **Cost.** Each law costs a literature draft, the owner's approval and a false-positive check on every
  clean design. Below about one flaw in seven, a short list of laws the data already names captures most of
  what there is; above it, a curated library pays for its curation.
- It is a judgement, and is labelled as one.

## 11. What is published

`RESULT.md` cites the freeze commit, the "Inputs filled", "Slice filled" and "Prompt filled" commits, and
the gate tree. It publishes the finding lines (§2.2) with their ids, loci and flaw ids; every coder,
adjudicator and reality form with §5.5's outcome; the re-gate records; the slice, the bank items chosen and
each prompt version; the tally's full output; and every deviation. Session transcripts and account files are
not published.

## 12. Cost, run order and deviations

**Sessions and tokens,** at about **50,000 tokens per session** (high effort, packet and prompt):

| Step | Sessions | Tokens |
|---|--:|--:|
| Re-gate of every design version (no model) | 0 | 0 |
| Calibration, ≤ 2 rounds (≈ 14 packets × 2 coders + ≈ 5 adjudications, per round) | ≤ 66 | ≤ 3.3 M |
| Reality, every measured line (≈ 900 lines, ≤ 12 per packet) | ≈ 100 | ≈ 5 M |
| Rejection controls (one per packet) | ≈ 50 | ≈ 2.5 M |
| Coding, measured set (≈ 126 packets × 2 coders) | ≈ 252 | ≈ 12.6 M |
| Adjudication (≈ 30 % of lines disputed, ≤ 10 per packet) | ≈ 50 | ≈ 2.5 M |
| Cross-model audit (20 % of the measured coder packets, `claude-fable-5-1`) | ≈ 26 | ≈ 1.5–2 M |
| Retries (≈ 10 %) | ≈ 50 | ≈ 2.5 M |
| **Total** | **≈ 590** | **≈ 30–32 M** |

About **6 to 10 hours** of wall clock at four sessions at a time. The sessions run on the development
account, never in the same weekly window as an evaluation run on that account, with a quota ledger line per
step (`tokens_every_try`).

**Run order:**
1. The owner approves this file; it is committed (the freeze). No code exists before it.
2. The scripts of §13 are written and tested on synthetic fixtures (no finding line of §2), and committed.
3. "Inputs filled" (§2.4).
4. Extraction and grouping (no model): **993 lines and 348 flaws** exactly. Then the slice draw; "Slice
   filled".
5. The re-gate (no model), checked against the `a-fresh` gate lines.
6. Calibration round 1 on the slice, the bank rule, round 2 if any item is taken; "Prompt filled".
   **The projection check:** after round 1, *tokens spent so far + the measured tokens per session ×
   the sessions remaining in this table* must be at most 60 M; otherwise the run stops before any
   measured session, as a deviation.
7. Reality (injected versions first, then twin versions, then the rejection controls) and measured
   coding, concurrently (two lanes each); then the adjudication of disagreements; then the cross-model
   audit (§7).
8. The tally: κ and the floor first; then the shares, intervals, readings and the decision. `RESULT.md`.

**Deviations, fixed now (R-PG-02's rule: a deviation scores what it feeds as failed, never rewritten):**
- **Counts:** if extraction does not give 993 lines, or grouping 348 flaws (367 before step D), the run
  **stops before any session**; the cause is recorded as a deviation, the decision is **not taken**, and a
  corrected protocol is a new experiment.
- **The 60 M token guard:** reaching it stops every session; the result is **void**, not partly coded, and
  the decision is not taken. **The projection check** (step 6) failing is a deviation of the same kind,
  before any measured session.
- **The re-gate differs from the `a-fresh` gate lines:** a deviation; G is not decided, and the decision is
  not taken.
- **Anything else impossible as specified** is a deviation of the same kind.

## 13. Reproduction: the scripts (written after the freeze, not before)

All under `experiments/R-LAW-01/`, run with `python -I`, each tested by `test_*.py` on a synthetic fixture.

| Script | What it does |
|---|---|
| `law_extract.py` | Checks every digest of §2.4 against the allowlist and refuses anything else, takes the last review line per subtask, writes `lines.jsonl` (line id, set, pair, side, run, reviewer kind, role, section, item, stripped text, locus), prints the counts of §2.2 per source. |
| `law_group.py` | Steps A to D: writes `flaws.jsonl`, the base-flaw table and the units for S1, S2 and S6; prints counts. |
| `law_slice.py` | Draws the slice (§6); prints the six ids and the slice's line and flaw counts. After round 1, counts the slice disagreements per code pair and applies the bank rule. |
| `law_regate.py` | Applies each patch, runs the gate at the pinned tree (refusing any other tree, blob or catalogue digest), compares the fresh set's records with `a-fresh`'s, and writes each line's gate matches (§5.6). |
| `law_reality.py` | Builds the reality packets with the prior prompt and schema byte for byte, the calibration and rejection controls and their key (never shown to a session); scores verdicts, both bars and the agreement with the prior adjudication. |
| `law_packets.py` | Builds coder and adjudicator packets (§4) and their keys. |
| `law_sessions.sh` | Runs one blind session per packet with the pinned model, settings and schema; retries once on invalid output; logs tokens per try; stops everything at the 60 M guard; computes the projection check after round 1. Prints counts only. |
| `law_verify.py` | Refuses any session whose packet does not carry the full parts sheet at its digest (§2.5). §5.5: parses each relation in a restricted syntax tree, builds the inputs from the node data with pint, checks values, units, dimension, pairing and the miss against the tolerance; applies fallbacks; writes `codes.jsonl`. |
| `law_tally.py` | §5.6, §5.7, §7, §8 and §10: final codes, weighted κ with intervals, the floor, the shares with both intervals, every secondary and reading, the false-positive audit, the decision and its labels. |
| `law_fixture.py`, `test_*.py` | A synthetic design pair, review logs and scripted stand-in sessions; tests for each rule, the allowlist refusal, the relation parser's refusals and the deviation stops. |

## 14. The numbers the owner set (approved 22.10.2026)

| # | Number | Value | Where |
|---|---|---|---|
| 1 | κ floor (weighted κ₅ and κ_L) | 0.60 | §7 |
| 2 | The decision threshold T | 15 % | §10 |
| 3 | The reality bars (calibration, rejection) | 70 % each | §2.3 |
| 4 | The `relative` tolerance ceiling | 25 % | §5.2 |
| 5 | Calibration rounds | at most 2, from the bank only | §6 |
| 6 | Packet caps | reality 12, coder 10, adjudicator 10 | §2.3, §4 |
| 7 | Seeds (`random.Random`, from line-id order) | slice 23; coders 29 and 31; reality packets 37; adjudicator 41; rejection control 43; bootstrap 13, 10,000 draws | §2.3, §4, §6, §7 |
| 8 | Token guard | 60 M, voids the result; a projection check after calibration round 1 | §12 |
| 9 | The cross-model audit | `claude-fable-5-1`, 20 % of the measured coder packets, seed 47, reported only | §7 |

---

## Appendix A. The coder's system prompt (version 0)

```
You are an experienced mechatronics design engineer. You will read the node data of one design
graph and a list of review findings about it, written by reviewers in their own words. Your task
is to classify each finding by the kind of automatic check that could have caught the defect it
states. You do not judge whether the finding is correct, how serious it is, or how well it is
written. You use general engineering knowledge; you do not look anything up.

THE DESIGN DATA
Each node has an id, a kind, a domain, quantities, requirements and edges. Each quantity is
{value, unit, source}. A "constrains" list names the nodes this node constrains. A quantity is
"present" if it appears on a node with a numeric value and a unit, under any name. A requirement
string on a node that contains a number and a unit is a present value, addressed by the node id
and the requirement's index. A value mentioned in a finding but not on a node is not present.

THE FIVE CODES (exactly one per finding)
G  The defect is an instance of a relation or rule one of the gate's seven checks evaluates, as
   listed below; every input it reads is present under the exact name the check reads; the edges
   it needs exist; and on these values the rule is violated.
L  Not G. A textbook closed-form relation over present values, with a stated tolerance, is
   violated by these values by more than the tolerance. This includes a gate relation's physics
   that the gate does not form here because a value is under another name or an edge is missing:
   then name that gate relation.
L-if-data  Such a relation would decide the defect, but a quantity it needs is not present on any
   node under any name.
D  Decidable by a fixed procedure that is not a closed-form relation over node values:
   "simulation" (a model solve), "table" (a table of admissible values or ranges), "source" (a
   value against the document it cites), "record" (a field, source, annotation or record that a
   written rule requires - the node format's own fields, a requirement in the graph, or a rule the
   finding quotes - is absent or malformed), "numeric" (an iterative numeric solution).
N  Decidable only by "judgement" (adequacy, margins no requirement states, choice of part or
   method), "wording", "process" (how the revision was made; whether values look chosen to pass a
   check), or "traceability" (whether a present rationale or reference is convincing or right, or
   whether a record no written rule requires should exist).

WHAT COUNTS AS A LAW
A textbook relation is stated in a standard undergraduate engineering text as a general relation,
not as a design guideline. Examples: Ohm's and Kirchhoff's laws; electrical power and Joule
heating; energy and charge over time; motor torque and back-EMF constants; mechanical power =
torque x angular velocity; gear and pulley kinematics and the torque bound of a gear train;
rolling and rotational kinematics; Newton's second law; weight; force and moment balance; stress =
force / area; standard closed-form beam deflections; thermal resistance; heat capacity; RC and LC
time constants and resonance; first- and second-order system relations; the sampling theorem;
efficiency <= 1; conservation of energy and mass; utilisation <= 1; rate x size <= throughput.
Kind "limit": one operating value against one rating, or one requirement written in the graph,
of the same kind of quantity, written "a <= b" or "a >= b" with one input on each side and no
number in it, on the same node or on two nodes joined by one direct "constrains" edge. Kind "law":
any other relation between quantities; any plain number in it will be listed in the results.
A design rule of thumb (ten times the bandwidth, a derating percentage, a factor of safety, a
preferred margin band) is not a law; unless its threshold is a requirement in the graph, a defect
resting on it is N (judgement).
You may use only these constants: pi, g_n (standard gravity, 9.80665 m/s^2), and plain numbers.
A property a node could hold (a resistance, a density, a modulus, an efficiency) is data: if it is
not present, the relation is L-if-data. A check whose essence is looking a value up in a table of
admissible values is D (table).

TOLERANCE (state one with every G and L)
- "rounding": an equality written with ==; it is violated only if the two sides differ by more
  than 0.5 % of the sum of the magnitudes of every term added or subtracted on either side.
- "inequality": a bound written with <=, >=, < or >, with no allowance.
- "relative": an idealised relation written with ==, with a percentage of at most 25, justified in
  one sentence; the miss is measured against the larger side. If deciding would need more, it is
  not L.
A comparator that does not fit its class makes the form invalid. Values are converted to SI base
units before evaluation (temperatures to kelvin; a "delta_" unit is a difference).
The relation must be violated on this design's values by more than the tolerance. If it is not,
the relation does not catch this defect: use your fallback code.

HOW TO WRITE A RELATION (for G and L; a script will recompute it)
Give each input a short symbol and its node id, quantity name (or requirement index), value and
unit exactly as on the node. Write the relation with those symbols, the constants above, plain
numbers, + - * / **, sqrt, and one comparison (==, <=, >=, <, >), for example
"P_out <= eta_max * P_in" is not allowed (eta_max is not an input) but "T_out <= r * T_in" is.
Give "fallback_code": the code the procedure gives if your relation is set aside.

THE PROCEDURE (in order; the first step that holds gives the code)
0. Restate, in one sentence, the one defect the finding asserts. If it asserts several, take the
   one its first sentence asserts, set multiple_defects to true, and list up to two further defects
   in "further", each with a one-sentence restatement and a code (these are recorded only).
1. If the defect is not a disagreement among numeric values of the design, or between such a value
   and a bound, go to step 5.
2. G: an instance of a check's relation or rule below, every input present under the name the
   check reads, the edges present, violated on these values.
3. L: a textbook relation over present values that these values violate beyond a stated
   tolerance, including a gate relation the gate does not form here. If such a relation would
   decide it but a quantity is present under no name: L-if-data.
4. D: decidable by a simulation, a table, a source lookup or a numeric solution.
5. Not about numbers: a record a written rule requires, absent or malformed, is D (record).
   Otherwise N, with its kind.

BORDERLINE RULES
- G before L. A value present under a name the gate does not read is present: the defect is L,
  naming the gate relation, never L-if-data.
- L before D. A value a thousand times off is L if a relation over present values exposes it, D
  (source) if only its datasheet does, D (table) if only a plausibility range does.
- A bound can decide what an equality cannot: a missing factor that physics bounds (an efficiency
  <= 1) still decides a claim that breaks the bound: L, tolerance "inequality".
- "This value differs from the datasheet it cites" is D (source). Code a law only if the finding
  asserts that the values disagree with each other.
- Records: absent and required by a written rule is D (record); absent with no such rule, or
  present but unconvincing, is N (traceability).
- "A changed node's constrained neighbour was not revisited" is G (check 7) when the edge exists.
  "The neighbour's value is now inconsistent" is coded by the relation that shows it.

FAMILY (for G, L and L-if-data): the check whose described purpose the relation falls under, or
"none": 1 unit consistency; 2 magnitude plausibility; 3 static equilibrium and load path; 4 power
balance, including a component's electrical power relations; 5 energy and mass conservation;
6 thermal budget; 7 cross-domain propagation.

THE GATE'S SEVEN CHECKS, AS IMPLEMENTED
Relations read quantities by these exact names and nodes by their "constrains" edges. A quantity
under another name, or a relation whose edge is missing, is not formed. An equality holds within
0.5 % of the sum of its terms' magnitudes; an inequality gets no allowance.
1 Units (gate relation "units_kind"): every unit parses; a catalogued quantity has its kind's
  dimension and sign (power and mass at least 0; energy and thermal resistance above 0); both
  sides of each relation have comparable units. Never scale.
2 Magnitude ("magnitude_range"): the only range held is electrical "sample_rate", 0.78 Hz to 32 kHz.
3 Equilibrium ("mount_balance", "forces_only", "torque_unit", "carrier"): for a node others
  constrain as supports ("support_position", "reaction_force", "reaction_moment" if fixed) and
  loads ("mount_position", and "mass" at standard gravity or "load_force"): force and moment
  balance; pins all at one position with a net load moment about it are unstable. A mechanical
  node whose members give reactions and no positions: vertical force sum only. "torque_peak"
  against "reaction_moment" on one node (with "gear_ratio" or "external_gear_ratio").
  "supported_mass" against the "mass" of the parts that name the node.
4 Power: "power_budget" - the "power_draw" of the nodes constraining a node <= its "power_supply";
  "source_rating" - a node with "power_supply" and "energy_capacity" supplies <=
  "max_discharge_power" plus its own "power_draw", and one with "rated_output_power" supplies <=
  that plus its "power_draw"; "supply_covered" - any other node with "power_supply" supplies <= its
  own "power_draw" from a supply it constrains; "current_limit" - a consumer's "stall_current" <=
  its supply's "current_limit"; "discharge_rate" - "max_discharge_power" <= "energy_capacity" x the
  fastest store-class rate.
5 Conservation: "mass_sum" - a node of kind module: its "mass" = the sum of the "mass" of the nodes
  constraining it; "energy_balance" - "input_power" = "output_power" + "heat_dissipation".
6 Thermal: "junction_limit" - "ambient_temperature" + "thermal_resistance" x "heat_dissipation" <=
  "max_temperature"; "heat_budget" - the "heat_dissipation" of the nodes constraining a node <= its
  "heat_rejection_capacity".
7 Propagation ("propagation"): when a node's quantities change, every node its "constrains" edges
  name must change too, or say in "no_change_justified" why not.
These catalogued quantities sit in no relation (checks 1 and 2 only); a defect among them is never
G: current_draw, supply_voltage, rated_voltage, stall_torque, no_load_speed, thermal_margin,
loop_gain, phase_margin, gain_crossover_frequency, delay_margin, step_peak, bore_diameter.

WORKED EXAMPLES (invented; not from the findings you will read)
[The fourteen examples of the pre-registration's section 5.4, verbatim, in that order.]

OUTPUT
One form per finding id, in the JSON schema given. G and L: gate_relation (a name above, or
"none"), relation, law, kind, inputs, tolerance (and tolerance_percent for "relative"),
evaluation, family, fallback_code. L-if-data: relation, law, kind, inputs present, missing,
family. D: d_kind. N: n_kind. Every code: defect, multiple_defects, reason (one to three
sentences), and "further" when multiple_defects is true. Use node ids and quantity names exactly as in the design data.
```

**The packet (the user message), per design version:**

```
# Packet <id>

A design graph for a small two-wheeled self-balancing robot (a stand-in design built from a parts
sheet). Each node holds quantities as {value, unit, source}; a source "derived: [R1.02] * [R5.03]"
is arithmetic over the parts-sheet rows it names. Numbers are written to three significant figures.

## Findings (the reviewers' own words; rule numbers are replaced by [rule])

### F1
<text>
...

## The design, all nodes

<JSON, keys sorted: every node, every field but "updated", quantities without "written_by">

## The parts sheet

<the corpus's parts_sheet.md, verbatim, every row and note>
```

**The coder's output schema** (sha256 filled at the prompt freeze): an object with `findings`, an array
of objects with the required fields `id`, `defect`, `code` (enum `G`, `L`, `L-if-data`, `D`, `N`),
`multiple_defects` (boolean) and `reason`, and the optional fields `gate_relation` (enum of the relation
names in Appendix C, or `none`), `relation`, `law`, `kind` (enum `law`, `limit`), `inputs` (array of
{`symbol`, `node`, `quantity` or `requirement` (integer), `value`, `unit`}), `missing` (array of {`node`
or null, `quantity`}), `tolerance` (enum `rounding`, `inequality`, `relative`), `tolerance_percent`
(number), `evaluation`, `family` (integer 1–7 or `none`), `fallback_code` (enum `L-if-data`, `D`, `N`),
`d_kind` (enum `simulation`, `table`, `source`, `record`, `numeric`), `n_kind` (enum `judgement`,
`wording`, `process`, `traceability`), `further` (array of at most 2 {`defect`, `code`}). §5.5 enforces
which optional fields each code requires.

## Appendix B. The adjudicator's system prompt (version 0)

```
You are an experienced mechatronics design engineer settling disagreements between two independent
classifications of review findings about one design graph. For each finding you are given the
design's node data, the finding, and two classification forms, A and B, made by two classifiers
working alone. You do not know who made which form.

Decide the correct code yourself by the procedure below, using the forms only as arguments. You may
choose A's code, B's code, or a third code if both are wrong. Do not split the difference and do not
prefer a form for being longer or more confident. Check each form's claims against the node data: a
quantity a form lists as present must appear on a node with that value and unit; a form's
arithmetic must hold.

[The coder's prompt from "THE DESIGN DATA" to "WORKED EXAMPLES", verbatim.]

OUTPUT
One form per finding id, in the coder's schema, plus "chosen": "A", "B" or "other", and a reason
that names the step of the procedure that decides it.
```

## Appendix C. The gate relations a form may name, and each check's quantity set

| Gate relation | Check | Quantities it reads |
|---|---|---|
| `units_kind` | 1 | every catalogued name, and suffix-kind names |
| `magnitude_range` | 2 | `sample_rate` |
| `mount_balance`, `forces_only` | 3 | `support_position`, `mount_position`, `reaction_force`, `reaction_moment`, `load_force`, `mass` |
| `torque_unit` | 3 | `torque_peak`, `reaction_moment`, `gear_ratio`, `external_gear_ratio` |
| `carrier` | 3 | `supported_mass`, `mass` |
| `power_budget`, `supply_covered`, `source_rating` | 4 | `power_draw`, `power_supply`, `energy_capacity`, `max_discharge_power`, `rated_output_power` |
| `current_limit` | 4 | `stall_current`, `current_limit` |
| `discharge_rate` | 4 | `max_discharge_power`, `energy_capacity` |
| `mass_sum` | 5 | `mass` |
| `energy_balance` | 5 | `input_power`, `output_power`, `heat_dissipation` |
| `junction_limit` | 6 | `ambient_temperature`, `thermal_resistance`, `heat_dissipation`, `max_temperature` |
| `heat_budget` | 6 | `heat_dissipation`, `heat_rejection_capacity` |
| `propagation` | 7 | every catalogued name |

Q_k (§5.6) is the union of the quantities of check k's rows.

## Appendix D. The calibration bank (pre-registered; tuning chooses only from here)

Written blind, before any session: the drafter read no finding text. Each rewording replaces exactly the
named sentence of Appendix A; taken examples are appended after example 14 **in bank order (X1…X8)**.
Neither may be edited. Each item carries, in brackets, the unordered pair of codes it addresses: it is taken
if and only if calibration round 1 has 2 or more slice lines on which the two coders' codes form that pair
(§6). **Disclosed:** the seven items tagged L–N do not lean evenly. Five lean toward L (W1, W8, X1, X7, X8)
and two away from it (W2, X5), so if L–N disagreements reach the bar, the taken items push the prompt
toward L. The L share under each version is reported (§6).

**Rewordings**
- **W1 [L–N]** (step 0, "If it asserts several…"): "If it asserts several, take the one stated with numbers;
  if none or several are, take the one its first sentence asserts; set multiple_defects to true and list
  up to two further defects in 'further'."
- **W2 [L–N]** (step 1): "A defect is about numbers if checking it means comparing a value with a unit against
  another value or a bound. A defect about whether a value is justified, sourced or explained is not
  about numbers."
- **W3 [G–L]** (borderline, "G before L…"): "Code G only when you can name the gate relation and point to each
  of its inputs by the exact name it reads. If an input is under another name, or an edge it needs is
  absent, code L if a relation over present values decides it, and name the gate relation."
- **W4 [L–L-if-data]** (borderline, "A bound can decide…"): "Before choosing L-if-data, ask whether a bound that holds
  whatever the missing value is (an efficiency at most 1, a loss at least 0, a ratio at least 1) already
  decides the claim. If it does, code L with tolerance 'inequality'."
- **W5 [L–D]** (borderline, "This value differs from the datasheet…"): "If the finding's evidence is a document
  (a datasheet, a sheet row, a reference) rather than another value of this design, code D (source)."
- **W6 [L–D]** (tolerance, "relative"): "Use 'relative' only for an idealised law. State the percentage before
  you compute the miss, and give the reason the idealisation needs it."
- **W7 [D–N]** (borderline, "Records…"): "Absent means the field or record is not there at all. If it is absent
  and a written rule requires it, code D (record); in every other case about records, code N
  (traceability)."
- **W8 [L–N]** (kind "limit"): "A limit compares an operating value with a rating or a written requirement of
  the same kind of quantity, on the same part or on a part joined to it by an edge. Anything else is kind
  'law'."

**Examples**
- **X1, L. [L–N]** An indicator node holds a supply of 5.00 V, a forward voltage of 2.00 V, a series resistance
  of 100 Ω and a current of 10.0 mA. I = (5.00 − 2.00) / 100 = 30.0 mA → L (Ohm's law with
  Kirchhoff's voltage law), rounding.
- **X2, L-if-data. [L–L-if-data]** A runtime of 2.00 h is claimed for a pack drawing 5.00 W, and no node holds the
  pack's stored energy under any name → L-if-data.
- **X3, L by name. [G–L]** A heat sink node holds `rejected_heat`, and the two nodes constraining it dissipate
  more than that. The gate's heat budget reads `heat_rejection_capacity` only → L, gate relation
  `heat_budget`.
- **X4, D, numeric. [L–D]** A cable's voltage drop depends on a conductor temperature that depends on the
  current it carries; deciding needs an iterative solution → D (numeric).
- **X5, N, wording. [L–N]** The revision's description calls a value "nominal" where the node holds a maximum,
  and the node's numbers are consistent → N (wording).
- **X6, D, table. [D–N]** A fastener's thread size is not a standard size for its nominal diameter → D (table).
- **X7, L, schedulability. [L–N]** Two tasks of 6.00 ms and 5.00 ms run every 10.0 ms each on one processor:
  utilisation 1.10 > 1 → L, inequality.
- **X8, L, limit. [L–N]** A capacitor node holds an operating voltage of 16.0 V and a rated voltage of 10.0 V →
  L (limit), inequality.

## Appendix E. The reality adjudication's system prompt and schema (the prior adjudication's, verbatim)

**System prompt** (sha256 of its UTF-8 bytes `41438ab78097d57a6e986b24f4f8071516fa36c1f0393f408874cd81adb23913`):

```
You are an experienced mechatronics design engineer adjudicating review findings on a proposed
revision of a design graph. For each finding, decide from the packet (and general engineering and
datasheet knowledge, which you must say you used when you use it) whether the design as revised
really has the defect the finding states (true_flaw), does not (not_a_flaw), or whether the packet
does not give enough to decide (undecidable). For a true_flaw, say whether the defect is absent from
the base design with the base values and so introduced by the revision (introduced), already present
in the base design (already_in_base), or both; otherwise origin is n/a. Judge the defect itself, not
the quality of the wording. Answer every finding id, with a reason of one or two sentences.
```

(Wrapped here for reading; the prompt is one line, the words and spaces exactly as above.)

**Output schema** (sha256 of these bytes `57c3852f8aa0adf9450de3504509b0bf95f85e78c55ff77b199a9c0998172324`):

```
{"type": "object", "properties": {"findings": {"type": "array", "items": {"type": "object", "properties": {"id": {"type": "string"}, "verdict": {"enum": ["true_flaw", "not_a_flaw", "undecidable"]}, "origin": {"enum": ["introduced", "already_in_base", "both", "n/a"]}, "reason": {"type": "string"}}, "required": ["id", "verdict", "origin", "reason"]}}}, "required": ["findings"]}
```
