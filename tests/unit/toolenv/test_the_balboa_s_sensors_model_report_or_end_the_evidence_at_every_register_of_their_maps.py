"""Each register of the LSM6DS33's and the LIS3MDL's maps is modelled, reported or ends the run.

A sensor that acknowledges its address and then answers every register from a plain register
file shows firmware a part that works. The tables below are the two datasheets' register maps
(LSM6DS33 DocID027423 Rev 4, Table 16; LIS3MDL DocID024204 Rev 4, Table 16), written out
independently of the rig, with for each register what the model does with a write and a read:

- modelled: the model acts on it (the outputs, the status, the identity, the control bits it
  keeps), or it is read-only and a write changes nothing, as on the part;
- reported: a write the model does not act on is named in ``unmodelled`` (``lsm6ds33:NAME``,
  ``lis3mdl:NAME``), and the summary's values are then not evaluable;
- ends the evidence: a read of data the model has no value for, or any access to a reserved
  register (the datasheets: "must not be changed"), stops the run's evidence.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from avrsim_node import evaluate

#: A device with its callbacks collected: `reports` (names), `ends` ({cause, ...}).
SCRIPT = """
const imu = await import(`${SRC}/imu.js`);
const reports = [];
const ends = [];
const faults = () => ({ nack: false, stale_since: null, saturated: null });
const sensors = {
  lsm6: new imu.LSM6DS33({ motion: () => ({ pitch_rad: 0, pitch_rate_rad_s: 0 }), raw: () => null,
    faults, onUnmodelled: (what) => reports.push(what),
    onEvidenceEnd: (cause, detail) => ends.push({ cause, ...detail }) }),
  lis3mdl: new imu.LIS3MDL({ faults, onUnmodelled: (what) => reports.push(what),
    onEvidenceEnd: (cause, detail) => ends.push({ cause, ...detail }) }),
};
const sensor = sensors[%(device)s];
const write = (register, value) => {
  sensor.begin(true); sensor.write(register, 0.5); sensor.write(value, 0.5);
};
const read = (register) => {
  sensor.begin(true); sensor.write(register, 0.5); sensor.begin(false); return sensor.read(0.5);
};
const results = [];
for (const [register, how] of %(stimuli)s) {
  reports.length = 0; ends.length = 0;
  const value = how === 'r' ? read(register) : (write(register, how), null);
  results.push({ register, how, value, reports: [...reports], ends: ends.map((e) => ({ ...e })) });
}
out(results);
"""

Row = tuple[int, str, str]

#: LSM6DS33, Table 16 (and the embedded-functions bank, which FUNC_CFG_ACCESS opens: any
#: write to that register is a use the model does not act on). "out": a read-only output the
#: model gives; "status": the identity and status registers; "cfg": a control register (a write
#: of anything but its reset value or its modelled bits is reported); "data": an output the
#: model has no value for; "reserved": the datasheet's reserved addresses.
LSM6: list[Row] = [
    (0x00, "RESERVED", "reserved"),
    (0x01, "FUNC_CFG_ACCESS", "cfg"),
    *[(a, "RESERVED", "reserved") for a in range(0x02, 0x06)],
    (0x06, "FIFO_CTRL1", "cfg"),
    (0x07, "FIFO_CTRL2", "cfg"),
    (0x08, "FIFO_CTRL3", "cfg"),
    (0x09, "FIFO_CTRL4", "cfg"),
    (0x0A, "FIFO_CTRL5", "cfg"),
    (0x0B, "ORIENT_CFG_G", "cfg"),
    (0x0C, "RESERVED", "reserved"),
    (0x0D, "INT1_CTRL", "cfg"),
    (0x0E, "INT2_CTRL", "cfg"),
    (0x0F, "WHO_AM_I", "status"),
    (0x10, "CTRL1_XL", "modelled_cfg"),
    (0x11, "CTRL2_G", "modelled_cfg"),
    (0x12, "CTRL3_C", "cfg"),
    (0x13, "CTRL4_C", "cfg"),
    (0x14, "CTRL5_C", "cfg"),
    (0x15, "CTRL6_C", "cfg"),
    (0x16, "CTRL7_G", "cfg"),
    (0x17, "CTRL8_XL", "cfg"),
    (0x18, "CTRL9_XL", "cfg"),
    (0x19, "CTRL10_C", "cfg"),
    (0x1A, "RESERVED", "reserved"),
    (0x1B, "WAKE_UP_SRC", "data"),
    (0x1C, "TAP_SRC", "data"),
    (0x1D, "D6D_SRC", "data"),
    (0x1E, "STATUS_REG", "status"),
    (0x1F, "RESERVED", "reserved"),
    (0x20, "OUT_TEMP_L", "out"),
    (0x21, "OUT_TEMP_H", "out"),
    *[(a, "OUT_G", "out") for a in range(0x22, 0x28)],
    *[(a, "OUT_XL", "out") for a in range(0x28, 0x2E)],
    *[(a, "RESERVED", "reserved") for a in range(0x2E, 0x3A)],
    *[(a, "FIFO_STATUS", "data") for a in range(0x3A, 0x3E)],
    (0x3E, "FIFO_DATA_OUT_L", "data"),
    (0x3F, "FIFO_DATA_OUT_H", "data"),
    (0x40, "TIMESTAMP0_REG", "data"),
    (0x41, "TIMESTAMP1_REG", "data"),
    (0x42, "TIMESTAMP2_REG", "timestamp"),
    *[(a, "RESERVED", "reserved") for a in range(0x43, 0x49)],
    (0x49, "STEP_TIMESTAMP_L", "data"),
    (0x4A, "STEP_TIMESTAMP_H", "data"),
    (0x4B, "STEP_COUNTER_L", "data"),
    (0x4C, "STEP_COUNTER_H", "data"),
    *[(a, "RESERVED", "reserved") for a in range(0x4D, 0x53)],
    (0x53, "FUNC_SRC", "data"),
    *[(a, "RESERVED", "reserved") for a in range(0x54, 0x58)],
    (0x58, "TAP_CFG", "cfg"),
    (0x59, "TAP_THS_6D", "cfg"),
    (0x5A, "INT_DUR2", "cfg"),
    (0x5B, "WAKE_UP_THS", "cfg"),
    (0x5C, "WAKE_UP_DUR", "cfg"),
    (0x5D, "FREE_FALL", "cfg"),
    (0x5E, "MD1_CFG", "cfg"),
    (0x5F, "MD2_CFG", "cfg"),
    *[(a, "RESERVED", "reserved") for a in range(0x60, 0x80)],
]

#: LIS3MDL, Table 16: the identity is modelled; the control registers are reported when written
#: away from their reset values; the status, outputs, temperature and interrupt source are data
#: the model has no value for.
LIS3MDL: list[Row] = [
    *[(a, "RESERVED", "reserved") for a in range(0x00, 0x0F)],
    (0x0F, "WHO_AM_I", "status"),
    *[(a, "RESERVED", "reserved") for a in range(0x10, 0x20)],
    (0x20, "CTRL_REG1", "cfg"),
    (0x21, "CTRL_REG2", "cfg"),
    (0x22, "CTRL_REG3", "cfg"),
    (0x23, "CTRL_REG4", "cfg"),
    (0x24, "CTRL_REG5", "cfg"),
    (0x25, "RESERVED", "reserved"),
    (0x26, "RESERVED", "reserved"),
    (0x27, "STATUS_REG", "data"),
    *[(a, "OUT", "data") for a in range(0x28, 0x2E)],
    (0x2E, "TEMP_OUT_L", "data"),
    (0x2F, "TEMP_OUT_H", "data"),
    (0x30, "INT_CFG", "cfg"),
    (0x31, "INT_SRC", "data"),
    (0x32, "INT_THS_L", "cfg"),
    (0x33, "INT_THS_H", "cfg"),
    *[(a, "RESERVED", "reserved") for a in range(0x34, 0x80)],
]


def _run(device: str, stimuli: list[list[Any]]) -> dict[tuple[int, str], dict[str, Any]]:
    found = evaluate(SCRIPT % {"device": json.dumps(device), "stimuli": json.dumps(stimuli)})
    return {(item["register"], "r" if item["how"] == "r" else "w"): item for item in found}


def _causes(item: dict[str, Any]) -> list[str]:
    return [e["cause"] for e in item["ends"]]


@pytest.mark.parametrize(
    ("device", "table", "data_cause", "prefix"),
    [
        ("lsm6", LSM6, "lsm6ds33_data", "lsm6ds33"),
        ("lis3mdl", LIS3MDL, "lis3mdl_data", "lis3mdl"),
    ],
)
def test_every_register_of_a_sensor_s_map_is_modelled_reported_or_ends_the_evidence(
    device: str, table: list[Row], data_cause: str, prefix: str
) -> None:
    # The two maps cover every 7-bit register address of the device they list.
    assert [a for a, _, _ in table] == list(range(len(table)))
    stimuli: list[list[Any]] = []
    for address, _, kind in table:
        stimuli.append([address, "r"])
        stimuli.append([address, 0x40 if kind == "modelled_cfg" else 0xFE])
    observed = _run(device, stimuli)
    failing: list[str] = []
    for address, name, kind in table:
        where = f"{address:#04x} {name}"
        read, written = observed[(address, "r")], observed[(address, "w")]
        # A read: data the model has no value for, a reserved register, and a timestamp's
        # counter end the evidence; the rest reads what the model gives.
        if kind in ("reserved", "data", "timestamp"):
            if _causes(read) != [data_cause] or read["ends"][0]["register"] != address:
                failing.append(f"read {where}: ended {read['ends']}")
        elif read["ends"] or read["reports"]:
            failing.append(f"read {where}: reported {read['reports']} ended {read['ends']}")
        # A write: a reserved register ends the evidence, a control register the model does not
        # act on is reported, and the rest changes nothing, as on the part.
        if kind == "reserved":
            if _causes(written) != [data_cause]:
                failing.append(f"write {where}: ended {written['ends']}")
        elif kind in ("cfg", "timestamp"):
            if written["reports"] != [f"{prefix}:{_name(address, name)}"] or written["ends"]:
                failing.append(f"write {where}: reported {written['reports']} {written['ends']}")
        elif written["reports"] or written["ends"]:
            failing.append(f"write {where}: reported {written['reports']} {written['ends']}")
    assert not failing, "\n" + "\n".join(failing)


def _name(address: int, name: str) -> str:
    """The name a report gives a register: the datasheet's, or its hex address."""
    return name if name != "RESERVED" else f"0x{address:02x}"


def test_the_identities_and_the_modelled_outputs_read_what_the_model_gives() -> None:
    lsm6 = _run("lsm6", [[0x0F, "r"], [0x1E, "r"], [0x20, "r"], [0x22, "r"], [0x28, "r"]])
    lis3mdl = _run("lis3mdl", [[0x0F, "r"]])
    assert lsm6[(0x0F, "r")]["value"] == 0x69 and lis3mdl[(0x0F, "r")]["value"] == 0x3D
    for key, item in lsm6.items():
        assert not item["ends"] and not item["reports"], key


def test_a_control_register_written_with_its_reset_value_is_not_a_use() -> None:
    # CTRL_REG1 resets to 0x10 and CTRL_REG3 (power-down) to 0x03: writing them back changes
    # nothing the model shows; any other value is firmware setting the part up.
    back = _run("lis3mdl", [[0x20, 0x10], [0x21, 0x00]])
    assert [back[(a, "w")]["reports"] for a in (0x20, 0x21)] == [[], []]
    back = _run("lis3mdl", [[0x22, 0x03]])
    assert back[(0x22, "w")]["reports"] == []
    other = _run("lis3mdl", [[0x22, 0x00]])
    assert other[(0x22, "w")]["reports"] == ["lis3mdl:CTRL_REG3"]
