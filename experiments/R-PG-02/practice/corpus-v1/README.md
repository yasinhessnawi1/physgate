# Practice set of R-PG-02 (never a result)

Twenty revisions of a labelled stand-in design (the Pololu Balboa 32U4 parts sheet), five errors of each class, each with its clean twin. Tuners read it freely; it is reported, never a result.

## Authors

- Author model: claude-opus-5-5. Reviewer model: claude-sonnet-5; the instrument refuses a reviewer on the author's model string.
- Binary: Claude Code 2.1.301 linux-arm64, sha256 1e119036a802d359ba5f9886428e031586e8796f7a858d5a8ee179ac7b8604f0.
- Sandbox: Read, Write and Edit only, a guard refusing any path outside the session's directory, no web, no settings or MCP servers; proven on the scripted endpoint before any launch.
- Session A (base and clean revisions): af630cec-f1f4-4d41-a1f8-ab9a2f4ed021, 38 turns, stream sha256 23debf83a40e7b1d501cd4cb3ea57555ec90522d7852aadf0e65cb04c3deb9d8.
  - Resumed once with only the base's failing checks (power, conservation) and their messages: 5 turns, stream sha256 c9517bd1c0840df22334bd229658d74486f3b38ca08925db1a8a9ce40f559902.
  - Resumed once with only the base's failing checks (power, conservation) and their messages: 8 turns, stream sha256 32e9bd66b387ab92f59baece5b23a7840b853d64b2391fa0cac8cffc31d774cd.
  - Resumed once with only the base's failing checks (power, conservation) and their messages: 5 turns, stream sha256 6449f8a33277d4a0c34fc5e930f904a19578beae5798c945ac2d5900e8b39f14.
- Session B (errors): c3b63f10-4a3b-4c02-9a0b-6ce72d564de5, 49 turns, stream sha256 fbe83f924deb1de3de8cdbc2282f54d160e00bb2f1eab7e3708930263ab0aa23. It read the base and the clean revisions, never any gate output.
- Secret scans after every session: 0, 0, 0.

## The briefs, frozen for the fresh test set

The fresh test set is written from these exact files, by new sessions launched after the tuning freeze:

- brief_A.md: c418745697029f4b27f73664747cd39b5b00683ec91073d7b09f2143d242d197
- brief_B.md: ade29804997290c061bcb5893ba0cfd346549cff1526b904c12719cd144c87a6
- common/architecture.md: e01e87163eedb3ab490ab3934f640306ef9a489eff374b89c0dab10d0de9f4b9
- common/format.md: edff781039ac7052ed3fa01c1ede661d2ce7c8d64f7ace118f408ae03eb2ea5c
- common/risk_row_1.md: 88ebf436877d2a81f6b10349815f01ba795b0c437614800c19390dbc16d5da09
- common/vocabulary.md: 498ad166a98f3d44c1d72e456d259074c072aa0dbf8f1c69783af6b9bd048a0d
- parts_sheet.md: 29f9568ce8465112ef0b0b164f05f3ba76f9702e3ccbc7a1dea96fbc3d057b3f

## Inconsistencies in the parts sheet

Listed by the source check at assembly, never fixed: the sheet is shared by every set. Listed below.

### Found by the source check (every number of the base and clean patches)

- current_draw of electrical.mcu is 27 mA, and no row at its source gives a number of that kind (https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-7766-8-bit-AVR-ATmega16U4-32U4_Datasheet.pdf) — in the base
- mass of control.balance_loop is 330 g, a difference of parts-sheet rows (derived: [R11.01] - [R10.03] + [R5.07] * [R5.10]) — in 14 places (base, revision a01, revision a02, revision a03, …)
- mass of mechanical.fitted_parts is 35 g, a difference of parts-sheet rows (derived: [R11.01] - [R10.03] - [R10.01]) — in the base
- mass of mechanical.robot is 330 g, a difference of parts-sheet rows (derived: [R11.01] - [R10.03] + [R5.07] * [R5.10]) — in 7 places (base, revision a01, revision a02, revision a03, …)
- mass_without_battery of mechanical.robot is 165 g, a difference of parts-sheet rows (derived: [R11.01] - [R10.03]) — in 7 places (base, revision a01, revision a02, revision a03, …)
- supported_mass of mechanical.drivetrain is 330 g, a difference of parts-sheet rows (derived: [R11.01] - [R10.03] + [R5.07] * [R5.10]) — in 8 places (base, revision a01, revision a02, revision a03, …)
- supported_mass of mechanical.wheel_left is 165 g, a difference of parts-sheet rows (derived: ([R11.01] - [R10.03] + [R5.07] * [R5.10]) / [R9.06]) — in the base
- supported_mass of mechanical.wheel_right is 165 g, a difference of parts-sheet rows (derived: ([R11.01] - [R10.03] + [R5.07] * [R5.10]) / [R9.06]) — in the base
- track_width of mechanical.drivetrain is 102 mm, a difference of parts-sheet rows (derived: [R10.07] - [R9.02]) — in 9 places (base, revision a01, revision a02, revision a03, …)

A difference of rows is the sheet's arithmetic, carried faithfully: wherever the sheet's own
rows disagree (its robot weight against its parts, for example), the design inherits that.
Twins are never edited for it, and the sheet is never changed: every set shares it.
