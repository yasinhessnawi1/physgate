# Mechanical — skill

> Procedures, tables and antipatterns for every mechanical task. Researched and drafted from
> published sources by an agent (16.10.2026), approved by a person before use. Read
> `knowledge/cross/standards.md`, then `knowledge/mechanical/standards.md` (cited as "std §N").
> Every value taken from here enters the design with its source and condition (cross §1).

## Material table

| Material, form | Property | Value | Condition | Source |
|---|---|---|---|---|
| PLA / PET / ABS, printed | tensile strength XY | 34.7 / 33.4 / 36.3 MPa | ISO 527 | Forward AM catalogue 2023 |
| PLA / PET / ABS, printed | tensile strength ZX | 21.2 / 17.2 / 21.3 MPa | ISO 527 | same |
| PLA / PET / ABS, printed | Young's modulus XY | 2308 / 1933 / 1958 MPa | ISO 527 | same |
| PLA / PET / ABS, printed | Young's modulus XZ or ZX (labelled both ways) | 2131 / 1665 / 1608 MPa | ISO 527 | same |
| PLA / PET / ABS | heat deflection temp. | 65 / 63 / 96 °C | 0.45 MPa, ISO 75-2 | same |
| Carbon steel bolt | ultimate tensile (*typical*, 1990) | 55 ksi (379 MPa) and up | room temp. | RP-1228 Table I, p. 2 |
| 300-series stainless bolt | ultimate tensile (*typical*, 1990) | 70–140 ksi (483–965 MPa) | room temp. | same |

The printed values are one maker's, "guidance only": *typical values*, not allowables (std §3).
The catalogue gives recommended print settings (PLA and PET: nozzle 210–230 °C, nozzle ≥ 0.4 mm,
40–80 mm/s) but not the settings of the test specimens. Its comparison table labels the second
modulus XZ while its PLA and PET pages put it under ZX, so that direction is uncertain. The maker
names the grade "PET"; do not read it as another maker's PETG. MPa
here is this draft's conversion at 1 ksi = 6.894757 MPa [NIST SP 811, App. B.9]. A metal with no
published shear or bearing allowable: F_su ≈ 0.6 F_tu (carbon and alloy steel), 0.55 F_tu
(stainless); F_bu ≈ 1.5 F_tu, F_by ≈ 1.5 F_ty [RP-1228, p. 21] (*rules of thumb*, metals only).

## Wall-thickness, hole and radius minima

| Process | Feature | Minimum | Source |
|---|---|---|---|
| FDM | supported / unsupported wall | 1.0 mm | UZH AMF, *Design Guideline FDM* |
| FDM | overhang without support | 45° | same |
| FDM | hole diameter | 2.0 mm, "highly depends on the hole length" | same |
| FDM | clearance, moving or connecting parts | 0.5 mm | same |
| FDM | pin diameter / smallest feature | 3.0 / 2.0 mm | same |
| FDM | vertical hole | prints undersized: print small, drill to size | Protolabs Network, FDM page |
| FDM | pin under 5 mm | perimeters only: use a drilled hole and a bought pin | same |
| FDM | smallest external corner radius produced | the nozzle size (a result, not a rule) | same |
| CNC | wall, metal / plastic | 0.8 / 1.5 mm recommended (0.5 / 1.0 feasible) | Protolabs Network, CNC page |
| CNC | internal corner radius | ≥ ⅓ of cavity depth | same |
| CNC | cavity depth / hole depth | ≤ 4 × width / ≤ 4 × diameter recommended | same |
| CNC | thread length | 3 × D recommended, 1.5 × D minimum | same |

All are a service's guidelines (*rules of thumb*, std §14); web pages read 16.10.2026.

## Procedure: load cases and the governing case

1. List every case of std §1 from the specification; record each limit load as value, unit, source.
2. For the stall case take the stall torque at the voltage the design runs at; a figure rated at
   another voltage does not transfer without a stated basis.
3. Resolve each case into forces and moments at every part and joint (free-body diagram).
4. Compute each part's margin in each case; the lowest margin governs. Record which case governs.

## Procedure: strength margin of a part

1. Name the failure mode: yield, rupture, buckling, creep, thread strip, bearing.
2. Take the allowable with its condition; for a printed part, the value for its load direction (std §3).
3. Compute the limit stress with a formula whose assumptions hold (std §9, §10) or a solver.
4. MS = allowable / (FS × limit) − 1 for yield and for ultimate, FS with its source (std §2);
   record each MS as a quantity with unit 1.
5. A sustained load adds the creep check of std §4, or goes through metal.

## Procedure: bolted joint

1. Pick fastener and internal thread; check engagement and two-pitch protrusion (std §7). Into
   plastic, prefer a metal insert rated by test.
2. Set torque and lubricant; P_nom = T / (K·D) with K's source; apply Γ for P_max and P_min, then
   relaxation (std §5).
3. Check the bolt at P_max + n·φ·P_t (5020B Eq. 8, p. 28; n load-introduction factor, φ stiffness
   factor); taking n·φ = 1 (full applied tension) is a conservative bound. Separation at P_min (std §5).
4. Shear in bearing at ultimate; friction only for slip at limit; tension–shear interaction (std §6).
5. Edge distance 2·D nominal, never below 1.5·D; spacing 4·D [RP-1228, p. 21] (*rules of thumb*
   from metal practice). Do not share a load between bolts and interference-fit pins: the pins
   carry it until something yields (ibid.).
6. Add a preload-independent lock (std §8); put torque, running-torque basis, lubricant and lock on
   the drawing.

## Procedure: shaft and bearing

1. Draw the shaft with bearings, wheel load (weight share plus traction) and the gear-train torque;
   a gear pair passes T_A = T·r_A / r_B [Roylance, *Shear and Torsion*, Example 3].
2. At each section: σ = M·y / I, τ = T·r / J, σ_eq = √(σ² + 3τ²) (std §9). Solid round:
   J = π·d⁴/32 and I = π·d⁴/64 (*derived*: Roylance Eq. 12 with R_i = 0; I = J/2 since y² + z² = r²
   in the defining integrals).
3. Include the stress concentration of a D-flat, keyway or groove with its source, or record it
   unchecked.
4. Fatigue: the bending stress of a turning shaft is fully reversed; check it against the
   material's sourced endurance or S-N data, or record the check unverified (std §9).
5. Bearings: P_r from the reactions, then L10h against the specified hours, and P_0r ≤ C_0r for the
   fall case (std §9), with C_r and C_0r from the bearing's own datasheet.
6. Keep the robot's weight off a gearmotor shaft; any radial load on it is recorded unverified.

## Procedure: mass properties and centre-of-mass height

1. List every part with mass and source (weighed, datasheet, or CAD volume × density with source);
   a printed part is weighed or carries its infill and wall settings (std §11).
2. Place each part's centre of mass in one frame with its origin on the wheel axle.
3. r_CM = Σ m_j·r_j / Σ m_j; pitch inertia about the axle I = Σ (I_j + m_j·d_j²) (std §11).
4. Hand mass, centre-of-mass height and pitch inertia to sizing as cross quantities, with the list;
   after a change, follow up the nodes they constrain (cross §5).

## Procedure: drive sizing and traction

1. Required wheel torque per std §1 case; control's peak demand comes from the control role.
2. Available: usable gearmotor torque × external ratio, below stall and within the maker's limits
   (std §12).
3. Traction: wheel torque / wheel radius ≤ μ_s × normal load; say whether slip or the motor governs.
4. Worked example, an example only (this draft's arithmetic): Balboa with 50:1 HPCB 6 V gearmotors,
   stall 0.74 kgf·cm = 0.0726 N·m and 1.5 A at 6 V [Pololu product 3073], and the kit's largest
   external ratio 2.88:1 (49:17 teeth) [Pololu guide §1.1, p. 5; §1.2, p. 9]: stall bound at the
   axle 0.209 N·m per wheel, 5.2 N on an 80 mm wheel (§1.2, p. 9). The kit runs at 7.2 V nominal on
   NiMH [§3.6, p. 21], not the rating's 6 V, so that bound needs a stated basis there. The 25 % rule
   gives 0.375 A per motor. Mass: 200 g assembled with motors, 80 mm wheels and bumper cage; it
   "does not include batteries" [Pololu product 3575, specs]. Six AA NiMH cells at a typical 27 g
   each (one maker's cell, as an example) [Energizer NH15-2300 datasheet] make 362 g, a weight of
   3.55 N at 9.80665 m/s² (the standard gravity in NIST's kgf factor), 1.78 N per wheel upright,
   weight shared equally. If tyre and floor behave like the rubber-on-concrete values of std §12,
   traction per wheel is 1.78 N at μ_s = 1.0 and 0.89 N at μ_s = 0.5, against a 5.2 N stall bound:
   traction, not the motor, governs, by about 3 to 6 times.

## Procedure: load split on a statically indeterminate mount

1. If reactions outnumber the equilibrium equations, the mount is indeterminate.
2. Model each support's stiffness (screw, boss, standoff, printed wall) and the plate's bending.
3. Add one compatibility equation per extra reaction, solve, and check the reactions sum to the load
   [Roylance, *Beam Displacements*, Example 2].
4. Size each support for its own reaction; record method and stiffnesses (std §13). Uncertain
   stiffness: bound the split with a stiff and a soft case.

## Design-for-manufacture checklist

1. Process, material and grade named for every part (FDM, CNC, bought).
2. Every wall, hole, pin, radius, cavity and thread meets the minima table, or the deviation is argued.
3. FDM: orientation puts the main tension along layers (std §3); overhangs ≤ 45° or supported;
   vertical holes drilled; 45° chamfer or radius on edges on the build plate [Protolabs Network,
   FDM page].
4. Every moving or connecting pair has a stated clearance, also in the balancing pose and to the
   ground (std §15); screw clearance and tap drill stated.
5. Thread forms compatible ("fine threads mated to coarse threads", inch with metric, are not)
   [5020B §4.7.2, p. 40]; no screw bottoming in a blind hole (TFSR 25, p. 42).
6. Tool access to every fastener; torque and locking on the drawing (std §5, §8).

## Antipatterns

- **"Strong enough" with no margin.** No load case, allowable or factor leaves nothing to check
  (std §1, §2).
- **Flat-direction (XY) strength for a printed part loaded across layers.** One maker's PET keeps
  about half its flat strength across layers (std §3).
- **Stall torque as an operating point.** The maker calls it theoretical and damaging (std §12).
- **Sizing for the largest force, not the lowest margin.** A smaller load on a weaker section, or
  one held for hours on plastic, can govern (std §1, §4).
- **Clamping friction under a screw in printed plastic.** Its relaxation is known only by test;
  carry shear in bearing or through a metal insert (std §5, §6).
- **A split lock washer as the lock.** Flat once torqued, it locks nothing (std §8).
- **An even split over three or four supports.** Stiffness decides; one support can carry most
  (std §13).
- **The robot's weight on the gearmotor shaft.** No overhung-load limit is published; the
  reference robot uses ball bearings (std §9).
- **A spaceflight factor used as physics, or dropped unexamined.** State factor, class and reason
  (std §2).
- **A centre-of-mass value with no parts list.** Control's plant rests on it and no one can
  recheck it (std §11).
- **A deflection limit chosen as a round number.** Derive it from what it protects (std §10).
- **A static yield check as the whole check of a turning shaft.** Its bending stress reverses every
  revolution; fatigue is a separate check (std §9).
