// The `balboa32u4` board model: what is wired to the ATmega32U4 on a Pololu Balboa 32U4.
//
// Pins and addresses are the provisioned Balboa32U4 1.1.2 library's (Balboa32U4Encoders.cpp,
// Balboa32U4Motors.cpp, Balboa32U4Buttons.h, Balboa32U4.h, FastGPIO.h's pin table for the
// 32U4); the sensors' behaviour is imu.js's. Fixed per environment version: a session does not
// extend it, and a device it lacks is the work's own model or not shown.
//
// - Encoders: left channel XOR on PB4 (PCINT4), left B on PE2; right XOR on PE6 (INT6), right B
//   on PF0. 12 counts per motor-shaft revolution (Balboa32U4Encoders.h), both edges of both
//   channels; a scenario's positive rate is the direction the library counts up, which is not
//   necessarily the wheel's forward direction (that sign is the board's wiring, not shown).
// - Buttons A on PB3, B on PD5, C on PB0, each pulling its pin low when pressed against the
//   board's resistor; B and C share their pins with the green and red LEDs.
// - I2C: SCL on PD0, SDA on PD1, held high by the board; the LSM6DS33 at 0x6B and the LIS3MDL
//   at 0x1E.
// - Battery: VBAT / 3 on ADC6 (A1), read against AVCC = 5 V (readBatteryMillivolts): the one
//   thing the ADC has a value for besides its band gap and ground.
// - Motors, observed: left PWM on PB6 (OC1B) with direction PB2, right PWM on PB5 (OC1A) with
//   direction PB1 (Balboa32U4Motors.cpp: PWM_L 10, PWM_R 9, DIR_L 16, DIR_R 15). Each PWM pin is
//   a DRV8838's EN input: EN low brakes the motor whatever PH is (TI DRV8838 datasheet, Table
//   7-2 "DRV8838 Device Logic"). EN has a 100 kOhm pull-down (RPD); a pin left as an input with
//   its 20 to 50 kOhm pull-up on reads high through that divider (VIH is at most 0.5 VCC), so
//   EN is high when the pin drives high or is an input pulled up, and low otherwise.
// - Any other pin with its pull-up enabled reads high; with none it reads low. A floating input is
//   neither, and an unattached one is not shown (NOT_SHOWN).

import { LIS3MDL, LIS3MDL_ADDRESS, LSM6DS33, LSM6DS33_ADDRESS } from './imu.js';
import { FREQUENCY_HZ, REG } from './mcu.js';
import { profileAt, slopeAt } from './scenario.js';

export const BOARD = 'balboa32u4';
export const BOARD_VERSION = 1;
export const COUNTS_PER_MOTOR_REVOLUTION = 12;

/** The motor outputs the summary observes. */
export const MOTOR_PINS = Object.freeze({
  left: { pwm: ['B', 6], pwmName: 'PB6', compare: 'OCR1B', direction: ['B', 2], directionName: 'PB2' },
  right: { pwm: ['B', 5], pwmName: 'PB5', compare: 'OCR1A', direction: ['B', 1], directionName: 'PB1' },
});

const ENCODER_PINS = {
  left: { xor: ['B', 4], b: ['E', 2] },
  right: { xor: ['E', 6], b: ['F', 0] },
};
const BUTTON_PINS = { A: ['B', 3], B: ['D', 5], C: ['B', 0] };
const SCL = ['D', 0];
const SDA = ['D', 1];
const BATTERY_CHANNEL = 6;
const SCL_PULSES_TO_RELEASE = 9;
/** The longest the board waits before looking at an encoder's rate again. */
const ENCODER_LOOK_S = 1e-3;
/** The quadrature state (A, B) for a count modulo 4, in the order the library counts up. */
const QUADRATURE = [
  [0, 0],
  [0, 1],
  [1, 1],
  [1, 0],
];

const seconds = (cycles) => cycles / FREQUENCY_HZ;
const cyclesAt = (s) => Math.round(s * FREQUENCY_HZ);

export class Balboa32U4 {
  /**
   * @param {object} scenario a read scenario (scenario.js)
   * @param {{onImuWrite?: Function, onInput?: Function, onUnmodelled?: Function,
   *   onEvidenceEnd?: Function, onOutputRead?: Function}} observers
   */
  constructor(scenario, observers = {}) {
    this.scenario = scenario;
    this.onInput = observers.onInput ?? (() => {});
    this.chip = null;
    this.faults = scenario.faults.map((fault) => ({ ...fault, released: false }));
    const faultsAt = (device) => (t) => this.faultsAt(t, device);
    this.lsm6 = new LSM6DS33({
      motion: (t) => this.motion(t),
      raw: (t) => this.rawAt(t),
      faults: faultsAt('lsm6ds33'),
      onWrite: observers.onImuWrite,
      onUnmodelled: observers.onUnmodelled,
      onEvidenceEnd: observers.onEvidenceEnd,
      onOutputRead: observers.onOutputRead,
      zeroRateDps: scenario.imu.gyro_zero_rate_dps,
      zeroGMg: scenario.imu.accel_zero_g_mg,
    });
    this.lis3mdl = new LIS3MDL({
      faults: faultsAt('lis3mdl'),
      onUnmodelled: observers.onUnmodelled,
      onEvidenceEnd: observers.onEvidenceEnd,
    });
    this.devices = new Map([
      [LSM6DS33_ADDRESS, this.lsm6],
      [LIS3MDL_ADDRESS, this.lis3mdl],
    ]);
    this.selected = null;
    this.encoders = {};
    for (const side of ['left', 'right']) {
      this.encoders[side] = { profile: scenario.encoders[side], phase: 0, count: 0, t: 0, edges: 0 };
    }
    this.buttons = scenario.buttons;
    this.sclPulses = 0;
    this.sclLevel = 1;
    // The chip's TWI asks `held()` before each byte: with SDA held low it settles the bits on
    // the bus itself (mcu.js TimedTWI), and the board answers only when SDA is free.
    this.bus = {
      held: () => this.sdaHeld(),
      start: () => !this.sdaHeld(),
      stop: () => {
        if (this.sdaHeld()) return false; // SDA cannot rise: no STOP condition
        this.selected = null;
        return true;
      },
      lost: () => {
        this.selected = null;
      },
      connect: (address, write) => {
        const t = this.now();
        const device = this.devices.get(address);
        if (!device || !device.acknowledges(t)) {
          this.selected = null;
          return false;
        }
        this.selected = device;
        device.begin(write);
        return true;
      },
      write: (value) => (this.selected ? this.selected.write(value, this.now()) : false),
      read: () => (this.sdaHeld() ? 0 : this.selected ? this.selected.read(this.now()) : 0xff),
    };
  }

  now() {
    return seconds(this.chip.cpu.cycles);
  }

  motion(t) {
    const { imu } = this.scenario;
    const pitch = profileAt(imu.pitch_rad, t);
    const rate = imu.pitch_rate_rad_s ? profileAt(imu.pitch_rate_rad_s, t) : slopeAt(imu.pitch_rad, t);
    return { pitch_rad: pitch, pitch_rate_rad_s: rate };
  }

  rawAt(t) {
    const { raw } = this.scenario.imu;
    let found = null;
    for (const entry of raw) {
      if (entry.t_s > t) break;
      found = entry;
    }
    return found;
  }

  faultsAt(t, device) {
    const state = { nack: false, stale_since: null, saturated: null };
    for (const fault of this.faults) {
      if (t < fault.start_s || t >= fault.end_s) continue;
      if (fault.kind === 'nack' && fault.device === device) state.nack = true;
      if (device !== 'lsm6ds33') continue;
      if (fault.kind === 'stale') state.stale_since = fault.start_s;
      if (fault.kind === 'saturated') state.saturated = { sensor: fault.sensor, axes: fault.axes };
    }
    return state;
  }

  sdaHeld() {
    const t = this.now();
    return this.faults.some(
      (fault) => fault.kind === 'sda_held' && !fault.released && t >= fault.start_s && t < fault.end_s,
    );
  }

  /** Wire the board to a chip just out of reset. */
  attach(chip) {
    this.chip = chip;
    this.selected = null;
    const driven = { B: 0, C: 0, D: 0, E: 0, F: 0 };
    const mark = ([letter, index]) => {
      driven[letter] |= 1 << index;
    };
    for (const pins of Object.values(ENCODER_PINS)) Object.values(pins).forEach(mark);
    Object.values(BUTTON_PINS).forEach(mark);
    mark(SCL);
    mark(SDA);
    for (const [letter, port] of Object.entries(chip.ports)) {
      const mask = driven[letter];
      const pullUps = () => {
        const ddr = chip.cpu.data[port.portConfig.DDR];
        const out = chip.cpu.data[port.portConfig.PORT];
        for (let index = 0; index < 8; index += 1) {
          const bit = 1 << index;
          if (mask & bit || ddr & bit) continue;
          port.setPin(index, !!(out & bit));
        }
      };
      port.addListener(pullUps);
      if (letter === SCL[0]) port.addListener(() => this.sclEdge());
    }
    this.sclLevel = 1;
    chip.adc.channelValues[BATTERY_CHANNEL] = this.scenario.battery_v / 3;
    this.applyInputs(true);
  }

  /** Bus recovery: nine SCL clocks with the interface off. A clock is a rise of SCL's level,
   * whatever makes it: the pin driven high, or released (DDR cleared) to the board's pull-up, as
   * an open-drain line is clocked. */
  sclEdge() {
    const bit = 1 << SCL[1];
    const { data } = this.chip.cpu;
    const port = this.chip.ports[SCL[0]];
    const level = data[REG.DDRD] & bit ? port.lastValue & bit : 1; // the board holds SCL up
    const rose = level && !this.sclLevel;
    this.sclLevel = level ? 1 : 0;
    if (!rose || data[REG.TWCR] & 0x04) return;
    const held = this.faults.find(
      (fault) => fault.kind === 'sda_held' && !fault.released && fault.release === 'scl_pulses' && this.active(fault),
    );
    if (!held) return;
    this.sclPulses += 1;
    if (this.sclPulses >= SCL_PULSES_TO_RELEASE) {
      held.released = true;
      this.sclPulses = 0;
      this.setPin(SDA, true);
    }
  }

  active(fault) {
    const t = this.now();
    return t >= fault.start_s && t < fault.end_s;
  }

  setPin([letter, index], value) {
    this.chip.ports[letter].setPin(index, !!value);
  }

  /** Set every input the board drives to what it is now; `initial` sets them without tracing. */
  applyInputs(initial = false) {
    const t = this.now();
    for (const [side, pins] of Object.entries(ENCODER_PINS)) {
      const [a, b] = QUADRATURE[((this.encoders[side].count % 4) + 4) % 4];
      this.setPin(pins.b, b);
      this.setPin(pins.xor, a ^ b);
    }
    for (const [button, pin] of Object.entries(BUTTON_PINS)) {
      const pressed = this.buttons.some((p) => p.button === button && t >= p.start_s && t < p.end_s);
      this.setPin(pin, !pressed);
    }
    this.setPin(SCL, true);
    this.setPin(SDA, !this.sdaHeld());
    if (!initial) this.onInput('inputs', t);
  }

  /** The next cycle after `cycle` at which the board changes an input. */
  nextChange(cycle) {
    const t = seconds(cycle);
    let next = Infinity;
    const later = (s) => {
      const c = cyclesAt(s);
      if (c > cycle && c < next) next = c;
    };
    for (const press of this.buttons) {
      later(press.start_s);
      later(press.end_s);
    }
    for (const fault of this.faults) {
      if (fault.kind !== 'sda_held') continue;
      later(fault.start_s);
      later(fault.end_s);
    }
    for (const encoder of Object.values(this.encoders)) {
      // Never now: a look due within this cycle is taken at the next one.
      const c = Math.max(cycle + 1, Math.ceil(this.encoderLook(encoder, t) * FREQUENCY_HZ));
      if (c < next) next = c;
    }
    return next;
  }

  /** Apply every change due by now. */
  advance() {
    const t = this.now();
    for (const [side, encoder] of Object.entries(this.encoders)) {
      this.integrate(encoder, t);
      const target = Math.round(encoder.phase);
      while (encoder.count !== target) {
        encoder.count += encoder.count < target ? 1 : -1;
        encoder.edges += 1;
        const [a, b] = QUADRATURE[((encoder.count % 4) + 4) % 4];
        const pins = ENCODER_PINS[side];
        this.setPin(pins.b, b);
        this.setPin(pins.xor, a ^ b);
        this.onInput(`encoder_${side}`, t, encoder.count);
      }
    }
    for (const [button, pin] of Object.entries(BUTTON_PINS)) {
      const pressed = this.buttons.some((p) => p.button === button && t >= p.start_s && t < p.end_s);
      const level = !pressed;
      const [letter, index] = pin;
      const port = this.chip.ports[letter];
      if (!!(port.pinValue & (1 << index)) !== level) {
        this.setPin(pin, level);
        this.onInput(`button_${button}`, t, pressed ? 1 : 0);
      }
    }
    const sda = !this.sdaHeld();
    const port = this.chip.ports[SDA[0]];
    if (!!(port.pinValue & (1 << SDA[1])) !== sda) {
      this.setPin(SDA, sda);
      this.onInput('sda', t, sda ? 1 : 0);
    }
  }

  /** Move an encoder's phase on to `t` by the trapezoid rule, exact for its piecewise-linear
   * rate when every breakpoint between is stepped on. */
  integrate(encoder, t) {
    let from = encoder.t;
    if (t <= from) return;
    const breaks = encoder.profile.map(([s]) => s).filter((s) => s > from && s < t);
    for (const to of [...breaks, t]) {
      const rate = (profileAt(encoder.profile, from) + profileAt(encoder.profile, to)) / 2;
      encoder.phase += rate * COUNTS_PER_MOTOR_REVOLUTION * (to - from);
      from = to;
    }
    encoder.t = t;
  }

  /** When to look at an encoder next: its next count at the present rate, no later than the
   * next breakpoint of its profile or ENCODER_LOOK_S from now. */
  encoderLook(encoder, t) {
    const rate = profileAt(encoder.profile, t) * COUNTS_PER_MOTOR_REVOLUTION;
    let next = t + ENCODER_LOOK_S;
    const breakpoint = encoder.profile.find(([s]) => s > t);
    if (breakpoint && breakpoint[0] < next) next = breakpoint[0];
    if (Math.abs(rate) > 1e-9) {
      // A count changes when the phase passes half-way to the next one, either way.
      const n = Math.round(encoder.phase);
      const distance = rate > 0 ? n + 0.5 - encoder.phase : encoder.phase - (n - 0.5);
      next = Math.min(next, t + Math.max(distance, 1e-9) / Math.abs(rate));
    }
    return next;
  }

  encoderEdges() {
    return { left: this.encoders.left.edges, right: this.encoders.right.edges };
  }

  encoderCounts() {
    return { left: this.encoders.left.count, right: this.encoders.right.count };
  }
}
