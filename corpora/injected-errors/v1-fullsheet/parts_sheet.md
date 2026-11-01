**Stand-in design, not the reference solution. Kit: Pololu Balboa 32U4 Balancing Robot Kit (item #3575), built with 50:1 Micro Metal Gearmotor HPCB 6V with Extended Motor Shaft (#3073), Pololu Wheel 80×10mm (#1430) and six AA NiMH cells (#1003).**

# Parts sheet, Balboa 32U4 stand-in (second pass, 27.09.2026)

Kit choice: I chose the Pololu Balboa 32U4 because Pololu publishes the whole build: a kit spec page with assembled mass and size, a full user's guide, a schematic, and dimension and gear-ratio PDFs, plus its own product page for every recommended motor, wheel and battery. The guide and schematic also name each on-board IC (DRV8838, MP4423H, LSM6DS33, ATmega32U4), so every datasheet figure traces back to a part the maker says is on the board.

Conventions: a count a source states is a row of its own, in the unit "count". Every row has an id, `R<section>.<row>`, which a derived number cites as `[R1.03]`. Values are copied verbatim with the source's own unit. Values from drawings and charts were read from the rendered page, which is cited. A number no source states is not on this sheet. All sources were retrieved on 27.09.2026.

Source keys (full URLs are in every row):
- Kit spec tab: https://www.pololu.com/product/3575/specs
- Kit description: https://www.pololu.com/product/3575
- User's guide: https://www.pololu.com/docs/0J70/all
- Schematic: https://www.pololu.com/file/0J1267/balboa-32u4-control-board-schematic.pdf

The 50:1 motor is the one the user's guide uses in its worked example. The 30:1 and 75:1 motors, which the kit page also recommends, have their own table.

## 1. Motor with gearbox: 50:1 Micro Metal Gearmotor HPCB 6V with Extended Motor Shaft (Pololu #3073), qty 2

| row | quantity | value | unit | source URL | retrieved | note |
|---|---|---|---|---|---|---|
| R1.01 | rated voltage | 6 | V | https://www.pololu.com/product/3073 | 27.09.2026 | "Rated Voltage" column, HPCB 6V comparison table on product description |
| R1.02 | rated voltage | 6 | V | https://www.pololu.com/file/0J1487/pololu-micro-metal-gearmotors-rev-6-2.pdf | 27.09.2026 | Pololu Micro Metal Gearmotors datasheet Rev 6.2 (February 2026), p. 4, "Rated Voltage", HPCB 6V |
| R1.03 | stall current @ 6V | 1.5 | A | https://www.pololu.com/product/3073/specs | 27.09.2026 | spec tab |
| R1.04 | stall current | 1.5 | A | https://www.pololu.com/file/0J1487/pololu-micro-metal-gearmotors-rev-6-2.pdf | 27.09.2026 | p. 4, "Stall Extrapolation", HPCB 6V, a table cell shared by all HPCB 6V ratios in the text extraction |
| R1.05 | no-load current @ 6V | 0.15 | A | https://www.pololu.com/product/3073/specs | 27.09.2026 | footnote: "Typical, ±50%; no-load current depends on internal friction, which is affected by many factors, including ambient temperature and duration of motor operation." |
| R1.06 | no-load current | 150 | mA | https://www.pololu.com/file/0J1487/pololu-micro-metal-gearmotors-rev-6-2.pdf | 27.09.2026 | p. 4, column header "mA (±50%)"; the text extraction shows one cell shared by the 10:1 to 1000:1 HPCB 6V rows |
| R1.07 | stall torque @ 6V | 0.74 | kg·cm | https://www.pololu.com/product/3073/specs | 27.09.2026 | spec tab |
| R1.08 | extrapolated stall torque | 0.74 | kg⋅cm | https://www.pololu.com/product/3073 | 27.09.2026 | comparison table; the same row gives 10 oz⋅in |
| R1.09 | stall torque (extrapolation) | 7.4 | kg⋅mm | https://www.pololu.com/file/0J1487/pololu-micro-metal-gearmotors-rev-6-2.pdf | 27.09.2026 | p. 4, row for items 3063, 3073, 5186, 5187 |
| R1.10 | no-load speed @ 6V | 650 | rpm | https://www.pololu.com/product/3073/specs | 27.09.2026 | footnote: "Typical; ±20%." |
| R1.11 | no-load speed | 650 | RPM | https://www.pololu.com/file/0J1487/pololu-micro-metal-gearmotors-rev-6-2.pdf | 27.09.2026 | p. 4, column header "RPM (±20%)" |
| R1.12 | gear ratio | 51.45:1 | ratio | https://www.pololu.com/product/3073/specs | 27.09.2026 | spec tab |
| R1.13 | gear ratio (exact) | 32 × 33 × 35 × 38 / 15 × 14 × 13 × 10 ≈ 51.4462: 1 | ratio | https://www.pololu.com/file/0J1487/pololu-micro-metal-gearmotors-rev-6-2.pdf | 27.09.2026 | p. 3, "Gearbox options" |
| R1.14 | gear ratio | 51.45:1 | ratio | https://www.pololu.com/docs/0J70/all | 27.09.2026 | user's guide: "50:1 motors (which have gear ratios more accurately specified as 51.45:1)" |
| R1.15 | max output power @ 6V | 1.2 | W | https://www.pololu.com/product/3073/specs | 27.09.2026 | the datasheet (p. 4) also gives 1.2 W |
| R1.16 | max efficiency @ 6V | 32 | % | https://www.pololu.com/product/3073/specs | 27.09.2026 | the datasheet (p. 4) also gives 32 % |
| R1.17 | speed at max efficiency | 490 | rpm | https://www.pololu.com/product/3073/specs | 27.09.2026 | the datasheet (p. 4) also gives 490 RPM |
| R1.18 | torque at max efficiency | 0.16 | kg·cm | https://www.pololu.com/product/3073/specs | 27.09.2026 | the datasheet (p. 4) gives 1.6 kg⋅mm |
| R1.19 | current at max efficiency | 0.42 | A | https://www.pololu.com/product/3073/specs | 27.09.2026 | the datasheet (p. 4) also gives 0.42 A |
| R1.20 | output power at max efficiency | 0.80 | W | https://www.pololu.com/product/3073/specs | 27.09.2026 | the datasheet (p. 4) also gives 0.80 W |
| R1.21 | mass (weight) | 9.5 | g | https://www.pololu.com/product/3073/specs | 27.09.2026 | per motor |
| R1.22 | dimensions (size) | 10 × 12 × 25 | mm | https://www.pololu.com/product/3073/specs | 27.09.2026 | footnote: "Output shafts add 15 mm to the 26 mm length. See dimension diagram for details." |
| R1.23 | shaft diameter | 3 | mm | https://www.pololu.com/product/3073/specs | 27.09.2026 | "D shaft" |
| R1.24 | motor type | 1.5A stall @ 6V (HPCB 6V - carbon brush) | text | https://www.pololu.com/product/3073/specs | 27.09.2026 | encoder: "encoder-compatible (extended motor shaft)" |
| R1.25 | number of motors on the robot | 2 | count | https://www.pololu.com/product/3575 | 27.09.2026 | "The Balboa uses two micro metal gearmotors to drive external 2-gear gearboxes" |

## 1a. Alternative motors the kit page recommends (Pololu #3072, #3074)

| row | quantity | value | unit | source URL | retrieved | note |
|---|---|---|---|---|---|---|
| R1a.01 | 30:1 HPCB 6V gear ratio | 29.86:1 | ratio | https://www.pololu.com/product/3072/specs | 27.09.2026 | |
| R1a.02 | 30:1 no-load speed @ 6V | 1100 | rpm | https://www.pololu.com/product/3072/specs | 27.09.2026 | "Typical; ±20%." |
| R1a.03 | 30:1 no-load current @ 6V | 0.15 | A | https://www.pololu.com/product/3072/specs | 27.09.2026 | "Typical, ±50%" |
| R1a.04 | 30:1 stall current @ 6V | 1.5 | A | https://www.pololu.com/product/3072/specs | 27.09.2026 | |
| R1a.05 | 30:1 stall torque @ 6V | 0.45 | kg·cm | https://www.pololu.com/product/3072/specs | 27.09.2026 | |
| R1a.06 | 30:1 max output power @ 6V | 1.2 | W | https://www.pololu.com/product/3072/specs | 27.09.2026 | |
| R1a.07 | 30:1 weight | 9.5 | g | https://www.pololu.com/product/3072/specs | 27.09.2026 | |
| R1a.08 | 30:1 size | 10 × 12 × 25 | mm | https://www.pololu.com/product/3072/specs | 27.09.2026 | same shaft note as #3073 |
| R1a.09 | 75:1 HPCB 6V gear ratio | 75.81:1 | ratio | https://www.pololu.com/product/3074/specs | 27.09.2026 | |
| R1a.10 | 75:1 no-load speed @ 6V | 430 | rpm | https://www.pololu.com/product/3074/specs | 27.09.2026 | "Typical; ±20%." |
| R1a.11 | 75:1 no-load current @ 6V | 0.15 | A | https://www.pololu.com/product/3074/specs | 27.09.2026 | "Typical, ±50%" |
| R1a.12 | 75:1 stall current @ 6V | 1.5 | A | https://www.pololu.com/product/3074/specs | 27.09.2026 | |
| R1a.13 | 75:1 stall torque @ 6V | 1.1 | kg·cm | https://www.pololu.com/product/3074/specs | 27.09.2026 | |
| R1a.14 | 75:1 max output power @ 6V | 1.3 | W | https://www.pololu.com/product/3074/specs | 27.09.2026 | |
| R1a.15 | 75:1 weight | 9.5 | g | https://www.pololu.com/product/3074/specs | 27.09.2026 | |
| R1a.16 | 75:1 size | 10 × 12 × 25 | mm | https://www.pololu.com/product/3074/specs | 27.09.2026 | same shaft note as #3073 |

## 2. External chassis gearbox (part of kit #3575), qty 2

| row | quantity | value | unit | source URL | retrieved | note |
|---|---|---|---|---|---|---|
| R2.01 | reduction options (range) | 1.64:1 to 2.88:1 | ratio | https://www.pololu.com/product/3575 | 27.09.2026 | "five reduction options" |
| R2.02 | 49:17 gear ratio | 2.88:1 | reduction | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | gear ratio chart |
| R2.03 | 47:19 gear ratio | 2.47:1 | reduction | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | |
| R2.04 | 45:21 gear ratio | 2.14:1 | reduction | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | |
| R2.05 | 43:23 gear ratio | 1.87:1 | reduction | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | |
| R2.06 | 41:25 gear ratio | 1.64:1 | reduction | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | |
| R2.07 | exact gearmotor ratio, nominal 30:1 | 86955/2912 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Exact gearmotor ratios" table, read from the rendered page |
| R2.08 | exact gearmotor ratio, nominal 50:1 | 3344/65 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Exact gearmotor ratios" table, read from the rendered page |
| R2.09 | exact gearmotor ratio, nominal 75:1 | 38437/507 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Exact gearmotor ratios" table, read from the rendered page |
| R2.10 | overall gear ratio, 30:1 gearmotor with 49:17 external gearbox | 86.1:1 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Overall gear ratios" grid, read from the rendered page |
| R2.11 | overall gear ratio, 50:1 gearmotor with 49:17 external gearbox | 148.3:1 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Overall gear ratios" grid, read from the rendered page |
| R2.12 | overall gear ratio, 75:1 gearmotor with 49:17 external gearbox | 218.5:1 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Overall gear ratios" grid, read from the rendered page |
| R2.13 | overall gear ratio, 30:1 gearmotor with 47:19 external gearbox | 73.9:1 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Overall gear ratios" grid, read from the rendered page |
| R2.14 | overall gear ratio, 50:1 gearmotor with 47:19 external gearbox | 127.3:1 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Overall gear ratios" grid, read from the rendered page |
| R2.15 | overall gear ratio, 75:1 gearmotor with 47:19 external gearbox | 187.5:1 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Overall gear ratios" grid, read from the rendered page |
| R2.16 | overall gear ratio, 30:1 gearmotor with 45:21 external gearbox | 64.0:1 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Overall gear ratios" grid, read from the rendered page |
| R2.17 | overall gear ratio, 50:1 gearmotor with 45:21 external gearbox | 110.2:1 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Overall gear ratios" grid, read from the rendered page |
| R2.18 | overall gear ratio, 75:1 gearmotor with 45:21 external gearbox | 162.5:1 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Overall gear ratios" grid, read from the rendered page |
| R2.19 | overall gear ratio, 30:1 gearmotor with 43:23 external gearbox | 55.8:1 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Overall gear ratios" grid, read from the rendered page |
| R2.20 | overall gear ratio, 50:1 gearmotor with 43:23 external gearbox | 96.2:1 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Overall gear ratios" grid, read from the rendered page |
| R2.21 | overall gear ratio, 75:1 gearmotor with 43:23 external gearbox | 141.7:1 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Overall gear ratios" grid, read from the rendered page |
| R2.22 | overall gear ratio, 30:1 gearmotor with 41:25 external gearbox | 45.9:1 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Overall gear ratios" grid, read from the rendered page |
| R2.23 | overall gear ratio, 50:1 gearmotor with 41:25 external gearbox | 84.4:1 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Overall gear ratios" grid, read from the rendered page |
| R2.24 | overall gear ratio, 75:1 gearmotor with 41:25 external gearbox | 124.3:1 | ratio | https://www.pololu.com/file/0J1266/balboa-kit-gear-ratio-chart.pdf | 27.09.2026 | p. 1, "Overall gear ratios" grid, read from the rendered page |
| R2.25 | bearings | six 683 ball bearings | text | https://www.pololu.com/product/3573 | 27.09.2026 | chassis kit contents |
| R2.26 | number of external gearboxes | 2 | count | https://www.pololu.com/product/3573 | 27.09.2026 | "Two configurable gearboxes further increase the gear ratio" |

## 3. Encoder (magnetic disc on motor extended shaft + Hall sensors on the control board), qty 2

| row | quantity | value | unit | source URL | retrieved | note |
|---|---|---|---|---|---|---|
| R3.01 | counts per revolution | 12 | counts per revolution of the motor shaft | https://www.pololu.com/docs/0J70/all | 27.09.2026 | "when counting both edges of both channels" |
| R3.02 | encoder disc resolution | 12 | CPR | https://www.pololu.com/docs/0J70/all | 27.09.2026 | kit contents: "two magnetic encoder discs (12 CPR)" |
| R3.03 | example counts per wheel revolution | ≈ 1778 | CPR | https://www.pololu.com/docs/0J70/all | 27.09.2026 | the guide's own worked example: "51.45 × 2.88 × 12 ≈ 1778 CPR" |
| R3.04 | sensor type | Hall effect sensor ICs in SOT-23 packages, e.g. AH1751 | text | https://www.pololu.com/file/0J1267/balboa-32u4-control-board-schematic.pdf | 27.09.2026 | schematic note |
| R3.05 | number of encoder discs | 2 | count | https://www.pololu.com/docs/0J70/all | 27.09.2026 | kit contents: "two magnetic encoder discs (12 CPR)" |

## 4. Motor driver: Texas Instruments DRV8838 (on Balboa 32U4 control board), qty 2 (one per motor)

| row | quantity | value | unit | source URL | retrieved | note |
|---|---|---|---|---|---|---|
| R4.01 | part identity | Two on-board Texas Instruments DRV8838 motor drivers | text | https://www.pololu.com/docs/0J70/all | 27.09.2026 | also shown twice on the schematic |
| R4.02 | board maximum input voltage | 10.8 | V | https://www.pololu.com/docs/0J70/all | 27.09.2026 | "the maximum voltage for the board is still limited to 10.8 V by the DRV8838 motor driver" |
| R4.03 | motor supply voltage VM (recommended) | 0 to 11 | V | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | TI SLVSBA4F (rev. April 2021), 6.3 Recommended Operating Conditions |
| R4.04 | motor supply voltage VM (absolute max) | –0.3 to 12 | V | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | 6.1 Absolute Maximum Ratings |
| R4.05 | logic supply voltage VCC | 1.8 to 7 | V | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | 6.3 |
| R4.06 | peak output current (IOUT motor peak current) | 0 to 1.8 | A | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | 6.3; Features: "1.8-A Maximum Drive Current" |
| R4.07 | peak drive current (absolute max) | Internally limited | A | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | 6.1 |
| R4.08 | overcurrent protection trip level IOCP | 1.9 (min), 3.5 (max) | A | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | 6.5 |
| R4.09 | HS + LS FET on-resistance rDS(on) | 280 (typ), 330 (max) | mΩ | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | VM = 5 V; VCC = 3 V; IO = 800 mA; TJ = 25°C |
| R4.10 | operating virtual junction temperature TJ | –40 to 150 | °C | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | 6.1 |
| R4.11 | operating ambient temperature TA | –40 to 85 | °C | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | 6.3 |
| R4.12 | thermal shutdown temperature TTSD | 150 (min), 160 (typ), 180 (max) | °C | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | die temperature TJ |
| R4.13 | RθJA junction-to-ambient | 60.9 | °C/W | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | DSG (WSON) 8 pins |
| R4.14 | RθJC(top) | 71.4 | °C/W | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | |
| R4.15 | RθJC(bot) | 9.8 | °C/W | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | |
| R4.16 | RθJB junction-to-board | 32.2 | °C/W | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | |
| R4.17 | ψJT / ψJB | 1.6 / 32.8 | °C/W | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | |
| R4.18 | externally applied PWM frequency | 0 to 250 | kHz | https://www.ti.com/lit/ds/symlink/drv8838.pdf | 27.09.2026 | 6.3 |
| R4.19 | number of motor drivers | 2 | count | https://www.pololu.com/docs/0J70/all | 27.09.2026 | "Two on-board Texas Instruments DRV8838 motor drivers power the Balboa's two micro metal gearmotors" |

## 5. Battery: Rechargeable NiMH AA Battery: 1.2 V, 2200 mAh, 1 cell (Pololu #1003), qty 6

| row | quantity | value | unit | source URL | retrieved | note |
|---|---|---|---|---|---|---|
| R5.01 | cell count | six AA batteries | cells | https://www.pololu.com/docs/0J70/all | 27.09.2026 | "Balboa chassis's six-AA battery compartment"; the kit page says "Balboa runs on six AA batteries (not included)" |
| R5.02 | battery holder configurations | four or six AA | cells | https://www.pololu.com/product/3573 | 27.09.2026 | chassis page: "can be configured for four or six AA batteries" |
| R5.03 | pack nominal voltage (NiMH) | 7.2 | V | https://www.pololu.com/docs/0J70/all | 27.09.2026 | "nominal voltage of 7.2 V (1.2 V per cell)" |
| R5.04 | pack nominal voltage (alkaline) | 9 | V | https://www.pololu.com/docs/0J70/all | 27.09.2026 | "alkaline cells, which would nominally give you 9 V" |
| R5.05 | cell nominal voltage | 1.2 | V | https://www.pololu.com/product/1003/specs | 27.09.2026 | |
| R5.06 | capacity | 2200 | mAh | https://www.pololu.com/product/1003/specs | 27.09.2026 | per cell |
| R5.07 | mass per cell (weight) | 0.97 | oz | https://www.pololu.com/product/1003/specs | 27.09.2026 | |
| R5.08 | cell size | 14 x 14 x 50 | mm | https://www.pololu.com/product/1003/specs | 27.09.2026 | |
| R5.09 | cell type | AA NiMH | text | https://www.pololu.com/product/1003/specs | 27.09.2026 | |
| R5.10 | number of cells in the pack | 6 | count | https://www.pololu.com/product/3575 | 27.09.2026 | "Balboa runs on six AA batteries (not included)"; the user's guide also says "six AA batteries" |

## 6. Voltage regulator, 5 V: MPS MP4423H switching buck converter (on control board), qty 1

| row | quantity | value | unit | source URL | retrieved | note |
|---|---|---|---|---|---|---|
| R6.01 | part identity | MP4423H switching buck converter | text | https://www.pololu.com/docs/0J70/all | 27.09.2026 | also on the schematic |
| R6.02 | output voltage | 5 | V | https://www.pololu.com/docs/0J70/all | 27.09.2026 | "The battery voltage is regulated to 5 V" |
| R6.03 | max output current (kit) | up to 2 A continuously | A | https://www.pololu.com/product/3575 | 27.09.2026 | the guide says: "Under typical conditions, up to 2 A of current is available from the VREG output" |
| R6.04 | input range (kit statement) | up to 36 | V | https://www.pololu.com/docs/0J70/all | 27.09.2026 | "the regulator itself works with input voltages up to 36 V, the motor drivers limit the control board's maximum input voltage to 10.8 V" |
| R6.05 | continuous operating input range | 4V to 36V | V | https://xonstorage.z8.web.core.windows.net/pdf/monolithicpowersystems_mp4423hgqz_apr22_xonlink.pdf | 27.09.2026 | MPS MP4423H datasheet Rev. 1.0, 8/18/2014. SOURCE CAVEAT: third-party mirror (XON) of MPS's datasheet Rev. 1.0, 8/18/2014; the file (sha256 f6f5f75efcc69ee585cdf04c176b3f1abf68c335a55db19accc961bbbe480053, 19 pages) holds MPS's 18 pages and one appended XON page; monolithicpower.com answered with a client challenge from two networks on 27.09.2026 |
| R6.06 | VIN absolute max | -0.3V to 40V | V | same mirror URL as above | 27.09.2026 | mirror caveat as above |
| R6.07 | continuous output current (datasheet) | 3A | A | same mirror URL as above | 27.09.2026 | "3A continuous output current"; mirror caveat as above |
| R6.08 | current limit ILIMIT | 3.2 (min), 4.4 (typ), 5.5 (max) | A | same mirror URL as above | 27.09.2026 | "Under 40% Duty Cycle"; mirror caveat as above |
| R6.09 | quiescent current IQ | 0.5 (typ), 0.7 (max) | mA | same mirror URL as above | 27.09.2026 | VEN = 2V, VFB = 1V, VIN = 12V; mirror caveat as above |
| R6.10 | shutdown supply current ISHDN | 8 | μA | same mirror URL as above | 27.09.2026 | VEN = 0V; mirror caveat as above |
| R6.11 | switching frequency | 320 (min), 410 (typ), 500 (max) | kHz | same mirror URL as above | 27.09.2026 | mirror caveat as above |
| R6.12 | operating junction temp | -40°C to +125°C | °C | same mirror URL as above | 27.09.2026 | junction temperature (abs. max) 150°C; mirror caveat as above |
| R6.13 | thermal resistance θJA / θJC | 55 / 13 | °C/W | same mirror URL as above | 27.09.2026 | QFN-8 (3mmx3mm), "Measured on JESD51-7, 4-layer PCB"; mirror caveat as above |

## 7. Microcontroller board: Balboa 32U4 Control Board (Pololu #3576) with Microchip ATmega32U4, qty 1

| row | quantity | value | unit | source URL | retrieved | note |
|---|---|---|---|---|---|---|
| R7.01 | microcontroller | ATmega32U4 AVR microcontroller | text | https://www.pololu.com/docs/0J70/all | 27.09.2026 | |
| R7.02 | clock | 16 | MHz | https://www.pololu.com/docs/0J70/all | 27.09.2026 | "clocked by a precision 16 MHz crystal oscillator" |
| R7.03 | MCU logic supply on board | 5 | V | https://www.pololu.com/docs/0J70/all | 27.09.2026 | "the ATmega32U4, operating at 5 V" |
| R7.04 | board max input voltage | 10.8 | V | https://www.pololu.com/docs/0J70/all | 27.09.2026 | limited by the DRV8838 |
| R7.05 | MCU operating voltage | 2.7 - 5.5V | V | https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-7766-8-bit-AVR-ATmega16U4-32U4_Datasheet.pdf | 27.09.2026 | Atmel-7766J-USB-ATmega16U4/32U4-Datasheet_04/2016 |
| R7.06 | MCU maximum frequency | 8MHz at 2.7V; 16MHz at 4.5V | MHz | same Microchip URL | 27.09.2026 | industrial range |
| R7.07 | MCU power supply current ICC, active 16MHz, VCC = 5V | 27 (max) | mA | same Microchip URL | 27.09.2026 | Table 29-1, datasheet p. 384, read from the rendered page: 27 is in the Max column; no Typ is given |
| R7.08 | MCU power supply current ICC, active 8MHz, VCC = 5V | 10 (typ), 15 (max) | mA | same Microchip URL | 27.09.2026 | Table 29-1 |
| R7.09 | MCU maximum operating voltage (abs. max) | 6.0 | V | same Microchip URL | 27.09.2026 | 29.1 |
| R7.10 | MCU operating temperature | -40°C to +85°C | °C | same Microchip URL | 27.09.2026 | |
| R7.11 | board overall length | 109.2 | mm | https://www.pololu.com/file/0J1264/balboa-32u4-control-board-dimensions.pdf | 27.09.2026 | p. 1 "Long profile" and p. 2 "Board dimensions (top view)", read from the rendered pages; drawing dated 14 March 2017, PCB bal01a; board edge tolerance ±0.3 mm |
| R7.12 | board overall width | 69.1 | mm | https://www.pololu.com/file/0J1264/balboa-32u4-control-board-dimensions.pdf | 27.09.2026 | p. 1 "Short profile" and p. 2 top view |
| R7.13 | board thickness | 1.57 | mm | https://www.pololu.com/file/0J1264/balboa-32u4-control-board-dimensions.pdf | 27.09.2026 | p. 1 "Short profile" |
| R7.14 | tallest part above the board | 8.0 | mm | https://www.pololu.com/file/0J1264/balboa-32u4-control-board-dimensions.pdf | 27.09.2026 | p. 1 "Long profile" |

## 8. IMU: ST LSM6DS33 3D accelerometer + 3D gyroscope (on control board), qty 1

| row | quantity | value | unit | source URL | retrieved | note |
|---|---|---|---|---|---|---|
| R8.01 | part identity | ST LSM6DS33 | text | https://www.pololu.com/docs/0J70/all | 27.09.2026 | the schematic shows it too. The board also carries an ST LIS3MDL magnetometer, which is not tabulated here |
| R8.02 | supply voltage Vdd | 1.71 (min), 1.8 (typ), 3.6 (max) | V | https://www.pololu.com/file/0J1087/LSM6DS33.pdf | 27.09.2026 | ST DocID027423 Rev 4 (October 2015). This is ST's datasheet as hosted by Pololu and linked from the kit's resources (sha256 96973195e7b425c7d66b6ab941cf6c7a0ab04ecd0bc61f78ec04f5362893048b, 77 pages); st.com timed out from two networks on 27.09.2026, so no newer revision was checked |
| R8.03 | supply on board | 3.3 | V | https://www.pololu.com/docs/0J70/all | 27.09.2026 | "the 3.3 V sensors" |
| R8.04 | supply current, gyro + accel high-performance mode | 1.25 | mA | https://www.pololu.com/file/0J1087/LSM6DS33.pdf | 27.09.2026 | IddHP, up to ODR = 1.6 kHz, @ Vdd = 1.8 V |
| R8.05 | supply current, gyro + accel normal mode | 0.9 | mA | https://www.pololu.com/file/0J1087/LSM6DS33.pdf | 27.09.2026 | IddNM, ODR = 208 Hz |
| R8.06 | supply current, gyro + accel low-power mode | 0.42 | mA | https://www.pololu.com/file/0J1087/LSM6DS33.pdf | 27.09.2026 | IddLP, ODR = 13 Hz |
| R8.07 | supply current, accelerometer only | 240 (HP) / 70 (NM, 104 Hz) / 24 (LP, 13 Hz) | μA | https://www.pololu.com/file/0J1087/LSM6DS33.pdf | 27.09.2026 | |
| R8.08 | power-down current | 6 | μA | https://www.pololu.com/file/0J1087/LSM6DS33.pdf | 27.09.2026 | |
| R8.09 | accelerometer ODR options | 13, 26, 52, 104, 208, 416, 833, 1666, 3332, 6664 | Hz | https://www.pololu.com/file/0J1087/LSM6DS33.pdf | 27.09.2026 | LA_ODR, Table 3 |
| R8.10 | gyroscope ODR options | 13, 26, 52, 104, 208, 416, 833, 1666 | Hz | https://www.pololu.com/file/0J1087/LSM6DS33.pdf | 27.09.2026 | G_ODR, Table 3 |
| R8.11 | accelerometer full scale | ±2/±4/±8/±16 | g | https://www.pololu.com/file/0J1087/LSM6DS33.pdf | 27.09.2026 | |
| R8.12 | gyroscope full scale | ±125/±245/±500/±1000/±2000 | dps | https://www.pololu.com/file/0J1087/LSM6DS33.pdf | 27.09.2026 | |
| R8.13 | gyro rate noise density | 7 | mdps/√Hz | https://www.pololu.com/file/0J1087/LSM6DS33.pdf | 27.09.2026 | Rn |
| R8.14 | accel noise density | 90 | μg/√Hz | https://www.pololu.com/file/0J1087/LSM6DS33.pdf | 27.09.2026 | FS = ±2 g, ODR = 104 Hz |
| R8.15 | operating temperature | -40 to +85 | °C | https://www.pololu.com/file/0J1087/LSM6DS33.pdf | 27.09.2026 | |

## 9. Wheels: Pololu Wheel 80×10mm Pair – Black (Pololu #1430), qty 2 (one pair)

| row | quantity | value | unit | source URL | retrieved | note |
|---|---|---|---|---|---|---|
| R9.01 | diameter | 80 | mm | https://www.pololu.com/product/1430 | 27.09.2026 | "80 mm (3.15″) in diameter"; spec tab size "80 x 10 mm" |
| R9.02 | width | 10 | mm | https://www.pololu.com/product/1430 | 27.09.2026 | "10 mm (0.4″) wide" |
| R9.03 | mass (weight) | 0.7 | oz | https://www.pololu.com/product/1430/specs | 27.09.2026 | footnote: "Per wheel, including tire." |
| R9.04 | shaft hole | 3 | mm | https://www.pololu.com/product/1430/specs | 27.09.2026 | D-shaped hole for press fit |
| R9.05 | tire | silicone tires | text | https://www.pololu.com/product/1430 | 27.09.2026 | |
| R9.06 | number of wheels in the pair | 2 | count | https://www.pololu.com/product/1430 | 27.09.2026 | "This product is a pair of wheels." |

## 10. Chassis / frame: Balboa chassis (in kit #3575; also sold as #3573 with Stability Conversion Kit) and Bumper Cage Kit (#3574)

| row | quantity | value | unit | source URL | retrieved | note |
|---|---|---|---|---|---|---|
| R10.01 | chassis mass (with stability conversion kit and motors) | 130 | g | https://www.pololu.com/product/3573/specs | 27.09.2026 | "This weight does not include wheels, batteries, or any electronics." Stability Conversion Kit included |
| R10.02 | chassis overall dimensions (with stability conversion kit, 80×10 mm wheels) | 185 × 112 × 80 | mm | https://www.pololu.com/product/3573/specs | 27.09.2026 | |
| R10.03 | bumper cage mass | 35 | g | https://www.pololu.com/product/3574/specs | 27.09.2026 | |
| R10.04 | material | black ABS plastic | text | https://www.pololu.com/product/3573 | 27.09.2026 | "The majority of the chassis is made from black ABS plastic" |
| R10.05 | wheel shaft position | "the gearboxes also position the wheel shafts along the central plane of the battery holder" | text | https://www.pololu.com/product/3573 | 27.09.2026 | |
| R10.06 | ground clearance (80 mm wheels) | "Clearance can be as small as 7mm with chassis tilted." | mm | https://www.pololu.com/file/0J1283/balboa-32u4-balancing-robot-kit-dimensions.pdf | 27.09.2026 | drawing note 2, 80 mm wheel sheet |
| R10.07 | distance between the wheels' outer faces (80 mm wheels) | 112 | mm | https://www.pololu.com/file/0J1283/balboa-32u4-balancing-robot-kit-dimensions.pdf | 27.09.2026 | p. 1 "Top view" (sheet for 80 mm wheels), read from the rendered page; the drawing does not dimension the track centre to centre |
| R10.08 | distance between the wheels' inner faces (80 mm wheels) | 92 | mm | https://www.pololu.com/file/0J1283/balboa-32u4-balancing-robot-kit-dimensions.pdf | 27.09.2026 | p. 1 "Top view" |
| R10.09 | wheel width as drawn | 10 | mm | https://www.pololu.com/file/0J1283/balboa-32u4-balancing-robot-kit-dimensions.pdf | 27.09.2026 | p. 1 "Front view"; the wheel product page gives 10 mm too |
| R10.10 | number of ball bearings | 6 | count | https://www.pololu.com/product/3573 | 27.09.2026 | kit contents: "six 683 ball bearings" |

## 11. Whole robot as assembled (kit #3575)

| row | quantity | value | unit | source URL | retrieved | note |
|---|---|---|---|---|---|---|
| R11.01 | mass (weight) | 200 | g | https://www.pololu.com/product/3575/specs | 27.09.2026 | "Of assembled robot as shown in the main product picture, with motors, 80×10 mm wheels, and bumper cage. This weight does not include batteries." |
| R11.02 | overall height (80 mm wheels) | 118.2 | mm | https://www.pololu.com/file/0J1283/balboa-32u4-balancing-robot-kit-dimensions.pdf | 27.09.2026 | p. 1 "Front view" |
| R11.03 | top of the robot to the top of the wheels (80 mm wheels) | 38.2 | mm | https://www.pololu.com/file/0J1283/balboa-32u4-balancing-robot-kit-dimensions.pdf | 27.09.2026 | p. 1 "Front view" |
| R11.04 | overall dimensions (size) | 118 × 112 × 80 | mm | https://www.pololu.com/product/3575/specs | 27.09.2026 | "Of assembled robot with 80×10 mm wheels (not including bumper cage, which can be installed in a variety of orientations)." |
