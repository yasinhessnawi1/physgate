// The scenario a run is driven by: read as data, bounded, and refused whole if any part is wrong.
//
// A session writes it. Nothing in it is run: every field is a number, a string from a fixed set,
// or a symbol name the ELF must hold. A field the reader does not know is refused, never
// ignored, so a misspelt fault cannot pass as a scenario without it.

import { ACCEL_ZERO_G_TYPICAL_MG, GYRO_ZERO_RATE_LIMIT_DPS } from './imu.js';

export class ScenarioError extends Error {
  constructor(where, why) {
    super(`the scenario is refused at ${where}: ${why}`);
    this.where = where;
  }
}

export const SCENARIO_VERSION = 1;
/** The most a scenario file may hold. */
export const MAX_SCENARIO_BYTES = 1 << 20;
/** The longest run, in seconds of board time. */
export const MAX_DURATION_S = 600;
const MAX_POINTS = 10_000;
const MAX_ITEMS = 1_000;
const MAX_PROBES = 16;
const MAX_TRACE_LINES = 20_000_000;
const DEFAULT_TRACE_LINES = 2_000_000;
const SYMBOL = /^[A-Za-z_.$][A-Za-z0-9_.$]{0,199}$/;
const NAME = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}$/;

const FAULT_KINDS = new Set(['nack', 'sda_held', 'stale', 'saturated']);
const DEVICES = new Set(['lsm6ds33', 'lis3mdl']);
const SENSORS = new Set(['gyro', 'accel', 'both']);
const BUTTONS = new Set(['A', 'B', 'C']);
const RELEASES = new Set(['end', 'scl_pulses']);
const AXES = ['x', 'y', 'z'];
const BOOTLOADERS = new Set(['a-star', 'none']);
/** How long both motor enables must stay low for the motors to count as off, by default: longer
 * than a PWM period at 50 Hz or faster, so the low part of a PWM wave is never "off". */
const DEFAULT_MOTORS_OFF_HOLD_S = 0.02;
/** The sensors' zero levels by default: the datasheet's typical figures (LSM6DS33 "Mechanical
 * characteristics", G_TyOff +-10 dps and LA_TyOff +-40 mg) at their stated magnitudes, so a
 * firmware that does not calibrate them shows that it does not. They are typical figures and not
 * bounds (the datasheet gives no maximum): a scenario may state up to ZERO_LEVEL_FACTOR times
 * either, of either sign. */
const DEFAULT_GYRO_ZERO_RATE_DPS = [GYRO_ZERO_RATE_LIMIT_DPS, GYRO_ZERO_RATE_LIMIT_DPS, GYRO_ZERO_RATE_LIMIT_DPS];
const DEFAULT_ACCEL_ZERO_G_MG = [ACCEL_ZERO_G_TYPICAL_MG, ACCEL_ZERO_G_TYPICAL_MG, ACCEL_ZERO_G_TYPICAL_MG];
const ZERO_LEVEL_FACTOR = 4;
/** The battery voltages the model is run at: a six-cell pack's own range, 6.0 V (1.0 V a cell) to
 * the 10.8 V the motor drivers limit the board to (Balboa 32U4 User's Guide, "5 V and 3.3 V
 * regulators"). It is the model's range and not a statement about the board: the documents give no
 * minimum input and no drop-out for the 5 V regulator (MP4423H) below it, and the chip's brown-out
 * reset lies at 4.0 to 4.5 V (datasheet Table 8-1; "The brown-out threshold is 4.3 V"). */
export const BATTERY_V = Object.freeze({ min: 6.0, max: 10.8 });
/** The watchdog oscillator, in Hz: 128 kHz is the datasheet's nominal, from which its Table 8-5
 * typical time-outs follow; its typical curves at 5 V (Figure 30-34) lie between about 112.5 kHz
 * (85 degC) and 121.5 kHz (-40 degC). The datasheet gives no bound; a scenario runs either end. */
export const WATCHDOG_OSCILLATOR_HZ = Object.freeze({ min: 112_000, max: 128_000, nominal: 128_000 });
/** The seed of the pattern SRAM holds at power-on (the datasheet gives SRAM no initial value). */
const DEFAULT_SRAM_SEED = 1;

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function only(value, where, allowed, required = []) {
  if (!isObject(value)) throw new ScenarioError(where, 'it is not an object');
  for (const key of Object.keys(value)) {
    if (!allowed.includes(key)) throw new ScenarioError(`${where}.${key}`, 'the field is unknown');
  }
  for (const key of required) {
    if (!(key in value)) throw new ScenarioError(`${where}.${key}`, 'the field is required');
  }
}

function number(value, where, { min = -1e9, max = 1e9, integer = false } = {}) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new ScenarioError(where, 'it is not a finite number');
  }
  if (integer && !Number.isInteger(value)) throw new ScenarioError(where, 'it is not an integer');
  if (value < min || value > max) {
    throw new ScenarioError(where, `it is not between ${min} and ${max}`);
  }
  return value;
}

function oneOf(value, where, allowed) {
  if (typeof value !== 'string' || !allowed.has(value)) {
    throw new ScenarioError(where, `it is not one of ${[...allowed].join(', ')}`);
  }
  return value;
}

function list(value, where, max) {
  if (!Array.isArray(value)) throw new ScenarioError(where, 'it is not a list');
  if (value.length > max) throw new ScenarioError(where, `it holds more than ${max} entries`);
  return value;
}

function time(value, where, duration) {
  return number(value, where, { min: 0, max: duration });
}

/** A piecewise-linear profile: [[t_s, value], ...], times strictly rising, held at both ends. */
function profile(value, where, duration, bound) {
  const points = list(value, where, MAX_POINTS);
  if (points.length === 0) throw new ScenarioError(where, 'it holds no point');
  let last = -1;
  return points.map((point, i) => {
    const at = `${where}[${i}]`;
    if (!Array.isArray(point) || point.length !== 2) {
      throw new ScenarioError(at, 'a point is not [time_s, value]');
    }
    const t = time(point[0], `${at}[0]`, duration);
    if (t <= last) throw new ScenarioError(`${at}[0]`, 'the times do not rise');
    last = t;
    return [t, number(point[1], `${at}[1]`, { min: -bound, max: bound })];
  });
}

function interval(item, where, duration) {
  const start = time(item.start_s, `${where}.start_s`, duration);
  const end = time(item.end_s, `${where}.end_s`, duration);
  if (end <= start) throw new ScenarioError(`${where}.end_s`, 'it is not after start_s');
  return { start_s: start, end_s: end };
}

function noOverlap(items, where, key) {
  const groups = new Map();
  items.forEach((item, i) => {
    const group = key(item);
    if (!groups.has(group)) groups.set(group, []);
    groups.get(group).push([item, i]);
  });
  for (const entries of groups.values()) {
    entries.sort((a, b) => a[0].start_s - b[0].start_s);
    for (let i = 1; i < entries.length; i += 1) {
      if (entries[i][0].start_s < entries[i - 1][0].end_s) {
        throw new ScenarioError(`${where}[${entries[i][1]}]`, 'it overlaps another of its kind');
      }
    }
  }
}

function triple(value, where) {
  if (!Array.isArray(value) || value.length !== 3) {
    throw new ScenarioError(where, 'it is not three counts [x, y, z]');
  }
  return value.map((v, i) => number(v, `${where}[${i}]`, { min: -32768, max: 32767, integer: true }));
}

function imu(value, duration) {
  const where = 'imu';
  only(value, where, ['pitch_rad', 'pitch_rate_rad_s', 'raw', 'gyro_zero_rate_dps', 'accel_zero_g_mg']);
  const level = (field, unit, typical, fallback) => {
    if (value[field] === undefined) return fallback;
    const at = `${where}.${field}`;
    if (!Array.isArray(value[field]) || value[field].length !== 3) {
      throw new ScenarioError(at, `it is not three ${unit} [x, y, z]`);
    }
    const bound = { min: -ZERO_LEVEL_FACTOR * typical, max: ZERO_LEVEL_FACTOR * typical };
    return value[field].map((v, i) => number(v, `${at}[${i}]`, bound));
  };
  const zeroRate = level('gyro_zero_rate_dps', 'rates', GYRO_ZERO_RATE_LIMIT_DPS, DEFAULT_GYRO_ZERO_RATE_DPS);
  const zeroG = level('accel_zero_g_mg', 'levels', ACCEL_ZERO_G_TYPICAL_MG, DEFAULT_ACCEL_ZERO_G_MG);
  const out = {
    pitch_rad: value.pitch_rad ? profile(value.pitch_rad, `${where}.pitch_rad`, duration, 100) : [[0, 0]],
    pitch_rate_rad_s: value.pitch_rate_rad_s
      ? profile(value.pitch_rate_rad_s, `${where}.pitch_rate_rad_s`, duration, 1000)
      : null,
    raw: [],
    gyro_zero_rate_dps: [...zeroRate],
    accel_zero_g_mg: [...zeroG],
  };
  if (value.raw !== undefined) {
    let last = -1;
    out.raw = list(value.raw, `${where}.raw`, MAX_POINTS).map((entry, i) => {
      const at = `${where}.raw[${i}]`;
      only(entry, at, ['t_s', 'gyro', 'accel'], ['t_s', 'gyro', 'accel']);
      const t = time(entry.t_s, `${at}.t_s`, duration);
      if (t <= last) throw new ScenarioError(`${at}.t_s`, 'the times do not rise');
      last = t;
      return { t_s: t, gyro: triple(entry.gyro, `${at}.gyro`), accel: triple(entry.accel, `${at}.accel`) };
    });
  }
  return out;
}

function faults(value, duration) {
  const items = list(value, 'faults', MAX_ITEMS).map((item, i) => {
    const where = `faults[${i}]`;
    if (!isObject(item)) throw new ScenarioError(where, 'it is not an object');
    const kind = oneOf(item.kind, `${where}.kind`, FAULT_KINDS);
    const fields = { nack: ['device'], sda_held: ['release'], stale: [], saturated: ['sensor', 'axes'] }[kind];
    only(item, where, ['kind', 'start_s', 'end_s', ...fields], ['kind', 'start_s', 'end_s', ...fields]);
    const fault = { kind, ...interval(item, where, duration) };
    if (kind === 'nack') fault.device = oneOf(item.device, `${where}.device`, DEVICES);
    if (kind === 'sda_held') fault.release = oneOf(item.release, `${where}.release`, RELEASES);
    if (kind === 'saturated') {
      fault.sensor = oneOf(item.sensor, `${where}.sensor`, SENSORS);
      const axes = list(item.axes, `${where}.axes`, 3);
      if (!axes.length) throw new ScenarioError(`${where}.axes`, 'it names no axis');
      axes.forEach((axis, j) => oneOf(axis, `${where}.axes[${j}]`, new Set(AXES)));
      if (new Set(axes).size !== axes.length) throw new ScenarioError(`${where}.axes`, 'it names an axis twice');
      fault.axes = AXES.filter((axis) => axes.includes(axis));
    }
    return fault;
  });
  noOverlap(items, 'faults', (fault) => `${fault.kind}:${fault.device ?? ''}`);
  return items;
}

/**
 * Read a scenario from its file's text.
 *
 * @param {string} text the file's contents
 * @returns {object} the scenario, every default filled in
 * @throws {ScenarioError} the text is too long, not JSON, or not a scenario
 */
export function readScenario(text) {
  if (typeof text !== 'string' || Buffer.byteLength(text, 'utf8') > MAX_SCENARIO_BYTES) {
    throw new ScenarioError('the file', `it holds more than ${MAX_SCENARIO_BYTES} bytes`);
  }
  let raw;
  try {
    raw = JSON.parse(text);
  } catch {
    throw new ScenarioError('the file', 'it is not JSON text');
  }
  const top = [
    'avrsim_scenario', 'duration_s', 'imu', 'encoders', 'faults', 'buttons', 'stalls',
    'usb_sof', 'battery_v', 'probes', 'markers', 'trace', 'bootloader', 'motors_off_hold_s',
    'watchdog_oscillator_hz', 'sram_seed',
  ]; // prettier-ignore
  only(raw, 'the scenario', top, ['avrsim_scenario', 'duration_s']);
  if (raw.avrsim_scenario !== SCENARIO_VERSION) {
    throw new ScenarioError('avrsim_scenario', `this rig reads version ${SCENARIO_VERSION}`);
  }
  const duration = number(raw.duration_s, 'duration_s', { min: 1e-6, max: MAX_DURATION_S });
  const scenario = { duration_s: duration };
  scenario.imu = imu(raw.imu ?? {}, duration);

  only(raw.encoders ?? {}, 'encoders', ['left_rev_s', 'right_rev_s']);
  const encoders = raw.encoders ?? {};
  scenario.encoders = {};
  for (const side of ['left', 'right']) {
    const key = `${side}_rev_s`;
    scenario.encoders[side] = encoders[key]
      ? profile(encoders[key], `encoders.${key}`, duration, 1000)
      : [[0, 0]];
  }

  scenario.faults = faults(raw.faults ?? [], duration);

  scenario.buttons = list(raw.buttons ?? [], 'buttons', MAX_ITEMS).map((item, i) => {
    const where = `buttons[${i}]`;
    only(item, where, ['button', 'start_s', 'end_s'], ['button', 'start_s', 'end_s']);
    return { button: oneOf(item.button, `${where}.button`, BUTTONS), ...interval(item, where, duration) };
  });
  noOverlap(scenario.buttons, 'buttons', (press) => press.button);

  scenario.stalls = list(raw.stalls ?? [], 'stalls', MAX_ITEMS).map((item, i) => {
    const where = `stalls[${i}]`;
    only(item, where, ['start_s', 'end_s', 'interrupts'], ['start_s', 'end_s', 'interrupts']);
    if (typeof item.interrupts !== 'boolean') {
      throw new ScenarioError(`${where}.interrupts`, 'it is not true or false');
    }
    return { ...interval(item, where, duration), interrupts: item.interrupts };
  });
  noOverlap(scenario.stalls, 'stalls', () => 'stall');

  if (raw.usb_sof !== undefined && typeof raw.usb_sof !== 'boolean') {
    throw new ScenarioError('usb_sof', 'it is not true or false');
  }
  scenario.usb_sof = raw.usb_sof ?? false;
  scenario.battery_v = raw.battery_v === undefined ? 7.2 : number(raw.battery_v, 'battery_v', BATTERY_V);
  scenario.watchdog_oscillator_hz =
    raw.watchdog_oscillator_hz === undefined
      ? WATCHDOG_OSCILLATOR_HZ.nominal
      : number(raw.watchdog_oscillator_hz, 'watchdog_oscillator_hz', WATCHDOG_OSCILLATOR_HZ);
  scenario.sram_seed =
    raw.sram_seed === undefined
      ? DEFAULT_SRAM_SEED
      : number(raw.sram_seed, 'sram_seed', { min: 0, max: 0xffffffff, integer: true });
  // The board's reset path: the A-Star 32U4 bootloader the Balboa ships with, unless the
  // scenario names "none" (a chip programmed without it).
  scenario.bootloader = raw.bootloader === undefined ? 'a-star' : oneOf(raw.bootloader, 'bootloader', BOOTLOADERS);
  scenario.motors_off_hold_s =
    raw.motors_off_hold_s === undefined
      ? DEFAULT_MOTORS_OFF_HOLD_S
      : number(raw.motors_off_hold_s, 'motors_off_hold_s', { min: 1e-4, max: duration });

  const symbols = new Set();
  scenario.probes = list(raw.probes ?? [], 'probes', MAX_PROBES).map((item, i) => {
    const where = `probes[${i}]`;
    only(item, where, ['symbol', 'period_s'], ['symbol']);
    if (typeof item.symbol !== 'string' || !SYMBOL.test(item.symbol)) {
      throw new ScenarioError(`${where}.symbol`, 'it is not a symbol name');
    }
    if (symbols.has(item.symbol)) throw new ScenarioError(`${where}.symbol`, 'it is named twice');
    symbols.add(item.symbol);
    const probe = { symbol: item.symbol, period_s: null };
    if (item.period_s !== undefined) {
      probe.period_s = number(item.period_s, `${where}.period_s`, { min: 1e-6, max: duration });
    }
    return probe;
  });

  const names = new Set();
  scenario.markers = list(raw.markers ?? [], 'markers', MAX_ITEMS).map((item, i) => {
    const where = `markers[${i}]`;
    only(item, where, ['name', 't_s'], ['name', 't_s']);
    if (typeof item.name !== 'string' || !NAME.test(item.name)) {
      throw new ScenarioError(`${where}.name`, 'it is not a plain name');
    }
    if (names.has(item.name)) throw new ScenarioError(`${where}.name`, 'it is named twice');
    names.add(item.name);
    return { name: item.name, t_s: time(item.t_s, `${where}.t_s`, duration) };
  });

  only(raw.trace ?? {}, 'trace', ['input_edges', 'max_lines']);
  const trace = raw.trace ?? {};
  if (trace.input_edges !== undefined && typeof trace.input_edges !== 'boolean') {
    throw new ScenarioError('trace.input_edges', 'it is not true or false');
  }
  scenario.trace = {
    input_edges: trace.input_edges ?? false,
    max_lines:
      trace.max_lines === undefined
        ? DEFAULT_TRACE_LINES
        : number(trace.max_lines, 'trace.max_lines', { min: 1, max: MAX_TRACE_LINES, integer: true }),
  };
  return scenario;
}

/** A piecewise-linear profile's value at `t`, held before its first point and after its last. */
export function profileAt(points, t) {
  if (t <= points[0][0]) return points[0][1];
  const last = points[points.length - 1];
  if (t >= last[0]) return last[1];
  let lo = 0;
  let hi = points.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (points[mid][0] <= t) lo = mid;
    else hi = mid;
  }
  const [t0, v0] = points[lo];
  const [t1, v1] = points[hi];
  return v0 + ((v1 - v0) * (t - t0)) / (t1 - t0);
}

/** A profile's slope at `t`: that of the segment `t` lies in, 0 before the first point and after
 * the last; at a point, the segment that starts there. */
export function slopeAt(points, t) {
  if (t < points[0][0] || t >= points[points.length - 1][0]) return 0;
  let lo = 0;
  while (lo + 1 < points.length && points[lo + 1][0] <= t) lo += 1;
  const [t0, v0] = points[lo];
  const [t1, v1] = points[lo + 1];
  return (v1 - v0) / (t1 - t0);
}
