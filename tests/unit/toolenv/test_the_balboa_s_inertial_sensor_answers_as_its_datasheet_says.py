"""The simulator's LSM6DS33 answers on the bus as the part's datasheet says it does.

The board model's inertial sensor is a register file with a sub-address pointer, given the time
with every bus step. What firmware reads from it is the scenario's motion at the sensor's own
sample instants, scaled by the full scale the firmware configured, through the Balboa library's
own axis convention (the balancing example's angle rate is +g.y, its angle atan2(a.z, a.x)).
Each fault the scenario can inject changes exactly what it names. What the part does while it
turns on and settles, and how a read spanning a sample's update is put together, follow ST's
LSM6DS33 datasheet (DocID025725) and its application note AN4682 (DocID027736).
"""

from __future__ import annotations

import json
import math
from typing import Any

from avrsim_node import evaluate

#: A sensor whose motion, raw override and faults are given as JavaScript expressions of `t`.
SENSOR = """
const imu = await import(`${SRC}/imu.js`);
const writes = [];
const motion = (t) => ({ pitch_rad: %(pitch)s, pitch_rate_rad_s: %(rate)s });
const faults = (t) => (%(faults)s);
const unmodelled = [];
const instants = [];
const sensor = new imu.LSM6DS33({ motion, raw: (t) => (%(raw)s), faults,
  onWrite: (r, v, t) => writes.push([r, v]), onUnmodelled: (what) => unmodelled.push(what),
  onOutputRead: (which, instant) => instants.push([which, instant * 208]) });
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
    # 208 Hz from t = 0: sample k is taken at k / 208 (well after the turn-on). The pitch rate
    # rises with time, so the value read tells which instant was sampled.
    found = _run(
        """
        write(0x11, [0x58], 0);
        read(0x22, 6, 29.5 / 208);
        const status = (t) => read(0x1e, 1, t)[0] & 0x02;
        const before = status(29.999 / 208);
        const after = status(30.001 / 208);
        const y = (t) => { const g = read(0x22, 6, t); return int16(g[2], g[3]); };
        const first = y(30.5 / 208);
        const cleared = status(30.6 / 208);
        const again = status(31.01 / 208);
        const second = y(31.5 / 208);
        out({ before, after, first, cleared, again, second });
        """,
        rate="t * 100",
    )

    def counts(t: float) -> int:
        return round(math.degrees(t * 100) * 1000 / 35)

    assert found == {
        "before": 0,
        "after": 2,
        "first": counts(30 / 208),
        "cleared": 0,
        "again": 2,
        "second": counts(31 / 208),
    }


def test_with_bdu_0_a_read_spanning_an_update_mixes_two_samples_and_with_bdu_1_it_cannot() -> None:
    # Datasheet Table 50, CTRL3_C BDU: "0: continuous update; 1: output registers not updated
    # until MSB and LSB have been read"; AN4682 section 3.4: BDU keeps an axis' two bytes to one
    # sample, while "X and Y can be read at T1 and Z sampled at T2". The rate is t * 4000 rad/s at
    # 2000 dps, so samples 40 and 41 differ by more than one count of the high byte.
    found = _run(
        """
        write(0x11, [0x5c], 0);                      // 208 Hz, 2000 dps
        const span = (bdu) => {
          write(0x12, [bdu ? 0x44 : 0x04], 0);
          sensor.begin(true); sensor.write(0x22, 0); sensor.begin(false);
          const t = (k) => k / 208;
          const x = [sensor.read(t(40.5)), sensor.read(t(40.5))];     // X pair, sample 40
          const yLow = sensor.read(t(40.9));                          // Y low byte: sample 40
          const yHigh = sensor.read(t(41.1));                         // Y high byte after 41
          const z = [sensor.read(t(41.2)), sensor.read(t(41.2))];     // Z pair, sample 41
          return { x, y: [yLow, yHigh], z };
        };
        const continuous = span(false), blocked = span(true);
        write(0x12, [0x00], 50);                     // IF_INC off
        const same = read(0x0f, 3, 50);
        out({ continuous, blocked, same, ctrl3: read(0x12, 1, 51)[0] });
        """,
        rate="t * 100",
    )

    def counts(k: int) -> int:
        return round(math.degrees(k / 208 * 100) * 1000 / 70) & 0xFFFF

    y40, y41 = counts(40), counts(41)
    assert y40 >> 8 != y41 >> 8
    assert found["continuous"]["y"] == [y40 & 0xFF, y41 >> 8]  # torn: two samples' bytes
    assert found["blocked"]["y"] == [y40 & 0xFF, y40 >> 8]  # held to sample 40's pair
    for case in ("continuous", "blocked"):  # the other axes update either way
        assert found[case]["x"] == [0, 0] and found[case]["z"] == [0, 0]
    assert found["same"] == [0x69, 0x69, 0x69]
    assert found["ctrl3"] == 0x00


def test_with_bdu_1_an_axis_read_only_by_its_low_byte_keeps_its_sample_until_the_high_one() -> None:
    found = _run(
        """
        write(0x11, [0x5c], 0); write(0x12, [0x44], 0);
        const low = (t) => { sensor.begin(true); sensor.write(0x24, t); sensor.begin(false);
          return sensor.read(t); };
        const high = (t) => { sensor.begin(true); sensor.write(0x25, t); sensor.begin(false);
          return sensor.read(t); };
        const a = low(40.5 / 208), b = low(45.5 / 208);   // the pair is held at sample 40
        const h = high(46.5 / 208);                      // its high byte frees it
        const c = low(47.5 / 208);
        out({ a, b, h, c });
        """,
        rate="t * 100",
    )

    def counts(k: int) -> int:
        return round(math.degrees(k / 208 * 100) * 1000 / 70) & 0xFFFF

    assert found == {
        "a": counts(40) & 0xFF,
        "b": counts(40) & 0xFF,
        "h": counts(40) >> 8,
        "c": counts(47) & 0xFF,
    }


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


def test_a_saturated_axis_reads_the_end_of_its_range_with_its_input_s_sign_and_no_other_does() -> (
    None
):
    # Datasheet "Mechanical characteristics", FS: an output clips at full scale on the axis that is
    # over its range. The fault names its sensor and axes; only those clip.
    def saturated(sensor: str, axes: list[str]) -> Any:
        return _run(
            """
            write(0x11, [0x58], 0); write(0x10, [0x40], 0);
            const g = read(0x22, 6, 0.2); const a = read(0x28, 6, 0.2);
            const axes = (b) => [0, 2, 4].map((i) => int16(b[i], b[i + 1]));
            out({ gyro: axes(g), accel: axes(a) });
            """,
            rate="-0.2",
            pitch="Math.PI / 6",
            faults="{ nack: false, stale_since: null, saturated: "
            + json.dumps({"sensor": sensor, "axes": axes})
            + " }",
        )

    y = round(math.degrees(-0.2) * 1000 / 35)
    ax, az = (
        round(math.cos(math.pi / 6) * 1000 / 0.061),
        round(math.sin(math.pi / 6) * 1000 / 0.061),
    )
    assert saturated("gyro", ["y"]) == {"gyro": [0, -32768, 0], "accel": [ax, 0, az]}
    assert saturated("gyro", ["x", "y"]) == {"gyro": [32767, -32768, 0], "accel": [ax, 0, az]}
    assert saturated("accel", ["z"]) == {"gyro": [0, y, 0], "accel": [ax, 0, 32767]}
    assert saturated("both", ["y", "z"]) == {
        "gyro": [0, -32768, 32767],
        "accel": [ax, 32767, 32767],
    }


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


def test_every_full_scale_reads_at_its_own_sensitivity() -> None:
    # FS_G 00..11: 245, 500, 1000, 2000 dps; FS_XL 00..11: 2, 16, 4, 8 g (that order).
    found = _run(
        """
        const y = (t) => { const g = read(0x22, 6, t); return int16(g[2], g[3]); };
        const z = (t) => { const a = read(0x28, 6, t); return int16(a[4], a[5]); };
        const scaled = (register, base, value) => [0, 1, 2, 3].map((fs, i) => {
          write(register, [base | (fs << 2)], i); return value(i + 0.5); });
        const gyro = scaled(0x11, 0x50, y);
        const accel = scaled(0x10, 0x40, z);
        out({ gyro, accel });
        """,
        rate="0.5",
        pitch="Math.PI / 2",
    )
    dps = math.degrees(0.5)
    assert found == {
        "gyro": [round(dps * 1000 / mdps) for mdps in (8.75, 17.5, 35, 70)],
        "accel": [round(1000 / mg) for mg in (0.061, 0.488, 0.122, 0.244)],
    }


#: Every ODR code (CTRL1_XL and CTRL2_G bits 7:4) and its rate in Hz.
RATES = {1: 12.5, 2: 26, 3: 52, 4: 104, 5: 208, 6: 416, 7: 833, 8: 1660, 9: 3330, 10: 6660}


def test_each_output_data_rate_takes_its_samples_at_its_own_period() -> None:
    # Code c is set at 10 c s; well after it, sample k (taken at 10 c + k / ODR) is not ready a
    # thousandth of a period before its instant and is just after, once sample k - 1 was read.
    # The gyroscope stops at 1.66 kHz: its codes 9 and 10 are power-down.
    found = _run(
        """
        const rates = RATES;
        const ready = (register, bit, outputs) => Object.entries(rates).map(([code, odr]) => {
          const t0 = 10 * code, k = Math.floor(odr) + 1;
          write(register, [code << 4], t0);
          read(outputs, 6, t0 + (k - 0.5) / odr);
          const status = (t) => read(0x1e, 1, t)[0] & bit;
          return [status(t0 + (k - 0.001) / odr), status(t0 + (k + 0.001) / odr)];
        });
        out({ accel: ready(0x10, 0x01, 0x28), gyro: ready(0x11, 0x02, 0x22) });
        """.replace("RATES", json.dumps(RATES))
    )
    assert found == {
        "accel": [[0, 1]] * 10,
        "gyro": [[0, 2]] * 8 + [[0, 0]] * 2,
    }


def test_a_sample_is_ready_at_its_own_instant_to_the_last_bit_of_the_time() -> None:
    # At 208 Hz, 60 / 208 * 208 falls just short of 60 in floating point; sample 60 is still due.
    found = _run(
        """
        write(0x11, [0x50], 0);
        read(0x22, 6, 59.5 / 208);
        out(read(0x1e, 1, 60 / 208)[0] & 0x02);
        """
    )
    assert found == 0x02


def test_changing_only_the_full_scale_keeps_the_sampling_instants() -> None:
    found = _run(
        """
        write(0x11, [0x58], 0);
        read(0x22, 6, 100.5 / 208);
        write(0x11, [0x5c], 100.6 / 208);                    // 2000 dps, the same 208 Hz
        const status = (t) => read(0x1e, 1, t)[0] & 0x02;
        out([status(100.999 / 208), status(101.001 / 208)]);
        """
    )
    assert found == [0, 2]


def test_a_stale_sensor_says_no_data_is_ready_even_before_its_held_sample_is_read() -> None:
    found = _run(
        """
        write(0x11, [0x58], 0);
        read(0x22, 6, 0.4);
        out(read(0x1e, 1, 0.6)[0] & 0x02);
        """,
        faults="{ nack: false, stale_since: t >= 0.5 && t < 1.0 ? 0.5 : null, saturated: null }",
    )
    assert found == 0


def test_the_status_register_shows_each_new_sample_and_the_counts_each_sample_read() -> None:
    found = _run(
        """
        write(0x11, [0x50], 0); write(0x10, [0x40], 0);      // 208 Hz and 104 Hz
        const status = read(0x1e, 1, 0.5)[0];
        for (const t of [0.5, 0.501, 0.51, 0.52]) { read(0x22, 6, t); read(0x28, 6, t); }
        out({ status, counts: sensor.counts });
        """
    )
    # Before any temperature read, TDA is set beside GDA and XLDA. The read at 0.501 s finds no
    # sample newer than the one read at 0.5 s; those at 0.51 and 0.52 s each find a new one.
    assert found == {
        "status": 0x07,
        "counts": {
            "whoami_reads": 0,
            "gyro_samples_read": 3,
            "accel_samples_read": 3,
            "invalid_samples_read": {"gyro": 0, "accel": 0},
            "read_before_any_sample": {"gyro": 0, "accel": 0},
        },
    }


def test_ctrl3_c_s_reboot_bit_clears_itself() -> None:
    found = _run("write(0x12, [0x84], 0); out(read(0x12, 1, 0)[0]);")
    assert found == 0x04


def test_the_magnetometer_s_address_increments_only_with_its_top_bit_set() -> None:
    found = _run(
        """
        const mag = new imu.LIS3MDL({ faults });
        mag.begin(true); mag.write(0x80 | 0x20); mag.write(1); mag.write(2);
        const reads = (pointer) => { mag.begin(true); mag.write(pointer); mag.begin(false);
          return [mag.read(), mag.read()]; };
        out({ plain: reads(0x20), incremented: reads(0x80 | 0x20) });
        """
    )
    assert found == {"plain": [1, 1], "incremented": [1, 2]}


def test_the_gyroscope_takes_no_sample_in_its_80_ms_turn_on_and_its_first_ones_are_invalid() -> (
    None
):
    # AN4682 Table 16: power-down to an active mode, 80 ms at most; Table 17: at 208 Hz two
    # samples to discard after it and after any ODR change (four at 1.66 kHz). Sample k is at
    # k / 208 s: none before 80 ms (k < 17); 17 and 18 invalid; 19 the first valid. Before the
    # first sample and for one to discard the outputs read the end of the range opposite the
    # input (the documents give no value; the rig's conservative choice).
    found = _run(
        """
        write(0x11, [0x58], 0);
        const status = (t) => read(0x1e, 1, t)[0] & 0x02;
        const y = (t) => { const g = read(0x22, 6, t); return int16(g[2], g[3]); };
        const k = (n) => (n + 0.5) / 208;
        const turningOn = [status(k(16)), y(k(16))];
        const discarded = [status(k(17)), y(k(17)), status(k(18)), y(k(18))];
        const valid = [status(k(19)), y(k(19))];
        const invalidAfterOn = { ...sensor.counts.invalid_samples_read };
        write(0x11, [0x88], 1);                       // 1.66 kHz: an ODR change
        const m = (n) => 1 + (n + 0.5) / 1660;
        const changed = [1, 2, 3, 4, 5].map((n) => y(m(n)));
        out({ turningOn, discarded, valid, invalidAfterOn, changed,
              invalid: sensor.counts.invalid_samples_read });
        """,
        rate="0.5",
    )
    y = round(math.degrees(0.5) * 1000 / 35)
    assert found["turningOn"] == [0, -32768]
    assert found["discarded"] == [2, -32768, 2, -32768]
    assert found["valid"] == [2, y]
    assert found["invalidAfterOn"] == {"gyro": 2, "accel": 0}
    assert found["changed"] == [-32768, -32768, -32768, -32768, y]
    assert found["invalid"] == {"gyro": 6, "accel": 0}


def test_data_ready_is_masked_for_the_samples_to_discard_when_drdy_mask_is_set() -> None:
    # AN4682 section 2.7.1: with CTRL4_C's DRDY_MASK set, "data-ready signals are masked until
    # the settling of the sensor filters is completed".
    found = _run(
        """
        write(0x13, [0x08], 0); write(0x11, [0x58], 0);
        const status = (t) => read(0x1e, 1, t)[0] & 0x02;
        out([16, 17, 18, 19].map((n) => status((n + 0.5) / 208)));
        """
    )
    assert found == [0, 0, 0, 2]


def test_the_accelerometer_discards_table_12_s_samples_in_high_performance_mode_only() -> None:
    # AN4682 Table 12 (high-performance mode): at 104 Hz with the bandwidth the ODR sets (50 Hz,
    # datasheet Table 45) two samples are discarded; with XL_BW_SCAL_ODR and BW_XL = 400 Hz one.
    # In normal mode (CTRL6_C XL_HM_MODE set, 104 Hz) the first sample is correct (Table 11).
    def first_three(setup: str) -> Any:
        return _run(
            setup
            + """
            const x = (t) => { const a = read(0x28, 6, t); return int16(a[0], a[1]); };
            out([1, 2, 3].map((n) => x((n + 0.5) / 104)));
            """
        )

    g = round(1000 / 0.061)
    assert first_three("write(0x10, [0x40], 0);") == [-32768, -32768, g]
    assert first_three("write(0x13, [0x80], 0); write(0x10, [0x40], 0);") == [-32768, g, g]
    assert first_three("write(0x15, [0x10], 0); write(0x10, [0x40], 0);") == [g, g, g]


def test_data_ready_clears_only_when_a_high_byte_of_the_sensor_s_outputs_is_read() -> None:
    # AN4682 section 3.3: "The interrupt is reset when the higher part of one of the enabled
    # channels has been read (29h, 2Bh, 2Dh for the accelerometer; 23h, 25h, 27h for the
    # gyroscope)."
    found = _run(
        """
        write(0x11, [0x58], 0);
        const status = (t) => read(0x1e, 1, t)[0] & 0x02;
        const t = 30.5 / 208;
        read(0x22, 1, t); read(0x24, 1, t); read(0x26, 1, t);   // the low bytes only
        const afterLow = status(t);
        read(0x25, 1, t);                                       // one high byte
        out({ afterLow, afterHigh: status(t), counted: sensor.counts.gyro_samples_read });
        """
    )
    assert found == {"afterLow": 2, "afterHigh": 0, "counted": 1}


def test_a_register_the_model_does_not_act_on_is_reported_when_written_away_from_its_reset() -> (
    None
):
    # Modelled: ODR and FS, BDU, IF_INC, SW_RESET, XL_BW_SCAL_ODR, DRDY_MASK, XL_HM_MODE,
    # G_HM_MODE. Everything else written from its reset value (CTRL9_XL and CTRL10_C reset to
    # 38h) is the firmware relying on behaviour the rig does not show.
    found = _run(
        """
        write(0x18, [0x38], 0); write(0x19, [0x38], 0);      // reset values: nothing
        write(0x13, [0x88], 0); write(0x15, [0x10], 0);      // modelled bits: nothing
        write(0x16, [0x80], 0);
        write(0x13, [0x40], 0);                              // SLEEP_G
        write(0x14, [0x01], 0);                              // CTRL5_C: self-test
        write(0x12, [0x06], 0);                              // BLE
        write(0x17, [0x80], 0);                              // CTRL8_XL: LPF2
        out(unmodelled);
        """
    )
    assert found == [
        "lsm6ds33:CTRL4_C",
        "lsm6ds33:CTRL5_C",
        "lsm6ds33:CTRL3_C",
        "lsm6ds33:CTRL8_XL",
    ]


def test_each_output_byte_read_is_told_with_the_instant_its_sample_was_taken() -> None:
    # What the rig's input-to-output bound is measured from: the sample's own instant k / ODR,
    # never the time of the read.
    found = _run(
        """
        write(0x11, [0x58], 0); write(0x10, [0x50], 0);      // both at 208 Hz
        read(0x23, 1, 30.7 / 208); read(0x29, 1, 31.2 / 208);
        out(instants.map(([w, k]) => [w, Math.round(k * 1000) / 1000]));
        """
    )
    assert found == [["gyro", 30], ["accel", 31]]


def test_the_gyroscope_s_turn_on_runs_from_its_power_up_write_whatever_rate_is_set_after() -> None:
    # AN4682 section 2.7.1, Table 16: "Power Down" to "Low-Power / Normal / High-Performance",
    # 80 ms at most. The Pololu LSM6 library's enableDefault() writes CTRL2_G = 0x80 (1.66 kHz)
    # and the Balboa's balancing example then writes 0x58 (208 Hz) at once: the second write
    # changes the rate inside the turn-on and does not end it. At 208 Hz from 0.5 ms the first
    # sample at or after 80 ms is k = 17 (at 0.5 ms + 17 / 208 s), then Table 17's two discards.
    found = _run(
        """
        write(0x11, [0x80], 0); write(0x11, [0x58], 0.0005);
        const status = (t) => read(0x1e, 1, t)[0] & 0x02;
        const y = (t) => { const g = read(0x22, 6, t); return int16(g[2], g[3]); };
        const k = (n) => 0.0005 + (n + 0.5) / 208;
        const early = [0.010, 0.020, 0.040, 0.079].map((t) => [status(t), y(t)]);
        const settled = [17, 18, 19].map((n) => [status(k(n)), y(k(n))]);
        // Power-down inside the turn-on ends it; a power-up begins a new one of 80 ms.
        write(0x11, [0x00], 1); write(0x11, [0x58], 1.01); write(0x11, [0x40], 1.05);
        const again = [status(1.089), status(1.0905), y(1.0905 + 2 / 104)];
        out({ early, settled, again, before: sensor.counts.read_before_any_sample });
        """,
        rate="1.0",
    )
    y = round(math.degrees(1.0) * 1000 / 35)
    assert found["early"] == [[0, -32768]] * 4
    assert found["settled"] == [[2, -32768], [2, -32768], [2, y]]
    # From 1.01 s (power-up) to 1.09 s; at 104 Hz from 1.05 s the first sample is at 1.05 + 5 /
    # 104 = 1.0981 s, so at 1.0905 s none yet; two to discard follow it.
    assert found["again"] == [0, 0, -32768]
    # Each high byte read before the first sample is counted: four reads of three axes.
    assert found["before"] == {"gyro": 12, "accel": 0}


def test_an_odr_change_of_either_sensor_starts_the_other_s_discards_again() -> None:
    # AN4682 sections 2.6.2 and 2.7.1: samples are discarded "when the accelerometer / gyroscope
    # ODR is changed"; the rig reads that as either sensor's change (the harsher reading). The
    # gyroscope at 208 Hz, settled at 0.2 s; the accelerometer's rate set at 0.2 s makes the
    # gyroscope's next two samples ones to discard. The accelerometer in high-performance mode at
    # 104 Hz (two to discard), settled at 0.3 s; the gyroscope's rate changed then makes its next
    # two ones to discard as well.
    found = _run(
        """
        write(0x11, [0x58], 0);
        const y = (t) => { const g = read(0x22, 6, t); return int16(g[2], g[3]); };
        const x = (t) => { const a = read(0x28, 6, t); return int16(a[0], a[1]); };
        const before = y(0.2);
        write(0x10, [0x40], 0.2);
        const k = (n) => (n + 0.5) / 208;
        const gyro = [42, 43, 44].map((n) => y(k(n)));
        const settledX = x(0.3);
        write(0x11, [0x48], 0.3);
        const m = (n) => 0.2 + (n + 0.5) / 104;
        const accel = [11, 12, 13].map((n) => x(m(n)));
        out({ before, gyro, settledX, accel });
        """,
        rate="0.5",
    )
    y = round(math.degrees(0.5) * 1000 / 35)
    g = round(1000 / 0.061)
    assert found == {
        "before": y,
        "gyro": [-32768, -32768, y],
        "settledX": g,
        "accel": [-32768, -32768, g],
    }


def test_the_gyroscope_reads_its_zero_rate_level_on_every_axis_but_not_in_a_discarded_one() -> None:
    # Datasheet "Mechanical characteristics": G_TyOff, the typical zero-rate level, +-10 dps. At
    # 245 dps (8.75 mdps a count) a level of (2, -3, 4) dps reads (229, -343, 457) at rest; a
    # sample to discard reads the end of each axis' range opposite the sign of what it measures.
    found = evaluate(
        SENSOR.replace("faults,\n", "faults, zeroRateDps: [2, -3, 4],\n")
        % {
            "pitch": "0",
            "rate": "0",
            "faults": NO_FAULT,
            "raw": "null",
            "body": """
            write(0x11, [0x50], 0);
            const g = (t) => { const b = read(0x22, 6, t);
              return [int16(b[0], b[1]), int16(b[2], b[3]), int16(b[4], b[5])]; };
            out({ discarded: g(17.5 / 208), level: g(0.5) });
            """,
        }
    )
    assert found == {"discarded": [-32768, 32767, -32768], "level": [229, -343, 457]}
