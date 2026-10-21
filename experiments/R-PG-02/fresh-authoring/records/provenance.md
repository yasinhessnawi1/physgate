# Fresh test set of R-PG-02 (the primary result)

Forty revisions of a labelled stand-in design (the Pololu Balboa 32U4 parts sheet), ten errors of each class, each with its clean twin, written by one author pair in two batches of twenty after the tuning freeze. Nobody read it before its run.

## Authors

- Author model: claude-opus-5-5, on the subscription. Reviewer model: claude-sonnet-5.
- Binary: Claude Code 2.1.301 linux-arm64, sha256 1e119036a802d359ba5f9886428e031586e8796f7a858d5a8ee179ac7b8604f0.
- Sandbox: Read, Write and Edit only, a guard refusing any path outside the session's directory, no web, no settings or MCP servers; proven on the scripted endpoint before any launch, and audited from each stream after it.
- Session A (base and clean revisions): e2d800d4-bc5d-484a-979e-f7d039df43b3, 30 turns, stream sha256 0c0d9805b5ebc2a4088a71c89d54b073167278038566ab5b7114308a2ed96684, secret scan {'token_value': 0, 'sk_ant_prefix': 0, 'oat_prefix': 0, 'files_scanned': 43}.
  - Resumed (cont) with a message of sha256 4cef18d7bfa374d779b9c0888e9f181e5597d6f221e1ebcfbfeb4151dc47cd4a: 22 turns, stream sha256 ca15246c8df8a330eb0d7e78014f8b4c67cffff9d3eaca72ba6aee84dd0a183a, secret scan {'token_value': 0, 'sk_ant_prefix': 0, 'oat_prefix': 0, 'files_scanned': 67}.
  - Resumed (facts1) with a message of sha256 4cec732eb51b1cbc7040c59061177197bc0c7195cb386f752b276fa7bf243423: 76 turns, stream sha256 ad69d617c6e8badc2f0b37f116447412d6528279c6c42a73679355ab809a993c, secret scan {'token_value': 0, 'sk_ant_prefix': 0, 'oat_prefix': 0, 'files_scanned': 70}.
  - Resumed (facts2) with a message of sha256 9eeb28d16bddd58374b49ce350d91594ba232f2a03e17c4ddc41ef1e56173872: 52 turns, stream sha256 594f3379bad3e619bf4d145d0828e0d2cec3a17949aee1cb335c7c02d39d120c, secret scan {'token_value': 0, 'sk_ant_prefix': 0, 'oat_prefix': 0, 'files_scanned': 73}.
- Session B (errors; never shown any gate output): e268c6a4-9081-45ec-92dc-f7f6974de18a, 49 turns, stream sha256 97571adc5f4e345da77c12ce2dd7ceaf91e9760e3db8e73f93bae15e75e43d0f, secret scan {'token_value': 0, 'sk_ant_prefix': 0, 'oat_prefix': 0, 'files_scanned': 63}.
  - Resumed (cont) with a message of sha256 660015c32f04093d78e3a6bf39747d2e7dc2eb0c938301b9acc84fc64e7bff2b: 42 turns, stream sha256 dfebeb822a37efee7801e7b9f129a72b2644c5dfd0e057143106cc4f304e7b12, secret scan {'token_value': 0, 'sk_ant_prefix': 0, 'oat_prefix': 0, 'files_scanned': 108}.

## The briefs and the two continuation messages

The briefs are the practice set's, frozen by their sha256 before the practice set was written:

- brief_A.md: c418745697029f4b27f73664747cd39b5b00683ec91073d7b09f2143d242d197
- brief_B.md: ade29804997290c061bcb5893ba0cfd346549cff1526b904c12719cd144c87a6
- common/architecture.md: e01e87163eedb3ab490ab3934f640306ef9a489eff374b89c0dab10d0de9f4b9
- common/format.md: edff781039ac7052ed3fa01c1ede661d2ce7c8d64f7ace118f408ae03eb2ea5c
- common/risk_row_1.md: 88ebf436877d2a81f6b10349815f01ba795b0c437614800c19390dbc16d5da09
- common/vocabulary.md: 498ad166a98f3d44c1d72e456d259074c072aa0dbf8f1c69783af6b9bd048a0d
- parts_sheet.md: 29f9568ce8465112ef0b0b164f05f3ba76f9702e3ccbc7a1dea96fbc3d057b3f

Each session was resumed once with a fixed continuation message for revisions 21 to 40:

- continue_A.txt: 4cef18d7bfa374d779b9c0888e9f181e5597d6f221e1ebcfbfeb4151dc47cd4a
- continue_B.txt: 660015c32f04093d78e3a6bf39747d2e7dc2eb0c938301b9acc84fc64e7bff2b

## Inconsistencies in the parts sheet

Listed by the source check at assembly, never fixed: the sheet is shared by every set.

### Found by the source check (every number of the base and clean patches)

- board_lateral_clearance of mechanical.chassis is 22.9 mm, a difference of parts-sheet rows (derived: [R10.08] - [R7.12]) — in 1 places (revision a23)
- current_draw of electrical.mcu is 27 mA, and no row at its source gives a number of that kind (https://ww1.microchip.com/downloads/en/DeviceDoc/Atmel-7766-8-bit-AVR-ATmega16U4-32U4_Datasheet.pdf) — in 2 places (revision a30, base)
- current_limit of electrical.driver_left is 1.8 A, and no row at its source gives a number of that kind (https://www.ti.com/lit/ds/symlink/drv8838.pdf) — in 9 places (revision a01, revision a02, revision a08, revision a18, …)
- current_limit of electrical.driver_right is 1.8 A, and no row at its source gives a number of that kind (https://www.ti.com/lit/ds/symlink/drv8838.pdf) — in 9 places (revision a01, revision a02, revision a08, revision a18, …)
- current_limit of electrical.regulator_5v is 2 A, and no row at its source gives a number of that kind (https://www.pololu.com/product/3575) — in 10 places (revision a09, revision a10, revision a11, revision a12, …)
- efficiency_point_heat_dissipation of electrical.motor_left is 1.72 W, a difference of parts-sheet rows (derived: [R1.01] * [R1.19] - [R1.20]) — in 1 places (revision a18)
- efficiency_point_heat_dissipation of electrical.motor_right is 1.72 W, a difference of parts-sheet rows (derived: [R1.01] * [R1.19] - [R1.20]) — in 1 places (revision a18)
- mass of mechanical.assembly is 330 g, a difference of parts-sheet rows (derived: [R11.01] - [R10.03] + [R5.07] * [R5.10]) — in 9 places (revision a01, revision a02, revision a21, revision a23, …)
- mass of mechanical.chassis is 165 g, a difference of parts-sheet rows (derived: [R11.01] - [R10.03]) — in 14 places (revision a01, revision a02, revision a03, revision a04, …)
- mass of mechanical.frame_and_board is 106 g, a difference of parts-sheet rows (derived: [R11.01] - [R10.03] - [R9.03] * [R9.06] - [R1.21] * [R1.25]) — in the base
- plant_mass of control.balance_loop is 330 g, a difference of parts-sheet rows (derived: [R11.01] - [R10.03] + [R5.07] * [R5.10]) — in 32 places (revision a01, revision a02, revision a03, revision a04, …)
- supply_voltage_margin of electrical.mcu is 1 V, a difference of parts-sheet rows (derived: [R7.09] - [R7.03]) — in 1 places (revision a30)
- unladen_mass of mechanical.assembly is 165 g, a difference of parts-sheet rows (derived: [R11.01] - [R10.03]) — in 10 places (revision a01, revision a02, revision a08, revision a21, …)
- wheel_top_height of mechanical.assembly is 80 mm, a difference of parts-sheet rows (derived: [R11.02] - [R11.03]) — in 1 places (revision a29)

A difference of rows is the sheet's arithmetic, carried faithfully: wherever the sheet's own
rows disagree (its robot weight against its parts, for example), the design inherits that.
Twins are never edited for it, and the sheet is never changed: every set shares it.
