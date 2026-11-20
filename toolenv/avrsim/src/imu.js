// The Balboa 32U4's inertial sensors as the rig models them, on the I2C bus.
//
// The LSM6DS33 (ST DocID025725, "LSM6DS33: iNEMO inertial module: always-on 3D accelerometer and
// 3D gyroscope") at 0x6B, its SA0 pin pulled high on the board, and the LIS3MDL magnetometer
// (ST DocID024204) at 0x1E as a minimal responder. Neither needs avr8js: each is a register file
// with a sub-address pointer, given the time in seconds with every bus step.
//
// The LSM6DS33's outputs are taken at sample instants: once an output data rate (ODR) is set at
// time t0, sample k is taken at t0 + k / ODR, and a read returns the newest sample so far. What is
// sampled is the body's motion as the scenario gives it, through the axis convention of the Balboa
// library's own balancing example (examples/Balancer/Balance.cpp: the angle rate is +g.y, the
// angle from the accelerometer is atan2(a.z, a.x)): with pitch theta and pitch rate omega, the
// gyroscope reads (0, omega, 0) and the accelerometer (cos theta, 0, sin theta) g. No noise, no
// bias, no filter delay: those are the part's, and not shown.

export const LSM6DS33_ADDRESS = 0x6b;
export const LIS3MDL_ADDRESS = 0x1e;

/** The LSM6DS33's registers the model gives a meaning to (datasheet "Register mapping"). */
export const LSM6 = Object.freeze({
  WHO_AM_I: 0x0f,
  CTRL1_XL: 0x10,
  CTRL2_G: 0x11,
  CTRL3_C: 0x12,
  STATUS_REG: 0x1e,
  OUT_TEMP_L: 0x20,
  OUT_TEMP_H: 0x21,
  OUTX_L_G: 0x22,
  OUTZ_H_G: 0x27,
  OUTX_L_XL: 0x28,
  OUTZ_H_XL: 0x2d,
});
const WHO_AM_I_VALUE = 0x69;
const CTRL3_C_RESET = 0x04; // IF_INC set: the address increments in a multi-byte access
const NAMES = new Map(Object.entries(LSM6).map(([name, address]) => [address, name]));

/** Output data rates by the four ODR bits of CTRL1_XL and CTRL2_G; the gyroscope stops at
 * 1.66 kHz, and its codes above that are taken as power-down. */
const ODR_HZ = [0, 12.5, 26, 52, 104, 208, 416, 833, 1660, 3330, 6660];
/** Sensitivity per count: gyroscope in mdps by FS_G (and FS_125), accelerometer in mg by FS_XL
 * (datasheet "Mechanical characteristics"). */
const GYRO_MDPS = [8.75, 17.5, 35, 70];
const GYRO_MDPS_125 = 4.375;
const ACCEL_MG = [0.061, 0.488, 0.122, 0.244];

const DEG_PER_RAD = 180 / Math.PI;

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
 * `motion(t)` gives {pitch_rad, pitch_rate_rad_s}; `raw(t)` gives counts that replace the outputs
 * ({gyro, accel}) or null; `faults(t)` gives {nack, stale_since, saturated} (`stale_since` the
 * time the active stale fault began, `saturated` one of null, 'gyro', 'accel', 'both').
 * `onWrite(register, value, t)` is told of every register the firmware writes.
 */
export class LSM6DS33 {
  constructor({ motion, raw, faults, onWrite }) {
    this.motion = motion;
    this.raw = raw;
    this.faults = faults;
    this.onWrite = onWrite ?? (() => {});
    this.registers = new Uint8Array(0x80);
    this.reset(0);
    this.pointer = 0;
    this.addressed = false;
    this.snapshot = {};
    this.counts = { whoami_reads: 0, gyro_samples_read: 0, accel_samples_read: 0 };
    /** The instant (s) the newest gyroscope sample read so far was taken, or null. */
    this.lastGyroReady = null;
  }

  reset(t) {
    this.registers.fill(0);
    this.registers[LSM6.WHO_AM_I] = WHO_AM_I_VALUE;
    this.registers[LSM6.CTRL3_C] = CTRL3_C_RESET;
    this.gyro = { odr: 0, t0: t, read: 0, held: [0, 0, 0] };
    this.accel = { odr: 0, t0: t, read: 0, held: [0, 0, 0] };
  }

  acknowledges(t) {
    return !this.faults(t).nack;
  }

  /** A transaction addressed to the part begins (after its address was acknowledged). */
  begin(write) {
    this.addressed = !write;
    this.snapshot = {};
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

  store(address, value, t) {
    this.onWrite(address, value, t);
    if (address === LSM6.WHO_AM_I || address === LSM6.STATUS_REG) return; // read-only
    if (address >= LSM6.OUT_TEMP_L && address <= LSM6.OUTZ_H_XL) return; // read-only
    if (address === LSM6.CTRL3_C && value & 0x01) {
      this.reset(t); // SW_RESET: the registers return to their reset values; the bit clears
      return;
    }
    this.registers[address] = address === LSM6.CTRL3_C ? value & ~0x80 : value;
    if (address === LSM6.CTRL1_XL) this.rate(this.accel, ODR_HZ[value >> 4] ?? 0, t);
    if (address === LSM6.CTRL2_G) {
      const code = value >> 4;
      this.rate(this.gyro, code <= 8 ? ODR_HZ[code] : 0, t);
    }
  }

  rate(sensor, odr, t) {
    if (odr === sensor.odr) return;
    sensor.odr = odr;
    sensor.t0 = t;
    sensor.read = 0;
  }

  /** The number of the newest sample a sensor has taken by `t` (0: none since its rate was set). */
  index(sensor, t) {
    if (!sensor.odr) return sensor.read;
    const faults = this.faults(t);
    const at = faults.stale_since !== null && faults.stale_since !== undefined ? Math.min(t, faults.stale_since) : t;
    return Math.max(0, Math.floor((at - sensor.t0) * sensor.odr + 1e-9));
  }

  ready(sensor, t) {
    const faults = this.faults(t);
    if (faults.stale_since !== null && faults.stale_since !== undefined) return false;
    return sensor.odr > 0 && this.index(sensor, t) > sensor.read;
  }

  load(address, t) {
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

  /** One byte of a sensor's output: within one transaction every byte comes from one sample. */
  outputByte(which, offset, t) {
    if (!this.snapshot[which]) {
      const sensor = this[which];
      const k = this.index(sensor, t);
      // Powered down, or no sample yet since the rate was set: the outputs hold what they held.
      const values = sensor.odr && k > 0 ? this.sample(which, sensor.t0 + k / sensor.odr) : sensor.held;
      sensor.held = values;
      if (sensor.odr && k > sensor.read) {
        sensor.read = k;
        this.counts[`${which}_samples_read`] += 1;
        if (which === 'gyro') this.lastGyroReady = sensor.t0 + k / sensor.odr;
      }
      this.snapshot[which] = values;
    }
    const value = this.snapshot[which][offset >> 1] & 0xffff;
    return offset & 1 ? value >> 8 : value & 0xff;
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
      counts = [0, int16((dps * 1000) / mdps), 0];
    } else {
      const mg = ACCEL_MG[(this.registers[LSM6.CTRL1_XL] >> 2) & 0x03];
      const { pitch_rad: theta } = this.motion(t);
      counts = [int16((Math.cos(theta) * 1000) / mg), 0, int16((Math.sin(theta) * 1000) / mg)];
    }
    const saturated = this.faults(t).saturated;
    if (saturated === which || saturated === 'both') {
      counts = counts.map((c) => (c < 0 ? -32768 : 32767));
    }
    return counts.map(int16);
  }
}

/** The LIS3MDL as a minimal responder: it acknowledges, keeps what is written, answers
 * WHO_AM_I (0x3D) and reads zero field. Its sub-address increments only when its top bit is set
 * (datasheet "I2C operation"). */
export class LIS3MDL {
  constructor({ faults }) {
    this.faults = faults;
    this.registers = new Uint8Array(0x40);
    this.registers[0x0f] = 0x3d;
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

  write(value) {
    if (!this.addressed) {
      this.pointer = value & 0x3f;
      this.increment = !!(value & 0x80);
      this.addressed = true;
      return true;
    }
    if (this.pointer !== 0x0f) this.registers[this.pointer] = value;
    if (this.increment) this.pointer = (this.pointer + 1) & 0x3f;
    return true;
  }

  read() {
    const value = this.registers[this.pointer];
    if (this.increment) this.pointer = (this.pointer + 1) & 0x3f;
    return value;
  }
}
