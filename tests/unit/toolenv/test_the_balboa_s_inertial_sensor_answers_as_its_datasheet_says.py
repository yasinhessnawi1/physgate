"""The simulator's LSM6DS33 answers on the bus as the part's datasheet says it does.

The board model's inertial sensor is a register file with a sub-address pointer, given the time
with every bus step. What firmware reads from it is the scenario's motion at the sensor's own
sample instants, scaled by the full scale the firmware configured, through the Balboa library's
own axis convention (the balancing example's angle rate is +g.y, its angle atan2(a.z, a.x)).
Each fault the scenario can inject changes exactly what it names.
"""

from __future__ import annotations

import math
from typing import Any

from avrsim_node import evaluate

#: A sensor whose motion, raw override and faults are given as JavaScript expressions of `t`.
SENSOR = """
const imu = await import(`${SRC}/imu.js`);
const writes = [];
const motion = (t) => ({ pitch_rad: %(pitch)s, pitch_rate_rad_s: %(rate)s });
const faults = (t) => (%(faults)s);
const sensor = new imu.LSM6DS33({ motion, raw: (t) => (%(raw)s), faults,
  onWrite: (r, v, t) => writes.push([r, v]) });
const write = (register, values, t) => {
  sensor.begin(true); sensor.write(register, t); for (const v of values) sensor.write(v, t);
};
const read = (register, n, t) => {
  sensor.begin(true); sensor.write(register, t); sensor.begin(false);
  return Array.from({ length: n }, () => sensor.read(t));
};
const int16 = (lo, hi) => ((hi << 8) | lo) << 16 >> 16;
%(body)s
"""

NO_FAULT = "{ nack: false, stale_since: null, saturated: null }"


def _run(
    body: str, *, pitch: str = "0", rate: str = "0", faults: str = NO_FAULT, raw: str = "null"
) -> Any:
    return evaluate(
        SENSOR % {"pitch": pitch, "rate": rate, "faults": faults, "raw": raw, "body": body}
    )


def test_who_am_i_is_0x69_and_the_magnetometer_s_is_0x3d() -> None:
    found = _run(
        """
        const mag = new imu.LIS3MDL({ faults });
        mag.begin(true); mag.write(0x0f); mag.begin(false);
        out({ lsm6: read(0x0f, 1, 0)[0], lis3mdl: mag.read(),
              addresses: [imu.LSM6DS33_ADDRESS, imu.LIS3MDL_ADDRESS] });
        """
    )
    assert found == {"lsm6": 0x69, "lis3mdl": 0x3D, "addresses": [0x6B, 0x1E]}


def test_the_gyroscope_s_pitch_rate_is_its_y_axis_at_the_configured_full_scale() -> None:
    # CTRL2_G = 0x58: 208 Hz, 1000 dps, 35 mdps per count; 0x52 adds FS_125: 4.375 mdps.
    found = _run(
        """
        write(0x11, [0x58], 0);
        const g = read(0x22, 6, 0.1);
        write(0x11, [0x52], 0.2);
        const g125 = read(0x22, 6, 0.3);
        out({ x: int16(g[0], g[1]), y: int16(g[2], g[3]), z: int16(g[4], g[5]),
              y125: int16(g125[2], g125[3]) });
        """,
        rate="0.1",
    )
    dps = math.degrees(0.1)
    assert found == {"x": 0, "y": round(dps * 1000 / 35), "z": 0, "y125": round(dps * 1000 / 4.375)}


def test_the_accelerometer_reads_gravity_along_x_upright_and_along_z_at_a_right_angle() -> None:
    # CTRL1_XL = 0x40: 104 Hz, +-2 g, 0.061 mg per count; 0x44: +-16 g, 0.488 mg per count.
    found = _run(
        """
        write(0x10, [0x40], 0);
        const upright = read(0x28, 6, 0.1);
        const flat = read(0x28, 6, 0.6);
        write(0x10, [0x44], 0.7);
        const coarse = read(0x28, 6, 0.8);
        const axes = (a) => [int16(a[0], a[1]), int16(a[2], a[3]), int16(a[4], a[5])];
        out([upright, flat, coarse].map(axes));
        """,
        pitch="t < 0.5 ? 0 : Math.PI / 2",
    )
    assert found == [
        [round(1000 / 0.061), 0, 0],
        [round(math.cos(math.pi / 2) * 1000 / 0.061), 0, round(1000 / 0.061)],
        [0, 0, round(1000 / 0.488)],
    ]


def test_an_output_is_the_sample_taken_at_its_own_instant_and_data_ready_says_when_one_is_new() -> (
    None
):
    # 208 Hz from t = 0: sample k is taken at k / 208. The pitch rate rises with time, so the
    # value read tells which instant was sampled.
    found = _run(
        """
        write(0x11, [0x58], 0);
        const status = (t) => read(0x1e, 1, t)[0] & 0x02;
        const before = status(0.999 / 208);
        const after = status(1.001 / 208);
        const y = (t) => { const g = read(0x22, 6, t); return int16(g[2], g[3]); };
        const first = y(1.5 / 208);
        const cleared = status(1.6 / 208);
        const again = status(2.01 / 208);
        const second = y(2.5 / 208);
        out({ before, after, first, cleared, again, second });
        """,
        rate="t * 100",
    )

    def counts(t: float) -> int:
        return round(math.degrees(t * 100) * 1000 / 35)

    assert found == {
        "before": 0,
        "after": 2,
        "first": counts(1 / 208),
        "cleared": 0,
        "again": 2,
        "second": counts(2 / 208),
    }


def test_a_burst_read_takes_one_sample_and_auto_increment_can_be_switched_off() -> None:
    found = _run(
        """
        write(0x11, [0x58], 0);
        sensor.begin(true); sensor.write(0x24, 0); sensor.begin(false);
        const lo = sensor.read(1 + 0.5 / 208);   // OUTY_L_G of the sample taken at t = 1 ...
        const hi = sensor.read(10);              // ... and its high byte, read much later
        write(0x12, [0x00], 11);                 // CTRL3_C: IF_INC off
        const same = read(0x0f, 3, 11);
        out({ burst: [lo, hi], same, ctrl3: read(0x12, 1, 12)[0] });
        """,
        rate="t",
    )
    counts = round(math.degrees(1) * 1000 / 35)
    assert found["burst"] == [counts & 0xFF, counts >> 8]
    assert found["same"] == [0x69, 0x69, 0x69]
    assert found["ctrl3"] == 0x00


def test_a_stale_sensor_holds_its_last_sample_and_never_says_data_is_ready() -> None:
    found = _run(
        """
        write(0x11, [0x58], 0);
        const y = (t) => { const g = read(0x22, 6, t); return int16(g[2], g[3]); };
        const status = (t) => read(0x1e, 1, t)[0] & 0x02;
        const live = y(0.4);
        out({ live, held: [y(0.6), y(0.9)], ready: [status(0.6), status(0.9)], after: y(1.2),
              readyAfter: status(1.3) });
        """,
        rate="t",
        faults="{ nack: false, stale_since: t >= 0.5 && t < 1.0 ? 0.5 : null, saturated: null }",
    )

    def sample(k: int) -> int:
        return round(math.degrees(k / 208) * 1000 / 35)

    assert found["live"] == sample(math.floor(0.4 * 208))
    assert found["held"] == [sample(math.floor(0.5 * 208))] * 2
    assert found["ready"] == [0, 0]
    assert found["after"] == sample(math.floor(1.2 * 208))
    assert found["readyAfter"] == 2


def test_a_saturated_sensor_reads_the_end_of_its_range_with_the_true_sign() -> None:
    found = _run(
        """
        write(0x11, [0x58], 0); write(0x10, [0x40], 0);
        const g = read(0x22, 6, 0.1); const a = read(0x28, 6, 0.1);
        const axes = (b) => [0, 2, 4].map((i) => int16(b[i], b[i + 1]));
        out({ gyro: axes(g), accel: axes(a) });
        """,
        rate="-0.2",
        faults="{ nack: false, stale_since: null, saturated: 'gyro' }",
    )
    assert found == {"gyro": [32767, -32768, 32767], "accel": [round(1000 / 0.061), 0, 0]}


def test_a_nack_fault_is_the_part_not_acknowledging_while_it_lasts() -> None:
    found = _run(
        "out([0.1, 0.3, 0.6].map((t) => sensor.acknowledges(t)));",
        faults="{ nack: t >= 0.2 && t < 0.5, stale_since: null, saturated: null }",
    )
    assert found == [True, False, True]


def test_raw_counts_replace_the_outputs_from_their_time_whatever_the_full_scale() -> None:
    found = _run(
        """
        write(0x11, [0x5c], 0); write(0x10, [0x4c], 0);
        const g = read(0x22, 6, 0.6); const a = read(0x28, 6, 0.6);
        const axes = (b) => [0, 2, 4].map((i) => int16(b[i], b[i + 1]));
        out(axes(g).concat(axes(a)));
        """,
        raw="t >= 0.5 ? { gyro: [1, -1234, 5], accel: [16000, -2, 300] } : null",
    )
    assert found == [1, -1234, 5, 16000, -2, 300]


def test_a_software_reset_returns_the_registers_and_read_only_ones_keep_their_value() -> None:
    found = _run(
        """
        write(0x11, [0x58], 0); write(0x12, [0x44], 0);
        write(0x0f, [0x00], 0);                  // WHO_AM_I is read-only
        const before = [read(0x11, 1, 0)[0], read(0x12, 1, 0)[0], read(0x0f, 1, 0)[0]];
        write(0x12, [0x05], 0.1);                // SW_RESET
        const after = [read(0x11, 1, 0.2)[0], read(0x12, 1, 0.2)[0], read(0x1e, 1, 0.2)[0]];
        out({ before, after, writes: writes.map(([r, v]) => [r, v]) });
        """
    )
    assert found["before"] == [0x58, 0x44, 0x69]
    assert found["after"] == [0x00, 0x04, 0x00]
    assert found["writes"] == [[0x11, 0x58], [0x12, 0x44], [0x0F, 0x00], [0x12, 0x05]]
