# Mechanical — standards

> Researched and drafted from published sources by an agent (16.10.2026), approved by a person
> before use. Read `knowledge/cross/standards.md` first; this file builds on it. Numbers are marked
> *derived* (theorem, definition, arithmetic: never relaxed), *normative* (a rule of the cited
> standard, adopted here) or *rule of thumb / typical value* (a sourced analysis may override it).
> Every value a rule asks for is recorded as value, unit and source (cross §1).

## 1. Every load case is enumerated with its source, and the governing case is named

List for each part and joint: static weight; the drive's stall-torque reaction (the most the drive
can apply, whatever the controller intends); each acceleration the specification names; a fall or
impact where it names one. Each is a limit load, "the maximum anticipated load, or combination of
loads that a structure may experience during its design service life" [NASA, *NASA-STD-5001B
w/Change 3*, 2022, §3.2, p. 10]. The governing case is the lowest margin (§2), not the largest
force. Factors presume "the service environments and limit loads shall be well defined" (ibid.,
FSR 3, p. 13). A balancing robot falls: the reference robot's guide advises a bumper cage "so the
bumper will hit the ground before the electronics" [Pololu, *Balboa 32U4 Balancing Robot User's
Guide*, ©2001–2022, §4, p. 60]; no impact load is published, so a fall case takes height and floor
from the design's own specification.

**Judgement-only** — check 2 bounds a named quantity; nothing detects an omitted load case.

## 2. A strength claim is a margin of safety against a stated factor, for yield and for ultimate

MS = allowable / (FS × limit load) − 1, once for yield, once for ultimate (*derived*: definition,
[5001B §3.2, p. 10]); for a threaded fastening system the denominator also carries the fitting
factor FF [NASA, *NASA-STD-5020B*, 2021, §4.4.1, Eqs. 6–7, p. 27]. MS ≥ 0 is required. A factor
multiplies limit load, never preload (5020B §4.2.1, p. 18). Factors cover "assumed uncertainty in
mechanical properties and manufacturing but not a lack of engineering effort" [ECSS,
*ECSS-E-ST-32-10C Rev.2 Corr.1*, 2019, §1, p. 6].
No public standard read gives a factor for a small ground robot or for printed plastic. The
published values are for spaceflight hardware. 5001B excludes "engines, rotating hardware, ...
ground support equipment" (§1.2.1, p. 6) and presumes "aerospace standard manufacturing and process
controls" (FSR 4) and "materials having mechanical properties that are well characterized" (§4.b,
p. 13); ECSS excludes GSE (§4.1.2a, p. 12) and defers mechanisms, "stops/shaft shoulders", to
ECSS-E-ST-33-01 (§1, p. 7), which was not read. Metallic 1.25 yield / 1.4 ultimate with protoflight
test [5001B Table 1, p. 18] and satellite metallic 1.1 / 1.25 with test [ECSS Table 4-3, p. 21] are
*normative* for those classes and not adopted. Analysis-only verification needs "larger factors of
safety than for tested hardware", yet "increasing the design factors of safety does not by itself
justify a 'no-test' approach" (5001B §4.1.2.3, p. 16). **Stated choice of this draft, for the
approver:** a metallic part verified by analysis only uses at least ECSS's satellite analysis-only
pair 1.25 / 2.0 (Table 4-3), as published practice of a stricter class, not as physics. Using it
on a shaft or mechanism goes beyond what either source covers. For printed plastic no factor is
adopted, because both standards presume well-characterized materials and controlled processes,
which a printed part does not have: the design states its factor, why, and test or analysis.
**Fitting factor (bolted joints).** FF is required (5020B TFSR 3, p. 18); it "should" be at least
1.15 on the ultimate factor, at least 1.15 on the yield factor where local yielding matters, and at
least 1.15 on FS_sep for a separation-critical joint. FF = 1.0 "may be adequate" for strength after
an ultimate load test, test-correlated finite elements, or redundant fasteners with ductility to
redistribute; for separation, when the joint is not separation-critical, or is separation-critical
but verified by a test to limit load or by test-correlated finite elements (ibid., pp. 18–20)
(*recommended practice* of 5020B, adopted).

**Judgement-only** — no gate check computes a structural margin: check 3 solves a determinate
mount's reactions and balances an indeterminate one's (cross §6), with no allowable or factor.

## 3. A material property is quoted with its condition, and a printed part uses the value for its load direction

Each strength, modulus or density carries source and condition: test standard, temperature, print
orientation and settings. Printed parts are anisotropic: "the strength of FDM (FFF) parts across
the layers (in the Z-direction) is significantly lower" [V. E. Kuznetsov et al., *Polymers*
10(3):313, 2018, §1]. One maker's ISO 527 tensile strengths, flat (XY) / upright (ZX): PLA 34.7 /
21.2 MPa, PET 33.4 / 17.2 MPa, ABS 36.3 / 21.3 MPa [BASF Forward AM, *3D Printing Materials &
Solutions*, Spring 2023, Mechanical Properties Comparison] (*typical values*; across layers 0.61,
0.51, 0.59 of flat, *derived*). Settings move strength widely: upright-printed PLA tubes in
three-point bending across layers gave ultimate flexural strength 17.5–70.7 MPa over nozzle and
layer settings [Kuznetsov 2018, Table 1]. That is a bending result on a different specimen and is
not comparable with the ISO 527 tensile values; the authors add that "the calculated UFS values
have no physical meaning, while being a virtual measure solely for comparison purposes" (§3.1).
Under tension across layers use the across-layer
value; with none, or other print settings, the value is unverified until tested. Polymers resist
yield more in compression than in tension [D. Roylance, *Yield and Plastic Flow*, MIT 3.11, 2001,
p. 6]; a tensile value is not reused for compression silently.

**Judgement-only** — check 2 can bound a magnitude but knows no print direction.

## 4. A sustained load on a plastic part is checked for creep, and its temperature is stated

Creep is "time-dependent deformation under load ... that results in cumulative, permanent
deformation" [5001B §3.2, p. 9]. Flat-printed PLA specimens (hexagonal infill) held at 15 MPa and
25 °C ruptured after a mean 2.1 h at the optimum of the tested range (0.1–0.3 mm layers, 10–100 %
infill: 0.1 mm, 100 %) [M. Waseem et al., *Polymers* 12(12):2962, 2020]; printed PETG creeps too
[L. Stankevics et al., *Polymers* 17(15):2075, 2025]. Short-term strength is no allowable for a load
held for hours (weight on a printed bracket, a screw clamping plastic). State each sustained load,
its duration and creep data; without data, carry it through metal and record the check open.
Spaceflight puts a factor 4.0 on fatigue and creep life (*normative* there, not adopted) [5001B
§4.4, FSR 51, p. 24]. A plastic part near a motor, driver or battery states its service temperature
against the heat deflection temperature at 0.45 MPa (ISO 75-2: PLA 65 °C, PET 63 °C, ABS 96 °C
[Forward AM catalogue]), an indicator only, not an allowable (*typical values*); the creep data
above is at 25 °C only.

**Judgement-only** — no gate check models time or a part's temperature against a plastic's limit.

## 5. A bolted joint states its preload range, from the installation method and its scatter

5020B requires the torque–preload relation to be "substantiated by tests of a minimum of six sets"
(TFSR 6, p. 23). **Stated choice of this draft for untested small-robot joints** (a relaxation of
5020B, not 5020B adopted): P_nom = T / (K·D) [5020B App. A.2, Eq. 24, p. 46] with a handbook K —
"the commonly assumed value for K is 0.2, but this value should not be used blindly" [R. T.
Barrett, *Fastener Design Manual*, NASA RP-1228, 1990, p. 17]; K = 0.074 to 0.250 for friction
0.05 to 0.20 (ibid., Table VI, p. 18) (*typical values*) — and 5020B's scatter minima Γ = 25 %
lubricated, 35 % not, without the test envelope that Table 3 adds (p. 25). "Lubricated" means
lubricant on the threads and on the turning bearing surface of nut or head (ibid., p. 26).
P_max = c_max(1+Γ)P_nom; P_min = c_min(1−Γ)P_nom (Eq. 4), less relaxation, creep and thermal loss
(Eqs. 1–4, pp. 21–22). Eq. 4 is 5020B's form for separation-critical joints; its milder Eq. 5
(Γ/√n_f) for slip and other joints is not used, by choice, to stay conservative. Relaxation is 5 %
for all-metal joints (*normative*, adopted) and "test-derived" for joints with "any non-metallic
parts or coatings"; 5 % "may be non-conservative" with several faying surfaces (Table 1, p. 22). A
printed part or a plated screw makes P_min unknown without test, and clamping friction is not
relied on. Separation, axial loading only: MS_sep = P_min / (FF·FS_sep·P_tL) − 1 (Eq. 19, p. 32).
FS_sep (Fig. 1, p. 20, *normative*, adopted): where separation could credibly cause a catastrophic
hazard, the ultimate factor; a critical hazard, the greater of 1.2 and the yield factor; otherwise
the greater of 1.0 and the test factor, raised if tested above limit load. The drawing states
torque, whether above running torque, and lubricant (TFSR 26, p. 43).

**Judgement-only** — no gate check holds a preload.

## 6. Shear across a joint is carried in bearing at ultimate, never by friction

"Use of friction to react applied shear forces between the clamped parts is not permissible for
ultimate load assessment" [5020B §4.4.1, p. 26]. In slip checks at limit or yield, μ ≤ 0.20 for
clean uncoated non-lubricated metal, ≤ 0.10 for every other surface, nonmetallic included, unless
tested (TFSR 14, p. 35) (*normative*, adopted). Threads in the shear plane leave only the minor
area (Eq. 13, p. 28): choose grip "such that the threads are never in bearing" [RP-1228, p. 22].
Tension with shear takes an interaction check (5020B Eqs. 20–23, pp. 33–34).

**Judgement-only** — no gate check models a joint's load path.

## 7. Thread engagement makes the screw fail before the thread strips; a thread or insert in plastic is rated by test

Engage threads "such that the fastener would fail in tension before threads would strip"; a screw
through a nut or insert extends two pitches past it [5020B §4.7.4, pp. 41–42] (*recommended
practice* of 5020B, a "should", adopted). Tapped-hole pull-out in a metal parent: P = π·d_m·F_s·L / 3
(d_m pitch diameter, F_s shear strength of the weaker material, L engaged length; "the 1/3 factor
is empirical") [RP-1228, p. 21] (*rule of thumb*). No shear strength of a thread in printed
plastic was found in the sources read, so such a thread is rated by test. In "nonmetallic
materials ... allowable pull-out loads should be derived from test" [5020B §4.4.1, p. 27];
ultrasonic inserts "do not have the holding power of those that are molded in place" [RP-1228,
p. 12].

**Judgement-only** — no gate check knows thread geometry.

## 8. Every threaded fastener has a locking feature that does not depend on preload

Spaceflight hardware "shall incorporate a minimum of one locking feature that does not depend upon
preload" [5020B TFSR 16, p. 37] (*normative* there; adopted here by stated choice: a robot that
falls and vibrates sheds loose screws). A helical spring lock washer "is useless for locking"; jam
nuts are "too unpredictable to be reliable"; nylon elements stop at about 250 °F (121 °C, this
draft's conversion; *typical value*) and are damaged by reassembly [RP-1228, pp. 7, 9]. A bolt that
is an axis of rotation takes a mechanical lock (TFSR 17, p. 38); a liquid locker needs a validated
process (TFSR 18, p. 38).

**Judgement-only** — no gate check sees fastener hardware.

## 9. A shaft is checked for combined bending and torsion, a bearing for rated life, and bearings carry the weight

|σ| = M·y / I [Roylance, *Stresses in Beams*, MIT 3.11, 2000, Eq. 7]; τ = T·r / J, J = π(R_o⁴ −
R_i⁴)/2 [Roylance, *Shear and Torsion*, 2000, Eqs. 12, 14]; σ_eq = √(σ² + 3τ²) (*derived*: this
draft's reduction of the von Mises form in *Yield and Plastic Flow*, p. 5; 5020B p. 31 also names
von Mises or Tresca), checked against yield with the §2 factor, which for a shaft is this library's
extension (§2). This is a static check only. A shaft that turns under a bending load sees fully
reversed stress every revolution [Roylance, *Fatigue*, 2001, p. 2]; ferrous alloys can have an
endurance limit, aluminium has none and is sized to a life on its S-N curve, and a mean stress is
handled with a Goodman line (ibid., pp. 3–4). No endurance or S-N values were found in the sources
read: the design states its material's fatigue data with source and condition, or records the
fatigue check unverified. Ball bearings: L10 = (C_r/P_r)³ ×10⁶ rev at 90 % reliability,
L10h = 10⁶/(60·n)·(C_r/P_r)³, P_r = X·F_r + Y·F_a [MinebeaMitsumi NMB, *Miniature / Small-diameter
Rolling Ball Bearings*, Oct 2019, pp. 20–21] (the catalogue's formula after JIS B 1518, *normative*
there; neither it nor ISO 281 was read). For the fall case, P_0r = max(0.6·F_r + 0.5·F_a, F_r) ≤
C_0r, the load at 4,200 MPa contact stress, for deep groove ball bearings (ibid., pp. 22–23; the
catalogue's rule after JIS B 1519, *normative* there; no static factor was found). The
reference robot's gearboxes "support the weight of the robot with ball bearings rather than the
motor shafts themselves" [Pololu guide §1.2, p. 9]; no overhung-load limit is published for its
gearmotors, so such a load is recorded unverified.

**Judgement-only** — no gate check computes stress or life.

## 10. A deflection limit comes from the function it protects, and its formula's assumptions are stated

No generic limit was found in the sources read; derive it from what deflection breaks (gear mesh,
sensor alignment, a clearance). Stiffness may need "more stringent" limits than strength [5001B
§4.1, p. 13]. Formulas assume linear elasticity and small rotations [Roylance, *Stresses in Beams*,
pp. 1–2]: e.g. centre load on a simple span δ = P·L³ / (48·E·I) [Roylance, *Beam Displacements*,
2000, Eq. 7]; twist θ = T·L / (G·J) [*Shear and Torsion*, Eq. 13]. Printed modulus depends on
direction: PLA 2308 MPa XY and 2131 MPa in the other direction (*typical values*), which the
catalogue's comparison table labels XZ but its PLA page places under ZX [Forward AM catalogue], so
that direction is uncertain.

**Judgement-only** — no gate check computes deflection.

## 11. Mass, centre of mass and inertia come from a stated list and method

r_CM = (1/M)·Σ m_j·r_j [W. Moebs et al., *University Physics* Vol. 1, OpenStax, 2016, §9.6,
Eq. 9.29]; I = Σ I_i about one axis, I = I_CM + m·d² (ibid., §10.5, Eqs. 10.20–10.21) (*derived*).
Each mass has a source: datasheet, weighed, or CAD volume × stated density. A printed part is
weighed, or its infill and wall settings are stated with the estimate, since partial infill makes it
lighter than its solid volume. A balancing robot is an "inverted pendulum" [Pololu guide §7, p. 78]:
mass, centre-of-mass height above the axle and pitch inertia set the control plant, so they are
cross quantities owned by sizing (ARCH-051).

**Judgement-only** — check 7 enforces only the follow-up a changed value owes (cross §5); nothing
checks the sum or the method.

## 12. Drive torque is sized against the motor's limits and the traction limit, with a stated margin

Wheel torque per §1 case ≤ usable gearmotor torque × external ratio (gear loss ignored, so an upper
bound, *derived*). Stall is not usable: the maker calls stall figures "theoretical values; stalls
could damage the motor or gearbox", sets an instantaneous-torque limit with applied loads to stay
"well under" it, and gives "a general recommendation ... 25% or less of the stall current" (*rule of
thumb*) [Pololu, product 3073 page, read 16.10.2026]. Traction: force ≤ μ_s·N [OpenStax
*University Physics* Vol. 1, §6.2, Eq. 6.1], coefficients "approximate" (rubber on dry concrete 1.0,
wet 0.5–0.7, Table 6.1, *typical values*); for a stated floor measure μ_s or take the lowest sourced
value. No numeric margin for torque or traction was found in the sources read: the design states its
margin and why. 1 kgf·cm = 0.0980665 N·m (*derived* from 1 kgf·m = 9.80665 N·m [NIST, SP 811, App.
B.9]).

**Judgement-only** — check 4 holds electrical draw to supply; none holds torque or traction.

## 13. A mount on more than two supports states how its load split was found

Equilibrium cannot split the load; add compatibility (deflection at each support) [Roylance,
*Beam Displacements*, pp. 3–4]. In its three-support example (uniform load, total 150) the reactions
are 28.11, 93.78, 28.11: the middle carries 62.5 %, not a third (*derived*). For equal bolts under a
moment, load is taken proportional to distance from the centroid (shear) or a conservatively chosen
heel line (tension) [RP-1228, pp. 17–18]; with clearance holes "some fasteners may not share the load
equally; and some fasteners may be unloaded" [5020B §4.2.2, p. 19]. State method, stiffnesses and
each support's reaction.

**Judgement-only** — check 3 balances declared reactions and leaves the split unverified (cross §6).

## 14. Every part meets its process's design-for-manufacture minima before release

Use the skill file's minima table and checklist for the process actually used. The minima are a
service's published guidelines (*rules of thumb*); going below one needs a reason, e.g. a test print.

**Judgement-only** — no gate check reads geometry.

## 15. Every clearance in the assembled, balancing pose is stated with a value, including to the ground

Check moving and fixed parts for interference and state each clearance in the pose the robot runs
in, with its tolerance basis: the reference robot's guide warns that 70×8 mm wheels "only offer a
few millimeters of clearance when the robot is balancing" [Pololu guide §1.2, p. 9].

**Judgement-only** — no gate check reads geometry or poses.
