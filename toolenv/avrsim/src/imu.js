// The Balboa 32U4's inertial sensors as the rig models them, on the I2C bus.
//
// The LSM6DS33 (ST DocID025725, "LSM6DS33: iNEMO inertial module: always-on 3D accelerometer and
// 3D gyroscope") at 0x6B, its SA0 pin pulled high on the board, and the LIS3MDL magnetometer
// (ST DocID024204) at 0x1E, which answers its address and identity and has no field to give.
// Neither needs avr8js: each is a register file with a sub-address pointer, given the time in
// seconds with every bus step. Every register of each part's map is modelled, reported or ends
// the evidence (`LSM6_KINDS`, `LIS3MDL_KINDS`): a part that acknowledged its address and then read
// zero from everything it has no model for would show firmware a sensor that works.
//
// The LSM6DS33's outputs are taken at sample instants: once an output data rate (ODR) is set at
// time t0, sample k is taken at t0 + k / ODR, and a read returns the newest sample so far. What is
// sampled is the body's motion as the scenario gives it, through the axis convention of the Balboa
// library's own balancing example (examples/Balancer/Balance.cpp: the angle rate is +g.y, the
// angle from the accelerometer is atan2(a.z, a.x)): with pitch theta and pitch rate omega, the
// gyroscope reads (0, omega, 0) plus its zero-rate level and the accelerometer (cos theta, 0,
// sin theta) g. The zero-rate level is the scenario's, within the datasheet's typical figure
// ("Mechanical characteristics", G_TyOff: +-10 dps, a typical figure and not a bound), and the
// accelerometer reads its own zero-g level (LA_TyOff: +-40 mg). No noise and no filter delay: those
// are the part's, and not shown.

export const LSM6DS33_ADDRESS = 0x6b;
export const LIS3MDL_ADDRESS = 0x1e;

/** The LSM6DS33's registers by name (datasheet "Register mapping"). */
export const LSM6 = Object.freeze({
  FUNC_CFG_ACCESS: 0x01,
  FIFO_CTRL1: 0x06,
  FIFO_CTRL2: 0x07,
  FIFO_CTRL3: 0x08,
  FIFO_CTRL4: 0x09,
  FIFO_CTRL5: 0x0a,
  ORIENT_CFG_G: 0x0b,
  INT1_CTRL: 0x0d,
  INT2_CTRL: 0x0e,
  WHO_AM_I: 0x0f,
  CTRL1_XL: 0x10,
  CTRL2_G: 0x11,
  CTRL3_C: 0x12,
  CTRL4_C: 0x13,
  CTRL5_C: 0x14,
  CTRL6_C: 0x15,
  CTRL7_G: 0x16,
  CTRL8_XL: 0x17,
  CTRL9_XL: 0x18,
  CTRL10_C: 0x19,
  STATUS_REG: 0x1e,
  OUT_TEMP_L: 0x20,
  OUT_TEMP_H: 0x21,
  OUTX_L_G: 0x22,
  OUTZ_H_G: 0x27,
  OUTX_L_XL: 0x28,
  OUTZ_H_XL: 0x2d,
  TIMESTAMP2_REG: 0x42,
  TAP_CFG: 0x58,
  TAP_THS_6D: 0x59,
  INT_DUR2: 0x5a,
  WAKE_UP_THS: 0x5b,
  WAKE_UP_DUR: 0x5c,
  FREE_FALL: 0x5d,
  MD1_CFG: 0x5e,
  MD2_CFG: 0x5f,
});
const WHO_AM_I_VALUE = 0x69;
const CTRL3_C_RESET = 0x04; // IF_INC set: the address increments in a multi-byte access
/** Registers not at 0 after reset (datasheet "Register mapping": CTRL9_XL and CTRL10_C 38h). */
const RESET_VALUES = { [LSM6.CTRL3_C]: CTRL3_C_RESET, [LSM6.CTRL9_XL]: 0x38, [LSM6.CTRL10_C]: 0x38 };
/** The bits of each control register the model acts on; a write setting any other bit away from
 * its reset value, or to any other register, is reported as unmodelled. CTRL3_C: BOOT, BDU,
 * IF_INC, SW_RESET; CTRL4_C: XL_BW_SCAL_ODR, DRDY_MASK; CTRL6_C: XL_HM_MODE; CTRL7_G: G_HM_MODE
 * (no effect on what the model shows: the gyroscope's samples to discard do not depend on it). */
const MODELLED_BITS = {
  [LSM6.CTRL1_XL]: 0xff,
  [LSM6.CTRL2_G]: 0xff,
  [LSM6.CTRL3_C]: 0xc5,
  [LSM6.CTRL4_C]: 0x88,
  [LSM6.CTRL6_C]: 0x10,
  [LSM6.CTRL7_G]: 0x80,
};
const NAMES = new Map(Object.entries(LSM6).map(([name, address]) => [address, name]));

/**
 * What each LSM6DS33 register is (datasheet Table 16): `cfg` a control register (a write the
 * model does not act on is reported), `out` an output or the status and identity the model gives
 * (read-only: a write changes nothing), `data` an output the model has no value for (a read
 * ends the evidence), `timestamp` such an output that a write also acts on, and `reserved` a
 * register the datasheet says must not be changed (any access ends the evidence).
 */
const kinds = (table, ranges) => {
  for (const [kind, ...spans] of ranges) {
    for (const span of spans) {
      const [from, to = from] = Array.isArray(span) ? span : [span];
      for (let address = from; address <= to; address += 1) table[address] = kind;
    }
  }
};
const LSM6_KINDS = new Array(0x80).fill('reserved');
kinds(LSM6_KINDS, [
  ['cfg', 0x01, [0x06, 0x0b], 0x0d, 0x0e, [0x10, 0x19], [0x58, 0x5f]],
  ['out', 0x0f, 0x1e, [0x20, 0x2d]],
  ['data', [0x1b, 0x1d], [0x3a, 0x41], [0x49, 0x4c], 0x53],
  ['timestamp', 0x42],
]);

/** Output data rates by the four ODR bits of CTRL1_XL and CTRL2_G; the gyroscope stops at
 * 1.66 kHz, and its codes above that are taken as power-down. */
const ODR_HZ = [0, 12.5, 26, 52, 104, 208, 416, 833, 1660, 3330, 6660];
/** Sensitivity per count: gyroscope in mdps by FS_G (and FS_125), accelerometer in mg by FS_XL
 * (datasheet "Mechanical characteristics"). */
const GYRO_MDPS = [8.75, 17.5, 35, 70];
const GYRO_MDPS_125 = 4.375;
const ACCEL_MG = [0.061, 0.488, 0.122, 0.244];

/** The gyroscope's turn-on from power-down, at most 80 ms (AN4682 Table 16), and the samples to
 * discard after it and after an ODR change, by ODR code (AN4682 Table 17: 2 up to 416 Hz, 3 at
 * 833 Hz, 4 at 1.66 kHz). The turn-on runs from the write that takes the gyroscope out of
 * power-down ("Power Down" to "Low-Power / Normal / High-Performance"); a change of its rate
 * before the turn-on is over does not end it. */
export const GYRO_TURN_ON_S = 0.08;
const GYRO_DISCARD = [0, 2, 2, 2, 2, 2, 2, 3, 4];
/** The accelerometer's samples to discard in high-performance mode, by ODR code and analog
 * filter bandwidth 400, 200, 100, 50 Hz or no filter (AN4682 Table 12); none in low-power and
 * normal mode (Table 11: "First sample correct"). */
const ACCEL_DISCARD = [
  null,
  [1, 1, 1, 1, 1],
  [1, 1, 1, 1, 0],
  [1, 1, 1, 1, 0],
  [1, 1, 1, 2, 0],
  [1, 1, 2, 4, 0],
  [1, 2, 3, 7, 0],
  [2, 4, 7, 14, 0],
  [4, 8, 14, 28, 0],
  [8, 16, 28, 56, 2],
  [16, 32, 56, 112, 4],
];
/** The analog filter's bandwidth column when XL_BW_SCAL_ODR is 0, by ODR code (datasheet Table
 * 45: 50 Hz to 104 Hz, 100 Hz at 208, 200 at 416, 400 at 833 and 1660, none above). */
const ACCEL_AUTO_BW = [null, 3, 3, 3, 3, 2, 1, 0, 0, 4, 4];

const DEG_PER_RAD = 180 / Math.PI;
/** The datasheet's typical zero-rate level ("Mechanical characteristics", G_TyOff), in dps: a
 * typical figure and not a bound (section 4.6.2 calls it the standard deviation of a group of
 * parts), so a scenario may state up to four times it, of either sign. */
export const GYRO_ZERO_RATE_LIMIT_DPS = 10;
/** The datasheet's typical zero-g level ("Mechanical characteristics", LA_TyOff), in mg. */
export const ACCEL_ZERO_G_TYPICAL_MG = 40;
/** What a sample to discard reads, and what the outputs read before the part has taken any
 * sample. The documents give no value for either: AN4682 Tables 12, 16 and 17 say only that such
 * samples "have to be discarded", and the register map gives the outputs no reset value. The rig's
 * conservative choice is a value no calibration or angle can take for the truth. */
export const INVALID_SAMPLE_VALUE =
  'each axis at the end of its range opposite to the sign of its input: -32768 for an input of 0 or more, ' +
  '32767 for a negative one (the documents give no value for a sample to discard, or for the outputs before ' +
  'the first sample)';
const AXES = { x: 0, y: 1, z: 2 };

function int16(value) {
  return Math.max(-32768, Math.min(32767, Math.round(value)));
}

/** The name the trace gives a register of the LSM6DS33. */
export function lsm6Name(address) {
  return NAMES.get(address) ?? `0x${address.toString(16).padStart(2, '0')}`;
}

/**
 * The LSM6DS33.
 *
 * `zeroRateDps` is the gyroscope's zero-rate level on x, y and z in dps and `zeroGMg` the
 * accelerometer's zero-g level in mg (none if not given);
 * `motion(t)` gives {pitch_rad, pitch_rate_rad_s}; `raw(t)` gives counts that replace the outputs
 * ({gyro, accel}) or null; `faults(t)` gives {nack, stale_since, saturated} (`stale_since` the
 * time the active stale fault began, `saturated` null or {sensor: 'gyro' | 'accel' | 'both',
 * axes: ['x', 'y', 'z'] or some of them}). `onWrite(register, value, t)` is told of every
 * register the firmware writes, `onUnmodelled(what)` of each write the model does not act on,
 * `onEvidenceEnd(cause, detail)` of each read of data it has no value for and each access to a
 * reserved register,
 * `onOutputRead(sensor, instant)` of each output byte read with the instant (s) of the sample it
 * came from.
 *
 * - Sample k of a sensor is taken at t0 + k / ODR, t0 the instant its rate was set.
 * - Block data update (CTRL3_C BDU, datasheet Table 50): with BDU 0 the outputs are updated
 *   continuously, so each byte read is the newest sample's, and the two bytes of one axis read
 *   across a sample's instant come from two samples; with BDU 1 an axis' pair, once one byte of
 *   it is read, keeps its sample until both bytes have been read (other axes still update,
 *   AN4682 section 3.4).
 * - Data ready (GDA, XLDA) says a sample newer than the one taken up is there; a sample is taken
 *   up when a high byte of the sensor's outputs is read (AN4682 section 3.3: "reset when the
 *   higher part of one of the enabled channels has been read").
 * - Turn-on and settling (AN4682 sections 2.6.2 and 2.7.1): from power-down the gyroscope takes
 *   no sample for 80 ms (data ready stays 0), and after that, and after any change of its ODR,
 *   its first samples of Table 17 are invalid; the accelerometer's first samples of Table 12 are
 *   invalid after power-down or an ODR change in high-performance mode. A change of either
 *   sensor's ODR starts the other's discards again: AN4682 section 2.6.2 has the accelerometer
 *   settle "when the accelerometer / gyroscope ODR is changed", and section 2.7.1 the gyroscope;
 *   the rig reads that as either sensor's change, the harsher reading. An invalid sample reads
 *   INVALID_SAMPLE_VALUE and sets data ready unless CTRL4_C's DRDY_MASK is set; each one taken up
 *   is counted, and so is each high output byte read before the sensor has taken any sample.
 */
export class LSM6DS33 {
  constructor({ motion, raw, faults, onWrite, onUnmodelled, onEvidenceEnd, onOutputRead, zeroRateDps,
    zeroGMg }) { // prettier-ignore
    this.motion = motion;
    this.zeroRateDps = zeroRateDps ?? [0, 0, 0];
    this.zeroGMg = zeroGMg ?? [0, 0, 0];
    this.raw = raw;
    this.faults = faults;
    this.onWrite = onWrite ?? (() => {});
    this.onUnmodelled = onUnmodelled ?? (() => {});
    this.onEvidenceEnd = onEvidenceEnd ?? (() => {});
    this.onOutputRead = onOutputRead ?? (() => {});
    this.registers = new Uint8Array(0x80);
    this.reset(0);
    this.pointer = 0;
    this.addressed = false;
    this.counts = {
      whoami_reads: 0,
      gyro_samples_read: 0,
      accel_samples_read: 0,
      invalid_samples_read: { gyro: 0, accel: 0 },
      read_before_any_sample: { gyro: 0, accel: 0 },
    };
    /** The instant (s) the newest gyroscope sample taken up so far was taken, or null. */
    this.lastGyroReady = null;
  }

  reset(t) {
    this.registers.fill(0);
    this.registers[LSM6.WHO_AM_I] = WHO_AM_I_VALUE;
    for (const [address, value] of Object.entries(RESET_VALUES)) this.registers[address] = value;
    // `held`: what the outputs hold, null before any sample; `onUntil`: the end of the
    // gyroscope's turn-on from its last power-down.
    const sensor = () => ({ odr: 0, code: 0, t0: t, read: 0, first: 1, valid: 1, held: null,
      latch: [null, null, null], cache: null, onUntil: null }); // prettier-ignore
    this.gyro = sensor();
    this.accel = sensor();
  }

  acknowledges(t) {
    return !this.faults(t).nack;
  }

  /** A transaction addressed to the part begins (after its address was acknowledged). */
  begin(write) {
    this.addressed = !write;
  }

  write(value, t) {
    if (!this.addressed) {
      this.pointer = value & 0x7f;
      this.addressed = true;
      return true;
    }
    this.store(this.pointer, value, t);
    this.advance();
    return true;
  }

  read(t) {
    const value = this.load(this.pointer, t);
    this.advance();
    return value;
  }

  advance() {
    if (this.registers[LSM6.CTRL3_C] & 0x04) this.pointer = (this.pointer + 1) & 0x7f;
  }

  /** A register the model has no value for was read or a reserved one touched: the evidence ends. */
  noData(address, access) {
    this.onUnmodelled('lsm6ds33_data');
    this.onEvidenceEnd('lsm6ds33_data', { register: address, name: lsm6Name(address), access });
  }

  store(address, value, t) {
    this.onWrite(address, value, t);
    const kind = LSM6_KINDS[address];
    if (kind === 'reserved') {
      this.noData(address, 'write'); // "must not be changed"
      return;
    }
    if (kind === 'out' || kind === 'data') return; // read-only: a write changes nothing
    if (address === LSM6.CTRL3_C && value & 0x01) {
      this.reset(t); // SW_RESET: the registers return to their reset values; the bit clears
      return;
    }
    const kept = MODELLED_BITS[address] ?? 0;
    if ((value ^ (RESET_VALUES[address] ?? 0)) & ~kept & 0xff) {
      this.onUnmodelled(`lsm6ds33:${lsm6Name(address)}`);
    }
    this.registers[address] = address === LSM6.CTRL3_C ? value & ~0x80 : value;
    if (address === LSM6.CTRL1_XL) this.rate('accel', value >> 4, t);
    if (address === LSM6.CTRL2_G) this.rate('gyro', value >> 4 <= 8 ? value >> 4 : 0, t);
  }

  rate(which, code, t) {
    const sensor = this[which];
    const odr = ODR_HZ[code] ?? 0;
    if (odr === sensor.odr) return;
    const fromPowerDown = sensor.odr === 0;
    sensor.odr = odr;
    sensor.code = odr ? code : 0;
    sensor.t0 = t;
    sensor.read = 0;
    sensor.latch = [null, null, null];
    sensor.cache = null;
    this.settleAgain(which === 'gyro' ? 'accel' : 'gyro', t);
    if (!odr) return;
    if (which === 'gyro' && fromPowerDown) sensor.onUntil = t + GYRO_TURN_ON_S;
    // `first`: the first sample the part takes, none before the turn-on's end; `valid`: the first
    // one that is not discarded.
    const on = sensor.onUntil !== null && sensor.onUntil > t ? sensor.onUntil - t : 0;
    sensor.first = Math.max(1, Math.ceil(on * odr - 1e-9));
    sensor.valid = sensor.first + this.discards(which, code);
  }

  /** The other sensor's ODR changed at `t`: its next samples are discarded again. */
  settleAgain(which, t) {
    const sensor = this[which];
    if (!sensor.odr) return;
    const taken = Math.floor((t - sensor.t0) * sensor.odr + 1e-9);
    const next = Math.max(sensor.first, taken + 1);
    sensor.valid = Math.max(sensor.valid, next + this.discards(which, sensor.code));
  }

  discards(which, code) {
    if (which === 'gyro') return GYRO_DISCARD[code] ?? 0;
    const highPerformance = !(this.registers[LSM6.CTRL6_C] & 0x10) || code >= 6;
    if (!highPerformance) return 0;
    const column = this.registers[LSM6.CTRL4_C] & 0x80 ? this.registers[LSM6.CTRL1_XL] & 0x03 : ACCEL_AUTO_BW[code];
    return ACCEL_DISCARD[code][column];
  }

  /** The number of the newest sample a sensor has taken by `t` (below `first`: none yet). */
  index(sensor, t) {
    if (!sensor.odr) return 0;
    const faults = this.faults(t);
    const at = faults.stale_since !== null && faults.stale_since !== undefined ? Math.min(t, faults.stale_since) : t;
    const k = Math.max(0, Math.floor((at - sensor.t0) * sensor.odr + 1e-9));
    return k < sensor.first ? 0 : k;
  }

  ready(sensor, t) {
    const faults = this.faults(t);
    if (faults.stale_since !== null && faults.stale_since !== undefined) return false;
    const k = this.index(sensor, t);
    if (this.registers[LSM6.CTRL4_C] & 0x08 && k < sensor.valid) return false; // DRDY_MASK
    return k > sensor.read;
  }

  load(address, t) {
    const kind = LSM6_KINDS[address];
    if (kind === 'reserved' || kind === 'data' || kind === 'timestamp') {
      this.noData(address, 'read'); // an output with no value here, or a register not to be touched
      return this.registers[address];
    }
    if (address === LSM6.STATUS_REG) {
      const xl = this.ready(this.accel, t) ? 0x01 : 0;
      const g = this.ready(this.gyro, t) ? 0x02 : 0;
      const temp = this.gyro.odr || this.accel.odr ? 0x04 : 0;
      return xl | g | temp;
    }
    if (address === LSM6.WHO_AM_I) {
      this.counts.whoami_reads += 1;
      return WHO_AM_I_VALUE;
    }
    if (address === LSM6.OUT_TEMP_L || address === LSM6.OUT_TEMP_H) return 0; // 25 degC
    if (address >= LSM6.OUTX_L_G && address <= LSM6.OUTZ_H_G) {
      return this.outputByte('gyro', address - LSM6.OUTX_L_G, t);
    }
    if (address >= LSM6.OUTX_L_XL && address <= LSM6.OUTZ_H_XL) {
      return this.outputByte('accel', address - LSM6.OUTX_L_XL, t);
    }
    return this.registers[address];
  }

  /** Sample k's three counts, or what the outputs hold when there is none (k = 0) at `t`. */
  values(which, k, t) {
    const sensor = this[which];
    if (!k) return sensor.held ?? this.invalid(which, t);
    if (sensor.cache && sensor.cache.k === k) return sensor.cache.values;
    const at = sensor.t0 + k / sensor.odr;
    const values = k < sensor.valid ? this.invalid(which, at) : this.sample(which, at);
    sensor.cache = { k, values };
    return values;
  }

  /** INVALID_SAMPLE_VALUE for the input at `t`. */
  invalid(which, t) {
    return this.sample(which, t).map((count) => (count < 0 ? 32767 : -32768));
  }

  /** One byte of a sensor's output, as BDU gives it. */
  outputByte(which, offset, t) {
    const sensor = this[which];
    const axis = offset >> 1;
    const high = offset & 1;
    let k;
    let values;
    const latched = sensor.latch[axis];
    if (latched) {
      ({ k, values } = latched);
      latched.read |= high ? 2 : 1;
      if (latched.read === 3) sensor.latch[axis] = null;
    } else {
      k = this.index(sensor, t);
      values = this.values(which, k, t);
      if (this.registers[LSM6.CTRL3_C] & 0x40) sensor.latch[axis] = { k, values, read: high ? 2 : 1 };
    }
    if (k) {
      sensor.held = values;
      this.onOutputRead(which, sensor.t0 + k / sensor.odr);
    }
    if (high && !k && !sensor.held) this.counts.read_before_any_sample[which] += 1;
    if (high && k > sensor.read) {
      sensor.read = k;
      this.counts[`${which}_samples_read`] += 1;
      if (k < sensor.valid) this.counts.invalid_samples_read[which] += 1;
      if (which === 'gyro') this.lastGyroReady = sensor.t0 + k / sensor.odr;
    }
    const value = values[axis] & 0xffff;
    return high ? value >> 8 : value & 0xff;
  }

  /** A sensor's three counts for the sample taken at `t`. */
  sample(which, t) {
    const raw = this.raw(t);
    let counts;
    if (raw) {
      counts = [...raw[which]];
    } else if (which === 'gyro') {
      const ctrl = this.registers[LSM6.CTRL2_G];
      const mdps = ctrl & 0x02 ? GYRO_MDPS_125 : GYRO_MDPS[(ctrl >> 2) & 0x03];
      const dps = this.motion(t).pitch_rate_rad_s * DEG_PER_RAD;
      const [x, y, z] = this.zeroRateDps;
      counts = [int16((x * 1000) / mdps), int16(((dps + y) * 1000) / mdps), int16((z * 1000) / mdps)];
    } else {
      const mg = ACCEL_MG[(this.registers[LSM6.CTRL1_XL] >> 2) & 0x03];
      const { pitch_rad: theta } = this.motion(t);
      const [x, y, z] = this.zeroGMg;
      counts = [
        int16((Math.cos(theta) * 1000 + x) / mg),
        int16(y / mg),
        int16((Math.sin(theta) * 1000 + z) / mg),
      ];
    }
    // Over range: each axis named clips at the end of the range on the side its input lies
    // (datasheet "Mechanical characteristics", FS); an input of exactly 0 is taken as positive.
    const saturated = this.faults(t).saturated;
    if (saturated && (saturated.sensor === which || saturated.sensor === 'both')) {
      for (const axis of saturated.axes) counts[AXES[axis]] = counts[AXES[axis]] < 0 ? -32768 : 32767;
    }
    return counts.map(int16);
  }
}

/** The LIS3MDL's registers by name (datasheet Table 16): the control registers a write of which
 * the model does not act on, the identity it answers, and the outputs it has no value for. */
const LIS3MDL_NAMES = new Map([
  [0x0f, 'WHO_AM_I'], [0x20, 'CTRL_REG1'], [0x21, 'CTRL_REG2'], [0x22, 'CTRL_REG3'],
  [0x23, 'CTRL_REG4'], [0x24, 'CTRL_REG5'], [0x27, 'STATUS_REG'], [0x28, 'OUT_X_L'],
  [0x29, 'OUT_X_H'], [0x2a, 'OUT_Y_L'], [0x2b, 'OUT_Y_H'], [0x2c, 'OUT_Z_L'], [0x2d, 'OUT_Z_H'],
  [0x2e, 'TEMP_OUT_L'], [0x2f, 'TEMP_OUT_H'], [0x30, 'INT_CFG'], [0x31, 'INT_SRC'],
  [0x32, 'INT_THS_L'], [0x33, 'INT_THS_H'],
]); // prettier-ignore
const LIS3MDL_KINDS = new Array(0x80).fill('reserved');
kinds(LIS3MDL_KINDS, [
  ['cfg', [0x20, 0x24], 0x30, 0x32, 0x33],
  ['out', 0x0f],
  ['data', 0x27, [0x28, 0x2f], 0x31],
]);
/** The LIS3MDL's control registers' values after reset (CTRL_REG1 10h, CTRL_REG3 03h). */
const LIS3MDL_RESET = { 0x20: 0x10, 0x22: 0x03 };
export const LIS3MDL_WHO_AM_I = 0x3d;

/** The name a trace or a report gives a LIS3MDL register: the datasheet's, or its address. */
export function lis3mdlName(address) {
  return LIS3MDL_NAMES.get(address) ?? `0x${address.toString(16).padStart(2, '0')}`;
}

/**
 * The LIS3MDL: it acknowledges its address and answers WHO_AM_I (0x3D), as on the board, and has
 * no field to give. A read of its status, outputs, temperature or interrupt source ends the
 * evidence (`lis3mdl_data`), a write of a control register away from its reset value is
 * reported (`lis3mdl:NAME`), and any access to a register the datasheet calls reserved ends the
 * evidence. Its sub-address increments only when its top bit is set (datasheet "I2C operation").
 */
export class LIS3MDL {
  constructor({ faults, onUnmodelled, onEvidenceEnd }) {
    this.faults = faults;
    this.onUnmodelled = onUnmodelled ?? (() => {});
    this.onEvidenceEnd = onEvidenceEnd ?? (() => {});
    this.registers = new Uint8Array(0x80);
    this.registers[0x0f] = LIS3MDL_WHO_AM_I;
    for (const [address, value] of Object.entries(LIS3MDL_RESET)) this.registers[address] = value;
    this.pointer = 0;
    this.increment = false;
    this.addressed = false;
  }

  acknowledges(t) {
    return !this.faults(t).nack;
  }

  begin(write) {
    this.addressed = !write;
  }

  noData(address, access) {
    this.onUnmodelled('lis3mdl_data');
    this.onEvidenceEnd('lis3mdl_data', { register: address, name: lis3mdlName(address), access });
  }

  write(value) {
    if (!this.addressed) {
      this.pointer = value & 0x7f;
      this.increment = !!(value & 0x80);
      this.addressed = true;
      return true;
    }
    const address = this.pointer;
    const kind = LIS3MDL_KINDS[address];
    if (kind === 'reserved') {
      this.noData(address, 'write'); // "must not be changed"
    } else if (kind === 'cfg') {
      if (value !== (LIS3MDL_RESET[address] ?? 0)) this.onUnmodelled(`lis3mdl:${lis3mdlName(address)}`);
      this.registers[address] = value;
    } // a read-only register ignores a write
    if (this.increment) this.pointer = (this.pointer + 1) & 0x7f;
    return true;
  }

  read() {
    const address = this.pointer;
    const kind = LIS3MDL_KINDS[address];
    if (kind === 'reserved' || kind === 'data') this.noData(address, 'read');
    if (this.increment) this.pointer = (this.pointer + 1) & 0x7f;
    return this.registers[address];
  }
}
