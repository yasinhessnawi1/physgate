// One run: the firmware on the chip on the board, driven by the scenario, measured.
//
// Measurements are taken from the CPU as it runs, never from the firmware's own reports:
//
// - an interrupt's execution time is the cycles from the CPU's acceptance of it (the cycle count
//   before the vector is entered, the interrupt response of four cycles included: the 32U4's
//   program counter is two bytes, so its pushes and RETI's pops are two, not the datasheet's
//   three-byte figure of five) to the end of its RETI. Both are given: inclusive, with the
//   interrupts that nested in it, and exclusive, without them. An interrupt left without a RETI
//   (its return address taken off the stack by anything else) is counted as such and dropped;
// - after SEI and after RETI one more instruction runs before a pending interrupt is taken
//   (datasheet "Interrupt Response Time" and the SEI example);
// - the stack's high-water mark is the least stack pointer after any instruction, and its
//   headroom the distance from it down to the highest the heap reached (avr-libc's __brkval,
//   taken whenever both its bytes have been written) or, below that, to the end of static data
//   (__heap_start); a negative headroom is a collision of stack and heap;
// - idle sleep (SMCR SM2..0 = 000) halts the CPU while the clocks run, until an interrupt is
//   taken, which costs five cycles more than from active mode (datasheet "Interrupt Response
//   Time"; "Power Management and Sleep Modes" says four: the rig takes the longer); any other
//   sleep mode, or idle with interrupts off, ends the run's evidence at that SLEEP;
// - a probe is a function symbol of the ELF: an entry is the CPU arriving at its address, its
//   return the RET (or RETI) executed at the stack depth it was entered at; its statistics start
//   again at each reset and are given per reset as well as over the run; its lateness is against
//   the grid of its period through the earliest phase any of its entries kept (LATENESS);
// - a PWM output's period and high time are taken between the pin's own edges while a timer's
//   compare unit drives it;
// - the motors are off while both DRV8838 enable inputs (PB5 and PB6) are low, from their pins'
//   levels (board.js), for at least `motors_off_hold_s` without a break; the compare registers'
//   zero is kept beside it as `ocr_zero_cycle`, which is not the motors' state;
// - the input-to-output delay is bounded from the sensor reads and the compare writes the rig
//   sees: it cannot see which sample a command was computed from (see `inputToOutput`).
//
// The board's reset path (`RESET_PATH`): after any reset the internal reset is stretched by the
// start-up time the fuses give, and the A-Star 32U4 bootloader then runs before the sketch.

import { avrInstruction } from 'avr8js';

import { BOARD, BOARD_VERSION, Balboa32U4, MOTOR_PINS } from './board.js';
import { INVALID_SAMPLE_VALUE, lsm6Name } from './imu.js';
import { WATCHDOG_OSCILLATOR_HZ } from './scenario.js';
import {
  ATmega32U4,
  CountingEEPROM,
  EEPROM_BYTES,
  FREQUENCY_HZ,
  MCUSR_BORF,
  MCUSR_EXTRF,
  MCUSR_PORF,
  MCUSR_WDRF,
  PLL_LOCK_CYCLES,
  RAMEND,
  REG,
  SRAM_BYTES,
  VECTORS,
  VECTOR_TABLE_WORDS,
  effectsOf,
  observeWrite,
  vectorName,
} from './mcu.js';

const F_RET = 1;
const F_RETI = 2;
const F_PROBE = 4;
const F_SLEEP = 8;
const F_SPM = 16;
const F_SEI = 32;
const F_USB_WRITE = 64;
const F_LPM = 128;
const OP_RET = 0x9508;
const OP_SEI = 0x9478;
const OP_RETI = 0x9518;
const OP_SLEEP = 0x9588;
const OP_SPM = 0x95e8;
const OP_SPM_Z = 0x95f8;
/** LPM and ELPM, in every form: the byte they read at Z (with RAMPZ) must lie in flash. */
const isProgramRead = (word) => word === 0x95c8 || word === 0x95d8 || (word & 0xfe0c) === 0x9004;
const isExtendedProgramRead = (word) => word === 0x95d8 || (word & 0xfe0e) === 0x9006;
const MAX_USART_TEXT = 64 << 10;
/** How late a timer-driven edge can be stamped: the longest instruction, four cycles. */
export const EDGE_RESOLUTION_CYCLES = 4;

/**
 * The start-up time after a reset: the Balboa's A-Star 32U4 low fuse is 0xFF (Pololu a-star
 * boards.txt, a-star32U4.bootloader.low_fuses), CKSEL0 = 1 and SUT1..0 = 11, a crystal with
 * slowly rising power: "Start-up Time" 16K CK and "Additional Delay from Reset" 14CK + 65 ms
 * (datasheet Table 6-4), both counted, as "the start-up sequence for the clock includes both the
 * time-out delay and the start-up time when the device starts up from reset" ("Clock Startup
 * Sequence"). 65 ms is the typical time-out at 5 V of 8K watchdog-oscillator cycles (Table 6-2):
 * a typical figure, taken at the nominal 128 kHz and scaled with the scenario's oscillator. It
 * follows every reset, power-on and watchdog alike ("Watchdog Reset": the delay timer counts
 * tTOUT).
 */
export function startUpCycles(watchdogHz = WATCHDOG_OSCILLATOR_HZ.nominal) {
  return Math.round(((0.065 * WATCHDOG_OSCILLATOR_HZ.nominal) / watchdogHz) * FREQUENCY_HZ) + 14 + 16_384;
}
export const START_UP_CYCLES = startUpCycles();
/** The extra cycles an interrupt takes to respond when it wakes the CPU from sleep: "increased by
 * five clock cycles" ("Interrupt Response Time"; "Power Management and Sleep Modes" gives four).
 * The ATmega328P's datasheet, whose program counter is two bytes as the 32U4's 16K words need,
 * says four, so the five is probably one cycle pessimistic: kept at the 32U4 datasheet's figure,
 * which only ever lengthens a measured latency. */
export const SLEEP_WAKE_CYCLES = 5;
/** What the lateness figures are, as the summary names them. */
const LATENESS =
  "per entry n of an epoch (from 0): (entry_n - n * period) - min over the epoch's entries m of (entry_m - m * " +
  'period), never negative: the lateness against the grid of the period whose phase is the earliest any entry ' +
  "kept. No entry can make another's lateness smaller: an entry early on its grid lowers the reference, which " +
  'makes every other later, and a late first entry is late itself. lateness_from_first_entry_cycles is the ' +
  'figure against the first entry: entry_n - (entry_0 + n * period).';
/** What the output does not show, whatever the run. */
export const NOT_SHOWN = Object.freeze([
  'brown-out beyond its reset: the chip resets below VBOT (4.0 to 4.5 V, typically 4.3 ' +
    "V; datasheet Table 8-1); the battery range is the model's own, 6.0 V (1.0 V a cell " +
    "of six) to the motor drivers' 10.8 V, and says nothing of the board below it",
  "the 5 V rail near its drop-out: VCC and the ADC's reference AVCC stay at exactly " +
    '5.000 V whatever the battery, and the battery does not sag under motor load',
  'an external reset (the RESET pin or button) and the bootloader path it takes',
  "the inertial sensor's noise (rate noise density 7 mdps/sqrt(Hz)) and its filters' " +
    "delay; start-up settling beyond AN4682's discard tables; its temperature output, " +
    'constant at 25 degC',
  "the inertial sensor's zero levels are typical figures, not bounds (G_TyOff +-10 dps, " +
    'LA_TyOff +-40 mg: a scenario may state up to four times either, of either sign), and ' +
    'its drift with temperature (sensitivity +-1 % and +-1.5 %; zero level 0.5 mg/degC ' +
    'and 0.05 dps/degC) is not shown',
  'the magnetometer answers its address and its identity only: a read of its data ends ' +
    'the evidence, and a setting written to it is reported',
  'clock tolerance: the crystal is exactly 16 MHz; the watchdog oscillator and the ' +
    'start-up time-out are typical figures (typical_figures), with no bound in the ' +
    'datasheet',
  'stack headroom on paths the run did not execute: stack.headroom_bytes covers only ' +
    'the paths taken',
  '"off" means the DRV8838 brake (EN low, Table 7-2), not the motors free; a motors-off ' +
    'figure is evidence only with its hold time (motors_off_rule.hold_cycles) and ' +
    'motors_off_until_cycle or stayed_off_to_end',
  'I2C transfers at their fastest (no clock stretching by the sensor, no level-shifter ' +
    "delay) and the bootloader's session without its interrupts' latency: both are lower " +
    'bounds',
  'the I2C bus has the chip as its only master: the Raspberry Pi the board can be ' +
    'connected to is not shown, and a firmware that listens as a slave ends the evidence',
  'the scenario is open loop: the inertial sensor, the encoders and the battery follow ' +
    'the script and the motor outputs change nothing, so anything that needs the loop ' +
    'closed is not shown',
  'USB: detached, no host; blocking Serial writes, USB interrupts and the CDC session ' +
    "are not shown unless usb_sof is set, and the calls of Serial's write are counted " +
    '(usb.serial_write_calls) with their cost not shown',
  "USART1 receive: nothing sends, as on an unconnected pin, so a receive interrupt's " +
    'load never appears',
  'ADC accuracy: conversions are exact (the datasheet gives an absolute accuracy of +-2 ' +
    'LSB at 200 kHz), the 2.56 V and 1.1 V references and the band gap are exact, and its ' +
    'input noise and offset are not shown; a clock outside 50 to 200 kHz is reported ' +
    '(adc_clock)',
  'the encoders are perfect quadrature: no bounce, glitch, missed count or skew between ' +
    'their channels',
  'inputs nothing is wired to: a pin with no pull-up reads low and one with its pull-up ' +
    'reads high; a floating or unattached input is neither',
  "uninitialised SRAM is one seed's pattern (power_on_sram_seed): a criterion that " +
    'depends on it must run several seeds',
  'an edge on INT0 to INT3 or INT6 while its mask bit is clear does not set its flag ' +
    'here, as in avr8js; the datasheet does not settle whether the part sets it',
]);
/** The EEPROM's endurance (datasheet "EEPROM Data Memory": at least 100,000 write/erase cycles). */
export const EEPROM_ENDURANCE_CYCLES = 100_000;
/** The bootloader's own .data, which its start-up copies to 0x0100..0x01CD before main(), and its
 * .bss, zeroed at 0x01CE..0x01E3 (Pololu a-star bootloaders/caterina/Caterina-A-Star.map; the
 * bytes are Caterina-A-Star.hex at 0x7F2A..0x7FF7). */
const BOOT_DATA = Uint8Array.from(Buffer.from(
  '4341544552494e4100000800000000000008011201100102000008fb1f010101000201000109023e00020100' +
  '80320904000001020201000524001001042402040524060001070582030800ff09040100020a000000070504' +
  '0210000107058302100001040309043c0350006f006c006f006c007500200041002d00530074006100720020' +
  '003300320055003400200042006f006f0074006c006f0061006400650072000000260350006f006c006f006c' +
  '007500200043006f00720070006f0072006100740069006f006e00000000', 'hex'));
const BOOT_BSS = [0x01ce, 0x01e4];
/** The word the bootloader reads and zeroes at every start (Caterina.c: bootKeyPtr 0x0800), and
 * the key that, found there after a watchdog reset, keeps it running. */
const BOOT_KEY_ADDRESS = 0x0800;
const BOOT_KEY = 0x7777;
/** The bootloader's own session when it runs: it leaves after its Timeout counter passes 8000
 * (TIMEOUT_PERIOD), one count per Timer1 compare at OCR1A 250 with clk/64, each at least 251
 * timer counts of 64 cycles; a lower bound, its interrupt latency not counted. */
export const BOOT_SESSION_CYCLES = 8001 * 251 * 64;

/** What the summary says of the reset path, each point the documents leave open read the way
 * that does not flatter firmware. */
const RESET_PATH = {
  'a-star': [
    'start-up delay after every reset: 16K CK + 14CK + 65 ms (low fuse 0xFF, datasheet Table 6-4), the 65 ms a ' +
      'typical figure scaled with the watchdog oscillator',
    'the bootloader runs first (Pololu: "The bootloader always runs first immediately after the AVR is reset"): ' +
      'it clears PORF, EXTRF and WDRF in MCUSR (and BORF after a power-on), disables the watchdog, zeroes the word ' +
      'at 0x0800 and overwrites 0x0100..0x01E3 with its own data, then starts the sketch with Timer1 stopped, ' +
      'PORTB0 and PORTD5 set (its RX and TX LEDs off) and PORTC7 clear (Caterina.c main() and StartSketch()): ' +
      'the sketch cannot tell a watchdog reset from MCUSR',
    'the bootloader\'s own instructions before the sketch (some thousands of cycles by its code) are not counted',
    'its stack (from 0x0AFF down, a few bytes on this path) is not written: the sketch\'s own stack lies there',
    'a watchdog reset with 0x7777 at 0x0800 keeps the bootloader running for its timeout, taken as its lower bound ' +
      `${BOOT_SESSION_CYCLES} cycles; it leaves OCR1A at 250, the LED pins as outputs (DDRC7, DDRB0, DDRD5), ` +
      'USBE and PLLE set and the USB detached (Caterina.c SetupHardware(), USB_Detach(), StartSketch()); the rest ' +
      'of its USB state is not modelled, and the timing after such a session is not evaluable',
    `the PLL's lock is taken as ${PLL_LOCK_CYCLES} cycles (datasheet: "about several ms")`,
  ],
  none: [
    'start-up delay after every reset: 16K CK + 14CK + 65 ms (low fuse 0xFF, datasheet Table 6-4), the 65 ms a ' +
      'typical figure scaled with the watchdog oscillator',
    'no bootloader: the sketch reads MCUSR as the reset left it; after a watchdog reset WDRF holds the watchdog on ' +
      'at 16 ms, its count started when the delay ends',
    `the PLL's lock is taken as ${PLL_LOCK_CYCLES} cycles (datasheet: "about several ms")`,
  ],
};

/** What the zero levels the sensor reads at rest are, as the summary names them. */
const ZERO_LEVEL_STATEMENT = {
  gyro:
    "the gyroscope's zero-rate level is the datasheet's typical figure (G_TyOff, +-10 dps), not a bound: it gives " +
    'no maximum, and a scenario may state up to four times it, of either sign; a criterion that depends on it ' +
    'should run at both signs',
  accel:
    "the accelerometer's zero-g level is the datasheet's typical figure (LA_TyOff, +-40 mg), not a bound: a " +
    'scenario may state up to four times it, of either sign; with +40 mg on both axes an angle from atan2 of ' +
    'two axes reads about 2.3 degrees too far at upright, nothing at 45 degrees and the other way beyond it, ' +
    'so a criterion with an asymmetric band should run at both signs',
};

/** What the input-to-output figures are, as the summary names them. */
const INPUT_TO_OUTPUT_DEFINITION =
  'per write of OCR1A or OCR1B: the cycles from the instant the oldest LSM6DS33 sample (gyroscope or ' +
  'accelerometer, any byte) read since the previous write of the same register was taken, to the write ' +
  '(upper_bound_cycles); and from the newest such sample (newest_sample_cycles). A write with no read since ' +
  'the previous one is measured from the reads before that one. The rig sees reads and writes, not which ' +
  'data a command was computed from: upper_bound_cycles bounds the delay only for a command computed from ' +
  "what was read since that register was last written. The sensor's own filter delay (AN4682 Fig. 4: its " +
  'anti-aliasing and digital low-pass filters) is not included.';

/** The sleep modes by SMCR's SM2..0 (datasheet "SMCR"). */
const SLEEP_MODES = ['idle', 'adc_noise_reduction', 'power_down', 'power_save', 'reserved', 'reserved',
  'standby', 'extended_standby']; // prettier-ignore

/** SRAM at power-on: the datasheet gives it no initial value, so the rig fills it with a pattern
 * from the scenario's seed (mulberry32), the same on every platform. */
export function powerOnSram(seed) {
  const sram = new Uint8Array(SRAM_BYTES);
  let state = seed >>> 0;
  for (let i = 0; i < sram.length; i += 4) {
    state = (state + 0x6d2b79f5) >>> 0;
    let z = state;
    z = Math.imul(z ^ (z >>> 15), z | 1);
    z ^= z + Math.imul(z ^ (z >>> 7), z | 61);
    z = (z ^ (z >>> 14)) >>> 0;
    for (let j = 0; j < 4 && i + j < sram.length; j += 1) sram[i + j] = (z >>> (8 * j)) & 0xff;
  }
  return sram;
}

/** A figure the run cannot stand behind, in place of its value. */
const withheld = (because) => ({ withheld: because });

export class RigError extends Error {}

function stats() {
  return { count: 0, min: Infinity, max: -Infinity, total: 0 };
}

function add(s, value) {
  s.count += 1;
  if (value < s.min) s.min = value;
  if (value > s.max) s.max = value;
  s.total += value;
}

function report(s) {
  if (!s.count) return { count: 0 };
  return { count: s.count, min: s.min, max: s.max, mean: s.total / s.count };
}

/** An epoch's phases as lateness against the earliest of them (LATENESS). */
function againstEarliest(phases) {
  return { count: phases.count, min: 0, max: phases.max - phases.min, total: phases.total - phases.count * phases.min };
}

function merge(into, s) {
  into.count += s.count;
  into.min = Math.min(into.min, s.min);
  into.max = Math.max(into.max, s.max);
  into.total += s.total;
}

const toSeconds = (cycles) => cycles / FREQUENCY_HZ;

/** The trace: one JSON object per line, bounded; past the bound the run goes on and the summary
 * says where the trace stopped. */
export class Trace {
  constructor(write, maxLines) {
    this.write = write;
    this.maxLines = maxLines;
    this.lines = 0;
    this.truncatedAt = null;
    this.buffer = [];
    this.size = 0;
  }

  event(cycle, record) {
    if (this.lines >= this.maxLines) {
      this.truncatedAt ??= cycle;
      return;
    }
    const line = JSON.stringify({ c: cycle, ...record });
    this.lines += 1;
    this.buffer.push(line);
    this.size += line.length + 1;
    if (this.size > 1 << 16) this.flush();
  }

  header(record) {
    this.buffer.push(JSON.stringify(record));
    this.flush();
  }

  flush() {
    if (!this.buffer.length) return;
    this.write(`${this.buffer.join('\n')}\n`);
    this.buffer = [];
    this.size = 0;
  }
}

export class Rig {
  /**
   * @param {{flash: Uint8Array, eeprom: Uint8Array | null, symbols: Map}} elf a loaded ELF
   * @param {object} scenario a read scenario
   * @param {Trace} trace where the events go
   * @param {{nested?: boolean}} options `nested`: a run made for another's watchdog figures
   */
  constructor(elf, scenario, trace, options = {}) {
    this.scenario = scenario;
    this.trace = trace;
    const { flash } = elf;
    this.program = new Uint16Array(flash.buffer.slice(flash.byteOffset, flash.byteOffset + flash.byteLength));
    this.flags = new Uint8Array(this.program.length);
    this.program.forEach((word, pc) => {
      if (word === OP_RET) this.flags[pc] |= F_RET;
      else if (word === OP_RETI) this.flags[pc] |= F_RETI;
      else if (word === OP_SLEEP) this.flags[pc] |= F_SLEEP;
      else if (word === OP_SPM || word === OP_SPM_Z) this.flags[pc] |= F_SPM;
      else if (word === OP_SEI) this.flags[pc] |= F_SEI;
      else if (isProgramRead(word)) this.flags[pc] |= F_LPM;
    });
    this.probes = new Map();
    for (const probe of scenario.probes) {
      const symbol = elf.symbols.get(probe.symbol);
      if (!symbol || symbol.type !== 'function') {
        throw new RigError(
          `the probe ${probe.symbol} is not a function in the ELF (an inlined function has no ` +
            'address of its own: mark it noinline)',
        );
      }
      if (symbol.ambiguous) {
        throw new RigError(`the probe ${probe.symbol} names more than one function in the ELF`);
      }
      const word = symbol.value >> 1;
      if (symbol.value & 1 || word >= this.program.length) {
        throw new RigError(`the probe ${probe.symbol} has no address in flash`);
      }
      this.flags[word] |= F_PROBE;
      this.probes.set(word, {
        symbol: probe.symbol,
        period: probe.period_s === null ? null : probe.period_s * FREQUENCY_HZ,
        open: [],
        epochs: [],
        epoch: null,
      });
    }
    const heap = elf.symbols.get('__heap_start') ?? elf.symbols.get('_end');
    this.heapStart = heap ? heap.value & 0xffff : null;
    // avr-libc's heap break: malloc() and free() keep the heap's end in it, 0 until the first.
    const brk = elf.symbols.get('__brkval');
    this.brkAddress = brk && brk.type !== 'function' ? brk.value & 0xffff : null;
    this.heapEndMax = null;
    this.eeprom = new CountingEEPROM(EEPROM_BYTES);
    if (elf.eeprom) this.eeprom.memory.set(elf.eeprom);
    // Arduino's USB serial port and its other classes: the calls of `Serial.write` and of
    // `USB_Send`, which a HID or any other class sends through, are counted (the cost of a write to
    // a host is not shown).
    this.usbSerialWrites = 0;
    for (const name of ['_ZN7Serial_5writeEh', '_ZN7Serial_5writeEPKhj', '_Z8USB_SendhPKvi']) {
      const symbol = elf.symbols.get(name);
      if (symbol && symbol.type === 'function' && !(symbol.value & 1) && symbol.value >> 1 < this.program.length) {
        this.flags[symbol.value >> 1] |= F_USB_WRITE;
      }
    }
    this.elf = elf;
    this.nested = options.nested ?? false;
    this.watchdogUsed = false;

    this.vectors = new Map();
    this.unwound = {};
    this.frames = [];
    this.minSp = RAMEND;
    this.resets = [];
    this.unmodelled = {};
    this.ocr = { OCR1A: { value: 0, writes: 0, max: 0 }, OCR1B: { value: 0, writes: 0, max: 0 } };
    this.ocrTimeline = [[0, true]];
    this.enables = { left: false, right: false };
    this.offTimeline = [[0, true]];
    this.hold = Math.round(scenario.motors_off_hold_s * FREQUENCY_HZ);
    this.pwm = {};
    this.usart = { bytes: 0, text: '' };
    this.imuWrites = {};
    this.lastGyroSeen = null;
    this.ddrSeen = {};
    // Per compare register: the instants (s) of the samples read since its last write, and of
    // the last such batch.
    const window = () => ({ oldest: Infinity, newest: -Infinity, last: null });
    this.reads = { OCR1A: window(), OCR1B: window() };
    this.inputToOutput = { upper: stats(), newest: stats() };
    this.releaseAt = -1;
    this.bootSession = false;
    this.sleeping = false;
    this.sleep = { idle_entries: 0, wakes: 0, cycles_asleep: 0 };
    this.evidenceEnd = null;
    this.startUpCycles = startUpCycles(scenario.watchdog_oscillator_hz);
    this.twi = { addresses: 0, nacks: 0, arbitration_lost: 0, bytes: 0 };
    this.board = new Balboa32U4(scenario, {
      onImuWrite: (register, value) => {
        const name = lsm6Name(register);
        this.imuWrites[name] = value;
        this.trace.event(this.chip.cpu.cycles, { type: 'imu_write', register: name, value });
      },
      onInput: (what, t, value) => {
        if (scenario.trace.input_edges) this.trace.event(this.chip.cpu.cycles, { type: 'input', what, value });
      },
      onUnmodelled: (what) => this.noteUnmodelled(what),
      onEvidenceEnd: (cause, detail) => this.endEvidence(cause, detail),
      onOutputRead: (sensor, instant) => {
        for (const window of Object.values(this.reads)) {
          if (instant < window.oldest) window.oldest = instant;
          if (instant > window.newest) window.newest = instant;
        }
      },
    });
    this.chip = null;
  }

  noteUnmodelled(what) {
    const cycle = this.chip ? this.chip.cpu.cycles : 0;
    const entry = this.unmodelled[what];
    if (entry) {
      entry.count += 1;
      return;
    }
    this.unmodelled[what] = { first_cycle: cycle, count: 1 };
    this.trace.event(cycle, { type: 'unmodelled', what });
  }

  /** The run's evidence ends here: nothing after this cycle is the board's behaviour. */
  endEvidence(cause, detail) {
    if (this.evidenceEnd) return;
    const cycle = this.chip.cpu.cycles;
    this.evidenceEnd = { cycle, cause, ...detail };
    this.trace.event(cycle, { type: 'evidence_end', cause, ...detail });
  }

  build(mcusr, carried, cause) {
    const chip = new ATmega32U4(this.program, {
      ...carried,
      mcusr,
      eeprom: this.eeprom,
      sof: this.scenario.usb_sof,
      bus: this.board.bus,
      watchdogHz: this.scenario.watchdog_oscillator_hz,
      onTransfer: (transfer) => this.transfer(transfer),
      onUnmodelled: (what) => this.noteUnmodelled(what),
      onEvidenceEnd: (why, detail) => this.endEvidence(why, detail),
    });
    this.chip = chip;
    const { cpu } = chip;
    this.resets.push({ cycle: cpu.cycles, cause, sketch_start_cycle: null, mcusr_at_sketch_start: null });
    this.trace.event(cpu.cycles, { type: 'reset', cause });
    // The internal reset is stretched by the start-up time; then the reset path (`release`).
    this.releaseAt = cpu.cycles + this.startUpCycles;
    this.bootSession = false;
    this.sleeping = false;
    if (this.brkAddress !== null) {
      // The heap's end once both bytes of __brkval are written, whatever their order.
      const at = this.brkAddress;
      let written = 0;
      for (const [address, bit] of [[at, 1], [at + 1, 2]]) {
        observeWrite(cpu, address, () => {
          written |= bit;
          if (written !== 3) return;
          written = 0;
          const end = cpu.data[at] | (cpu.data[at + 1] << 8);
          if (end && (this.heapEndMax === null || end > this.heapEndMax)) this.heapEndMax = end;
        });
      }
    }
    for (const name of ['OCR1A', 'OCR1B']) this.ocr[name].value = 0;
    this.ocrChanged(cpu.cycles);
    this.frames = [];
    this.ddrSeen = {};
    for (const probe of this.probes.values()) {
      probe.open = [];
      if (probe.epoch && probe.epoch.entries) probe.epochs.push(probe.epoch);
      probe.epoch = { reset: this.resets.length - 1, entries: 0, first: null, last: null,
        periods: stats(), durations: stats(), lateness: stats(), phases: stats() }; // prettier-ignore
    }
    // The motors' enable inputs, from the pins' levels: high when driven high or pulled up.
    const pb = chip.ports.B;
    const enables = (value) => {
      this.enables.right = !!(value & (1 << MOTOR_PINS.right.pwm[1]));
      this.enables.left = !!(value & (1 << MOTOR_PINS.left.pwm[1]));
      this.motorsChanged(cpu.cycles);
    };
    pb.addListener((value) => enables(value));
    enables(pb.lastValue);

    const compare = { OCR1A: [REG.OCR1AL, 'nextOcrA'], OCR1B: [REG.OCR1BL, 'nextOcrB'] };
    for (const [name, [address, field]] of Object.entries(compare)) {
      observeWrite(cpu, address, () => {
        const value = chip.timer1[field];
        const entry = this.ocr[name];
        entry.value = value;
        entry.writes += 1;
        if (value > entry.max) entry.max = value;
        this.trace.event(cpu.cycles, { type: 'ocr', register: name, value });
        this.inputToOutputAt(name, cpu.cycles);
        this.ocrChanged(cpu.cycles);
      });
    }
    const timerRegisters = {
      TCCR0A: REG.TCCR0A, TCCR0B: REG.TCCR0B, TCCR1A: REG.TCCR1A, TCCR1B: REG.TCCR1B,
      TCCR3A: REG.TCCR3A, TCCR3B: REG.TCCR3B, TIMSK0: REG.TIMSK0, TIMSK1: REG.TIMSK1,
      TIMSK3: REG.TIMSK3, OCR0A: REG.OCR0A, OCR0B: REG.OCR0B,
    }; // prettier-ignore
    for (const [name, address] of Object.entries(timerRegisters)) {
      observeWrite(cpu, address, (value) => this.trace.event(cpu.cycles, { type: 'timer', register: name, value }));
    }
    const sixteen = { ICR1: [REG.ICR1L, chip.timer1, 'icr'], ICR3: [REG.ICR3L, chip.timer3, 'icr'],
      OCR3A: [REG.OCR3AL, chip.timer3, 'nextOcrA'] }; // prettier-ignore
    for (const [name, [address, timer, field]] of Object.entries(sixteen)) {
      observeWrite(cpu, address, () => this.trace.event(cpu.cycles, { type: 'timer', register: name, value: timer[field] }));
    }
    observeWrite(cpu, REG.WDTCSR, (value) => {
      if (value & 0x48) this.watchdogUsed = true;
      this.trace.event(cpu.cycles, { type: 'watchdog', register: 'WDTCSR', value: cpu.data[REG.WDTCSR] });
    });
    for (const [letter, port] of Object.entries(chip.ports)) {
      port.addListener((value, previous) => this.pins(letter, port, value, previous));
    }
    chip.usart1.onByteTransmit = (byte) => {
      this.usart.bytes += 1;
      if (this.usart.text.length < MAX_USART_TEXT) this.usart.text += String.fromCharCode(byte);
      this.trace.event(cpu.cycles, { type: 'usart1', byte });
    };
    this.board.attach(chip);
  }

  transfer(transfer) {
    const cycle = this.chip.cpu.cycles;
    if (transfer.arbitration_lost) this.twi.arbitration_lost += 1;
    else if (transfer.kind === 'address') {
      this.twi.addresses += 1;
      if (!transfer.ack) this.twi.nacks += 1;
    } else {
      this.twi.bytes += 1;
    }
    this.trace.event(cycle, { type: 'twi', ...transfer });
    const ready = this.board.lsm6.lastGyroReady;
    if (transfer.kind === 'read' && ready !== null && ready !== this.lastGyroSeen) {
      this.lastGyroSeen = ready;
      this.trace.event(cycle, { type: 'imu_sample', sensor: 'gyro', ready_cycle: Math.round(ready * FREQUENCY_HZ) });
    }
  }

  /** A write of a compare register: its input-to-output figures (INPUT_TO_OUTPUT_DEFINITION). */
  inputToOutputAt(name, cycle) {
    const window = this.reads[name];
    let batch = null;
    if (window.oldest !== Infinity) batch = [window.oldest, window.newest];
    else batch = window.last;
    window.oldest = Infinity;
    window.newest = -Infinity;
    if (!batch) return;
    window.last = batch;
    add(this.inputToOutput.upper, cycle - Math.round(batch[0] * FREQUENCY_HZ));
    add(this.inputToOutput.newest, cycle - Math.round(batch[1] * FREQUENCY_HZ));
  }

  ocrChanged(cycle) {
    const zero = this.ocr.OCR1A.value === 0 && this.ocr.OCR1B.value === 0;
    const last = this.ocrTimeline[this.ocrTimeline.length - 1];
    if (last[1] !== zero) this.ocrTimeline.push([cycle, zero]);
  }

  motorsChanged(cycle) {
    const off = !this.enables.left && !this.enables.right;
    const last = this.offTimeline[this.offTimeline.length - 1];
    if (last[0] === cycle) {
      // Two changes in one cycle: the later one stands.
      last[1] = off;
      if (this.offTimeline.length > 1 && this.offTimeline[this.offTimeline.length - 2][1] === off) this.offTimeline.pop();
    } else if (last[1] !== off) {
      this.offTimeline.push([cycle, off]);
    }
  }

  pins(letter, port, value, previous) {
    const cycle = this.chip.cpu.cycles;
    const ddr = this.chip.cpu.data[port.portConfig.DDR];
    const ddrChanged = ddr ^ (this.ddrSeen[letter] ?? 0);
    if (ddrChanged) {
      this.ddrSeen[letter] = ddr;
      for (let index = 0; index < 8; index += 1) {
        const bit = 1 << index;
        if (ddrChanged & bit) {
          this.trace.event(cycle, { type: 'ddr', pin: `P${letter}${index}`, output: ddr & bit ? 1 : 0 });
        }
      }
    }
    const changed = value ^ previous;
    if (!changed) return;
    for (let index = 0; index < 8; index += 1) {
      const bit = 1 << index;
      if (!(changed & bit)) continue;
      const name = `P${letter}${index}`;
      const level = value & bit ? 1 : 0;
      if (!(port.overrideMask & bit)) {
        this.pwmEdge(name, cycle, level);
      } else if (ddr & bit) {
        this.trace.event(cycle, { type: 'pin', pin: name, value: level });
      }
    }
  }

  pwmEdge(name, cycle, level) {
    let pin = this.pwm[name];
    if (!pin) {
      pin = { rise: null, period: stats(), high: stats(), lastPeriod: null, lastHigh: null, shown: null };
      this.pwm[name] = pin;
    }
    if (level) {
      if (pin.rise !== null) {
        pin.lastPeriod = cycle - pin.rise;
        add(pin.period, pin.lastPeriod);
      }
      pin.rise = cycle;
    } else if (pin.rise !== null) {
      pin.lastHigh = cycle - pin.rise;
      add(pin.high, pin.lastHigh);
      // Shown when the waveform changes by more than an edge's stamp can be off by: a pin is
      // updated when its timer is next served, after the instruction in which it matched.
      const shown = pin.shown;
      const moved = (a, b) => b === null || Math.abs(a - b) > EDGE_RESOLUTION_CYCLES;
      if (pin.lastPeriod !== null && (!shown || moved(pin.lastPeriod, shown[0]) || moved(pin.lastHigh, shown[1]))) {
        pin.shown = [pin.lastPeriod, pin.lastHigh];
        this.trace.event(cycle, { type: 'pwm', pin: name, period_cycles: pin.lastPeriod, high_cycles: pin.lastHigh });
      }
    }
  }

  /** Run the scenario to its end; the summary's measurements. */
  run() {
    this.build(MCUSR_PORF, { cycles: 0, sram: powerOnSram(this.scenario.sram_seed) }, 'power_on');
    const end = Math.round(this.scenario.duration_s * FREQUENCY_HZ);
    const stalls = this.scenario.stalls.map((stall) => ({
      start: Math.round(stall.start_s * FREQUENCY_HZ),
      end: Math.round(stall.end_s * FREQUENCY_HZ),
      interrupts: stall.interrupts,
    }));
    let stallIndex = 0;
    let stall = null;
    let stalledByReset = -1;
    let stallShown = -1;
    while (this.chip.cpu.cycles < end && !this.evidenceEnd) {
      const { cpu } = this.chip;
      const now = cpu.cycles;
      while (stallIndex < stalls.length && stalls[stallIndex].end <= now) stallIndex += 1;
      const upcoming = stalls[stallIndex];
      stall = upcoming && upcoming.start <= now && stallIndex !== stalledByReset ? upcoming : null;
      let limit = Math.min(end, this.board.nextChange(now));
      if (stall) limit = Math.min(limit, stall.end);
      else if (upcoming && upcoming.start > now) limit = Math.min(limit, upcoming.start);
      if (stall && stallShown !== stallIndex) {
        stallShown = stallIndex;
        this.trace.event(now, { type: 'stall', interrupts: stall.interrupts, until: stall.end });
      }
      if (now < this.releaseAt) {
        // Held in reset: nothing runs until the start-up time is over.
        cpu.cycles = Math.min(limit, this.releaseAt);
        if (cpu.cycles === this.releaseAt) this.release();
      } else {
        this.execute(limit, stall);
      }
      if (this.chip.resetRequest && !this.evidenceEnd) {
        const cause = this.chip.resetRequest;
        const period = this.chip.watchdog.period;
        // A reset sets its own flag and leaves the others, which only a written zero clears.
        const mcusr = (cause === 'watchdog' ? MCUSR_WDRF : MCUSR_PORF) | this.chip.cpu.data[REG.MCUSR];
        this.build(mcusr, this.chip.carried(), cause);
        if (cause === 'watchdog') this.resets[this.resets.length - 1].watchdog_period_cycles = period;
        if (stall) stalledByReset = stallIndex;
      }
      this.board.advance();
    }
    this.trace.flush();
    return this.summary(end);
  }

  /** The end of the start-up time: the board's reset path, then the sketch from its vector. */
  release() {
    const { cpu, watchdog } = this.chip;
    const { data } = cpu;
    const entry = this.resets[this.resets.length - 1];
    this.releaseAt = -1;
    if (this.scenario.bootloader === 'a-star' && !this.bootSession) {
      // Caterina.c: the C start-up copies its .data and clears its .bss, then main().
      data.set(BOOT_DATA, 0x100);
      data.fill(0, BOOT_BSS[0], BOOT_BSS[1]);
      const key = data[BOOT_KEY_ADDRESS] | (data[BOOT_KEY_ADDRESS + 1] << 8);
      data[BOOT_KEY_ADDRESS] = 0;
      data[BOOT_KEY_ADDRESS + 1] = 0;
      const flags = data[REG.MCUSR];
      data[REG.MCUSR] = flags & ~(MCUSR_PORF | MCUSR_EXTRF | MCUSR_WDRF);
      data[REG.WDTCSR] = 0; // wdt_disable(), WDRF already clear
      watchdog.schedule();
      if (flags & MCUSR_PORF) {
        data[REG.MCUSR] &= ~MCUSR_BORF;
      } else if (!(flags & MCUSR_EXTRF) && flags & MCUSR_WDRF && key === BOOT_KEY) {
        // The bootloader's own session, until its timeout; then MCUSR = 0 and the sketch.
        data[REG.MCUSR] = 0;
        entry.bootloader_session_cycles = BOOT_SESSION_CYCLES;
        this.noteUnmodelled('bootloader_session');
        this.bootSession = true;
        this.releaseAt = cpu.cycles + BOOT_SESSION_CYCLES;
        return;
      }
    }
    if (this.scenario.bootloader === 'a-star' && this.bootSession) {
      // What the session leaves (Caterina.c SetupHardware(), then USB_Detach() and StartSketch()):
      // OCR1A at 250, the LED pins as outputs, the USB controller and its PLL on, detached.
      const { timer1 } = this.chip;
      timer1.ocrA = 250;
      timer1.nextOcrA = 250;
      data[REG.OCR1AL] = 250;
      data[REG.OCR1AL + 1] = 0;
      this.ocr.OCR1A.value = 250;
      this.ocrChanged(cpu.cycles);
      cpu.writeData(REG.DDRC, data[REG.DDRC] | 0x80);
      cpu.writeData(REG.DDRB, data[REG.DDRB] | 0x01);
      cpu.writeData(REG.DDRD, data[REG.DDRD] | 0x20);
      data[REG.USBCON] = (data[REG.USBCON] | 0x80) & ~0x20;
      data[REG.PLLCSR] = 0x13;
      data[REG.UDCON] |= 0x01;
    }
    if (this.scenario.bootloader === 'a-star') {
      // StartSketch(): Timer1 stopped and cleared (as it is from reset on this path), the vectors
      // back at 0, the LEDs off: L (PC7) low, TX (PD5) and RX (PB0) high.
      data[REG.MCUCR] = 0;
      cpu.writeData(REG.PORTC, data[REG.PORTC] & ~0x80);
      cpu.writeData(REG.PORTD, data[REG.PORTD] | 0x20);
      cpu.writeData(REG.PORTB, data[REG.PORTB] | 0x01);
    } else if (watchdog.running) {
      watchdog.restart(); // WDRF holds it on; its count starts as the delay ends
    }
    data[REG.SREG] &= 0x7f;
    cpu.pc = 0;
    entry.sketch_start_cycle = cpu.cycles;
    entry.mcusr_at_sketch_start = data[REG.MCUSR];
    this.trace.event(cpu.cycles, { type: 'sketch_start', mcusr: data[REG.MCUSR] });
  }

  /** Execute until `limit` cycles, a reset, the stall's end, or the evidence's end. */
  execute(limit, stall) {
    const chip = this.chip;
    const { cpu } = chip;
    const { data } = cpu;
    const { flags } = this;
    let minSp = this.minSp;
    while (cpu.cycles < limit && !chip.resetRequest && !this.evidenceEnd) {
      const pc = cpu.pc;
      // The program counter past the last word of flash: there is nothing the part would run.
      if (pc >= this.program.length || pc < 0) {
        this.unmapped('execute', pc * 2);
        break;
      }
      // The main program is stuck in place. Stuck with interrupts on, it stops at its first
      // instruction with them enabled (not inside a section that holds them off) and an
      // interrupt still runs; stuck with them off, nothing runs.
      if (stall && this.frames.length === 0 && (!stall.interrupts || data[95] & 0x80)) {
        cpu.cycles += 1;
        if (stall.interrupts) {
          cpu.tick();
          if (cpu.pc !== pc) this.entered(pc);
        } else {
          const sreg = data[95];
          data[95] = sreg & 0x7f;
          cpu.tick();
          if (!chip.resetRequest) data[95] = (data[95] & 0x7f) | (sreg & 0x80);
        }
        continue;
      }
      if (this.sleeping) {
        // Idle: the CPU halted, the clocks running, until an interrupt is taken.
        cpu.cycles += 1;
        this.sleep.cycles_asleep += 1;
        cpu.tick();
        if (cpu.pc !== pc && !chip.resetRequest) this.entered(pc);
        continue;
      }
      const flag = flags[pc];
      let sleeps = false;
      if (flag) {
        if (flag & F_PROBE) this.probeEntry(pc, cpu);
        if (flag & F_SLEEP && data[REG.SMCR] & 0x01) sleeps = true;
        if (flag & F_SPM) this.noteUnmodelled('spm_instruction');
        if (flag & F_USB_WRITE) this.usbSerialWrites += 1;
        if (flag & F_LPM && !this.programReadInFlash(cpu, this.program[pc])) break;
        if (flag & (F_RET | F_RETI)) {
          const sp = data[93] | (data[94] << 8);
          avrInstruction(cpu);
          this.returned(flag, sp);
        } else {
          avrInstruction(cpu);
        }
      } else {
        avrInstruction(cpu);
      }
      const sp = data[93] | (data[94] << 8);
      if (sp < minSp) minSp = sp;
      // An interrupt whose return address is no longer on the stack has been left without RETI.
      while (this.frames.length && sp > this.frames[this.frames.length - 1].sp) this.unwind();
      if (sleeps && !this.enterSleep()) break;
      const after = cpu.pc;
      if (flag & (F_SEI | F_RETI)) {
        // The next instruction runs before any pending interrupt is taken.
        const sreg = data[95];
        data[95] = sreg & 0x7f;
        cpu.tick();
        if (!chip.resetRequest) data[95] = (data[95] & 0x7f) | (sreg & 0x80);
      } else {
        cpu.tick();
      }
      if (cpu.pc !== after && !chip.resetRequest) this.entered(after);
    }
    this.minSp = Math.min(this.minSp, minSp);
  }

  /** An access to memory the part does not have ends the run's evidence at its address. */
  unmapped(access, address) {
    this.noteUnmodelled('unmapped_memory');
    this.endEvidence('unmapped_memory', { space: 'program', access, address });
  }

  /** An LPM or ELPM is about to read the byte at Z (and RAMPZ): whether it lies in flash. */
  programReadInFlash(cpu, opcode) {
    const z = cpu.data[30] | (cpu.data[31] << 8);
    const address = isExtendedProgramRead(opcode) ? (cpu.data[REG.RAMPZ] << 16) | z : z;
    if (address < this.program.length * 2) return true;
    this.unmapped('read', address);
    return false;
  }

  /** A SLEEP with SE set has run: idle with interrupts on sleeps; anything else ends the evidence
   * (datasheet "Power Management and Sleep Modes": only idle keeps every clock and wake source
   * the rig models, and whether an interrupt wakes the part with I clear is not documented).
   * Whether the CPU goes on. */
  enterSleep() {
    const { cpu } = this.chip;
    const { data } = cpu;
    const mode = (data[REG.SMCR] >> 1) & 0x07;
    if (mode !== 0 || !(data[REG.SREG] & 0x80)) {
      this.endEvidence('sleep', { mode: SLEEP_MODES[mode], interrupts_enabled: !!(data[REG.SREG] & 0x80) });
      return false;
    }
    this.sleeping = true;
    this.sleep.idle_entries += 1;
    // "If the ADC is enabled, a conversion starts automatically when this mode is entered."
    if (data[REG.ADCSRA] & 0x80 && !(data[REG.ADCSRA] & 0x40)) cpu.writeData(REG.ADCSRA, data[REG.ADCSRA] | 0x40);
    return true;
  }

  unwind() {
    const frame = this.frames.pop();
    const name = vectorName(frame.vector);
    this.unwound[name] = (this.unwound[name] ?? 0) + 1;
  }

  /** An interrupt was accepted: the CPU now stands at its vector. */
  entered() {
    const { cpu } = this.chip;
    // avr8js counts two cycles of the response; the part takes four.
    const start = cpu.cycles - 2;
    cpu.cycles += 2;
    if (this.sleeping) {
      this.sleeping = false;
      this.sleep.wakes += 1;
      cpu.cycles += SLEEP_WAKE_CYCLES;
    }
    const vector = cpu.pc;
    if (vector === VECTORS.WDT) this.chip.watchdog.vectored();
    const sp = cpu.data[93] | (cpu.data[94] << 8);
    if (sp < this.minSp) this.minSp = sp;
    this.frames.push({ vector, start, sp, nested: 0 });
  }

  returned(flag, spBefore) {
    const { cpu } = this.chip;
    if (flag & F_RETI && this.frames.length) {
      const frame = this.frames.pop();
      const name = vectorName(frame.vector);
      let s = this.vectors.get(name);
      if (!s) {
        s = { inclusive: stats(), exclusive: stats() };
        this.vectors.set(name, s);
      }
      const inclusive = cpu.cycles - frame.start;
      add(s.inclusive, inclusive);
      add(s.exclusive, inclusive - frame.nested);
      if (this.frames.length) this.frames[this.frames.length - 1].nested += inclusive;
    }
    if (!this.probes.size) return;
    for (const probe of this.probes.values()) {
      const open = probe.open[probe.open.length - 1];
      if (open && open.sp === spBefore) {
        probe.open.pop();
        const duration = cpu.cycles - open.entry;
        add(probe.epoch.durations, duration);
        this.trace.event(open.entry, { type: 'probe', symbol: probe.symbol, cycles: duration });
      }
    }
  }

  probeEntry(pc, cpu) {
    const probe = this.probes.get(pc);
    const entry = cpu.cycles;
    const sp = cpu.data[93] | (cpu.data[94] << 8);
    probe.open.push({ entry, sp });
    const epoch = probe.epoch;
    if (epoch.last !== null) add(epoch.periods, entry - epoch.last);
    if (epoch.first === null) epoch.first = entry;
    if (probe.period) {
      // The n-th entry's phase on the period's grid (LATENESS): an entry missed makes the later
      // ones late.
      add(epoch.phases, entry - epoch.entries * probe.period);
      add(epoch.lateness, entry - (epoch.first + epoch.entries * probe.period));
    }
    epoch.entries += 1;
    epoch.last = entry;
  }

  summary(end) {
    const { cpu, timer1 } = this.chip;
    // What the unmodelled uses make not evaluable: the times, the values read, or (a use with no
    // effect on a board that runs from its crystal) neither (FEATURE_EFFECTS).
    const { untimed, unvalued } = this.unevaluable();
    const timed = untimed.length === 0;
    // With timing not evaluable, every figure of time is withheld (`withheld` names them).
    const untimedWhy = `timing not evaluable: ${untimed.join(', ')}`;
    const timing = (value) => (timed ? value : withheld(untimedWhy));
    // The evidence's end: nothing after it is the board's behaviour.
    const last = this.evidenceEnd ? this.evidenceEnd.cycle : end;
    const vectors = {};
    for (const name of [...this.vectors.keys()].sort()) {
      const v = this.vectors.get(name);
      vectors[name] = { count: v.inclusive.count, inclusive_cycles: timing(report(v.inclusive)),
        exclusive_cycles: timing(report(v.exclusive)) }; // prettier-ignore
    }
    const pwm = {};
    for (const name of Object.keys(this.pwm).sort()) {
      const pin = this.pwm[name];
      pwm[name] = timing({
        period_cycles: report(pin.period),
        high_cycles: report(pin.high),
        last_period_cycles: pin.lastPeriod,
        last_high_cycles: pin.lastHigh,
        frequency_hz: pin.period.count ? FREQUENCY_HZ / (pin.period.total / pin.period.count) : null,
      });
    }
    const probes = {};
    for (const probe of this.probes.values()) {
      const epochs = [...probe.epochs, ...(probe.epoch && probe.epoch.entries ? [probe.epoch] : [])];
      const all = { periods: stats(), durations: stats(), lateness: stats(), late: stats() };
      for (const epoch of epochs) {
        for (const key of ['periods', 'durations', 'lateness']) merge(all[key], epoch[key]);
        if (epoch.phases.count) merge(all.late, againstEarliest(epoch.phases));
      }
      const lateness = (epoch) =>
        probe.period ? timing(epoch.phases.count ? report(againstEarliest(epoch.phases)) : { count: 0 }) : null;
      const shown = (epoch) => ({
        reset_index: epoch.reset,
        entries: epoch.entries,
        first_entry_cycle: timing(epoch.first),
        period_cycles: timing(report(epoch.periods)),
        duration_cycles: timing(report(epoch.durations)),
        lateness_cycles: lateness(epoch),
        lateness_from_first_entry_cycles: probe.period ? timing(report(epoch.lateness)) : null,
      });
      probes[probe.symbol] = {
        entries: epochs.reduce((n, epoch) => n + epoch.entries, 0),
        first_entry_cycle: timing(epochs.length ? epochs[0].first : null),
        period_cycles: timing(report(all.periods)),
        duration_cycles: timing(report(all.durations)),
        lateness_cycles: probe.period ? timing(report(all.late)) : null,
        lateness_from_first_entry_cycles: probe.period ? timing(report(all.lateness)) : null,
        lateness_definition: probe.period ? LATENESS : null,
        nominal_period_cycles: probe.period,
        by_reset: epochs.map(shown),
      };
    }
    const events = [];
    const push = (kind, cycle, extra = {}) => {
      let figures;
      if (cycle > last) {
        const after = withheld(`after the evidence ends at cycle ${last}`);
        figures = { motors_off_cycle: after, motors_off_delay_s: after, motors_off_until_cycle: after,
          stayed_off_to_end: after, ocr_zero_cycle: after }; // prettier-ignore
      } else {
        figures = { ...this.motorsOffAfter(cycle, last), ocr_zero_cycle: this.ocrZeroAfter(cycle) };
        if (!timed) for (const key of Object.keys(figures)) figures[key] = withheld(untimedWhy);
      }
      events.push({ kind, cycle, ...extra, ...figures });
    };
    this.scenario.faults.forEach((fault, i) =>
      push(`fault:${fault.kind}`, Math.round(fault.start_s * FREQUENCY_HZ), { index: i }),
    );
    this.scenario.stalls.forEach((stall, i) =>
      push('stall', Math.round(stall.start_s * FREQUENCY_HZ), { index: i, interrupts: stall.interrupts }),
    );
    this.scenario.markers.forEach((marker) => push(`marker:${marker.name}`, Math.round(marker.t_s * FREQUENCY_HZ)));
    events.sort((a, b) => a.cycle - b.cycle);
    const motor = (side) => {
      const pins = MOTOR_PINS[side];
      const entry = this.ocr[pins.compare];
      return { compare: pins.compare, pwm_pin: pins.pwmName, direction_pin: pins.directionName,
        writes: entry.writes, max: entry.max, last: entry.value }; // prettier-ignore
    };
    const unmodelled = {};
    for (const what of Object.keys(this.unmodelled).sort()) unmodelled[what] = this.unmodelled[what];
    const heapEnd = Math.max(this.heapStart ?? 0, this.heapEndMax ?? 0);
    const headroom = this.heapStart === null && this.heapEndMax === null ? null : this.minSp - heapEnd;
    const ioUpper = report(this.inputToOutput.upper);
    const ioNewest = report(this.inputToOutput.newest);
    return {
      board: { model: BOARD, version: BOARD_VERSION },
      frequency_hz: FREQUENCY_HZ,
      simulated_cycles: cpu.cycles,
      simulated_s: toSeconds(cpu.cycles),
      scenario_end_cycle: end,
      evidence_end: this.evidenceEnd,
      not_shown: NOT_SHOWN,
      typical_figures: {
        watchdog_oscillator_hz: this.scenario.watchdog_oscillator_hz,
        scenario_range_hz: [WATCHDOG_OSCILLATOR_HZ.min, WATCHDOG_OSCILLATOR_HZ.max],
        start_up_cycles: this.startUpCycles,
        statement:
          'the watchdog period (2K << WDP oscillator cycles, Table 8-5) and the start-up time-out (typically 65 ms ' +
          'at 5 V, Table 6-2) are typical figures: the datasheet gives no bound; its typical curves at 5 V ' +
          '(Figure 30-34) lie between about 112.5 and 121.5 kHz, below the nominal 128 kHz; a scenario runs any ' +
          'oscillator in scenario_range_hz',
      },
      reset_path: {
        bootloader: this.scenario.bootloader,
        start_up_cycles: this.startUpCycles,
        pll_lock_cycles: PLL_LOCK_CYCLES,
        readings: RESET_PATH[this.scenario.bootloader],
      },
      resets: this.resets.map((reset) => ({
        ...reset,
        at_oscillator_hz: this.scenario.watchdog_oscillator_hz,
        cycle: timing(reset.cycle),
        sketch_start_cycle: timing(reset.sketch_start_cycle),
        ...('bootloader_session_cycles' in reset
          ? { bootloader_session_cycles: timing(reset.bootloader_session_cycles) }
          : {}),
        ...('watchdog_period_cycles' in reset
          ? { watchdog_period_cycles: timing(reset.watchdog_period_cycles) }
          : {}),
      })),
      watchdog: this.watchdogEnds(),
      interrupt_response_cycles: 4,
      sleep: {
        ...this.sleep,
        cycles_asleep: timing(this.sleep.cycles_asleep),
        wake_extra_cycles: SLEEP_WAKE_CYCLES,
      },
      vectors,
      vectors_left_without_reti: this.unwound,
      stack: {
        min_sp: this.minSp,
        ramend: RAMEND,
        max_depth_bytes: RAMEND - this.minSp,
        heap_start: this.heapStart,
        static_end: this.heapStart,
        heap_end_max: this.heapEndMax,
        headroom_bytes: headroom,
        collision: headroom === null ? null : headroom < 0,
        definition:
          'headroom_bytes = min_sp - max(static_end, heap_end_max): from the least stack pointer to the highest ' +
          "the heap's end (avr-libc __brkval) reached, or to static data's end; negative is a collision. It covers " +
          'the paths this run executed only.',
      },
      power_on_sram_seed: this.scenario.sram_seed,
      motors: { left: motor('left'), right: motor('right') },
      motors_off_rule: {
        enable_pins: [MOTOR_PINS.right.pwmName, MOTOR_PINS.left.pwmName],
        hold_cycles: this.hold,
        definition:
          'off while both DRV8838 EN inputs are low (an output driven low, or an input without its pull-up) for ' +
          'hold_cycles without a break; an interval cut short by the end of the run or of its evidence is not ' +
          'counted; stayed_off_to_end: off from motors_off_cycle to that end. Off is the DRV8838 brake.',
      },
      timer1: { icr1: timer1.icr, wgm: timer1.WGM, tccr1a: cpu.data[REG.TCCR1A], tccr1b: cpu.data[REG.TCCR1B] },
      pwm,
      probes,
      events,
      imu: {
        registers_written: this.imuWrites,
        whoami_reads: this.board.lsm6.counts.whoami_reads,
        gyro_samples_read: this.board.lsm6.counts.gyro_samples_read,
        accel_samples_read: this.board.lsm6.counts.accel_samples_read,
        invalid_samples_read: this.board.lsm6.counts.invalid_samples_read,
        read_before_any_sample: this.board.lsm6.counts.read_before_any_sample,
        invalid_sample_value: INVALID_SAMPLE_VALUE,
        gyro_zero_rate_dps: this.scenario.imu.gyro_zero_rate_dps,
        gyro_zero_rate_statement: ZERO_LEVEL_STATEMENT.gyro,
        accel_zero_g_mg: this.scenario.imu.accel_zero_g_mg,
        accel_zero_g_statement: ZERO_LEVEL_STATEMENT.accel,
      },
      eeprom: this.eepromSummary(),
      usb: {
        host: 'none',
        usb_sof: this.scenario.usb_sof,
        serial_write_calls: this.usbSerialWrites,
        statement:
          'no USB host is present: the controller is detached and silent (usb_sof adds only the 1 kHz ' +
          'start-of-frame load of a host that has enumerated); a blocking write to a connected ' +
          "Serial, the USB interrupts' load and the CDC session are not shown, and the calls of " +
          'Serial.write and USB_Send (which a HID or any other USB class sends through) are counted here',
      },
      input_to_output: {
        definition: INPUT_TO_OUTPUT_DEFINITION,
        upper_bound_cycles: timing(ioUpper),
        newest_sample_cycles: timing(ioNewest),
      },
      twi: { ...this.twi, durations: 'each step at f_SCL exactly: a lower bound (a device may hold SCL low)' },
      encoders: { edges: this.board.encoderEdges(), counts: this.board.encoderCounts() },
      usart1: { bytes: this.usart.bytes, text: this.usart.text, text_truncated: this.usart.bytes > this.usart.text.length },
      unmodelled,
      timing_evaluable: timed,
      timing_not_evaluable_because: untimed,
      behaviour_evaluable: unvalued.length === 0,
      behaviour_not_evaluable_because: unvalued,
      withheld: timed
        ? []
        : ['vectors.*.inclusive_cycles', 'vectors.*.exclusive_cycles', 'pwm.*', 'probes.*.period_cycles',
            'probes.*.duration_cycles', 'probes.*.lateness_cycles', 'probes.*.lateness_from_first_entry_cycles',
            'input_to_output.upper_bound_cycles', 'input_to_output.newest_sample_cycles',
            'events.*.motors_off_*', 'events.*.stayed_off_to_end', 'events.*.ocr_zero_cycle',
            'resets.*.cycle', 'resets.*.sketch_start_cycle', 'resets.*.bootloader_session_cycles',
            'resets.*.watchdog_period_cycles', 'probes.*.first_entry_cycle',
            'probes.*.by_reset.*.first_entry_cycle', 'sleep.cycles_asleep'], // prettier-ignore
      trace: { lines: this.trace.lines, truncated_at_cycle: this.trace.truncatedAt },
    };
  }

  /** The EEPROM's programming operations, with the datasheet's endurance. */
  eepromSummary() {
    const { writes, per_address_max: perAddressMax } = this.eeprom.counts();
    const over = [];
    this.eeprom.cells.forEach((count, address) => {
      if (count > EEPROM_ENDURANCE_CYCLES) over.push(address);
    });
    return {
      write_cycles: writes,
      per_address_max: perAddressMax,
      endurance_cycles: EEPROM_ENDURANCE_CYCLES,
      cells_over_endurance: over,
      statement:
        'each erase, write or atomic erase-and-write of a cell is one programming operation on it; the datasheet ' +
        'gives the EEPROM an endurance of at least 100,000 write/erase cycles: a cell in cells_over_endurance ' +
        'was programmed more often in this run alone',
    };
  }

  /** The features reported so far that make time not evaluable and those that make values not. */
  unevaluable() {
    const named = Object.keys(this.unmodelled).sort();
    return {
      untimed: named.filter((what) => effectsOf(what).includes('timing')),
      unvalued: named.filter((what) => effectsOf(what).includes('behaviour')),
    };
  }

  /**
   * The watchdog's figures at both ends of its oscillator (`watchdog_oscillator_hz`'s range): the
   * datasheet gives the oscillator no bound, so a figure of "does not reset early" must read the
   * fast end and one of "resets within" the slow end. When the firmware used the watchdog (or a
   * watchdog reset came) each end is a run of its own; otherwise only what the oscillator changes
   * without it, the start-up time, differs. Each end carries what its own run ended or reported
   * (`evidence_end`, `timing_evaluable`, `behaviour_evaluable`): a figure of time of an end
   * that cannot stand behind time is withheld, and a first reset that never came because the
   * evidence ended first is not shown as a watchdog that was fed in time.
   */
  watchdogEnds() {
    if (this.nested) return null;
    const used = this.watchdogUsed || this.resets.some((reset) => reset.cause === 'watchdog');
    const own = this.scenario.watchdog_oscillator_hz;
    const end = (hz) => {
      const run =
        !used || hz === own
          ? this
          : new Rig(this.elf, { ...this.scenario, watchdog_oscillator_hz: hz }, new Trace(() => {}, 0), {
              nested: true,
            });
      if (run !== this) run.run();
      const { untimed, unvalued } = run.unevaluable();
      const figures = {
        oscillator_hz: hz,
        start_up_cycles: startUpCycles(hz),
        evidence_end: run.evidenceEnd,
        timing_evaluable: untimed.length === 0,
        timing_not_evaluable_because: untimed,
        behaviour_evaluable: unvalued.length === 0,
        behaviour_not_evaluable_because: unvalued,
      };
      if (!used) return figures;
      const timing = (value) =>
        untimed.length === 0 ? value : withheld(`timing not evaluable: ${untimed.join(', ')}`);
      const first = run.resets.find((reset) => reset.cause === 'watchdog');
      const unreached = run.evidenceEnd
        ? withheld(`the evidence ended at cycle ${run.evidenceEnd.cycle} before a watchdog reset`)
        : null;
      const resets = run.resets.map(({ cycle, cause, sketch_start_cycle: start }) => ({
        cycle: timing(cycle),
        cause,
        sketch_start_cycle: timing(start),
      }));
      return {
        ...figures,
        period_cycles: timing(first ? first.watchdog_period_cycles : unreached),
        first_watchdog_reset_cycle: timing(first ? first.cycle : unreached),
        watchdog_resets: run.resets.filter((reset) => reset.cause === 'watchdog').length,
        resets,
      };
    };
    return {
      used,
      statement:
        "the watchdog's oscillator is a typical figure with no bound in the datasheet (128 kHz nominal; the " +
        'typical curves at 5 V lie between about 112.5 and 121.5 kHz): each figure is given at both ends of ' +
        'scenario_range_hz. Read the fast end for a criterion that the watchdog does not reset early and ' +
        'the slow end for one that it resets within a time; the run\'s own figures (resets, probes, vectors) ' +
        "are the scenario's oscillator's, which each reset's at_oscillator_hz and `own` say, and each end " +
        'says whether its own run ended its evidence or left time or values not evaluable',
      own: {
        oscillator_hz: own,
        end:
          own >= WATCHDOG_OSCILLATOR_HZ.max ? 'fast' : own <= WATCHDOG_OSCILLATOR_HZ.min ? 'slow' : 'between',
      },
      ends: { fast: end(WATCHDOG_OSCILLATOR_HZ.max), slow: end(WATCHDOG_OSCILLATOR_HZ.min) },
      read: { does_not_reset_early: 'fast', resets_within: 'slow' },
    };
  }

  /** The first cycle at or after `cycle` from which both motor enables stay low for the hold, the
   * cycle they next rise (null: not before `end`, the run's or its evidence's), and whether they
   * stayed off to `end`. */
  motorsOffAfter(cycle, end) {
    const timeline = this.offTimeline;
    for (let i = 0; i < timeline.length; i += 1) {
      const [from, off] = timeline[i];
      const until = i + 1 < timeline.length ? timeline[i + 1][0] : null;
      if (!off || (until !== null && until <= cycle)) continue;
      const start = Math.max(from, cycle);
      if ((until ?? end) - start < this.hold) continue;
      return { motors_off_cycle: start, motors_off_delay_s: toSeconds(start - cycle), motors_off_until_cycle: until,
        stayed_off_to_end: until === null }; // prettier-ignore
    }
    return { motors_off_cycle: null, motors_off_delay_s: null, motors_off_until_cycle: null, stayed_off_to_end: false };
  }

  /** The first cycle at or after `cycle` at which the last writes to OCR1A and OCR1B are both 0. */
  ocrZeroAfter(cycle) {
    const timeline = this.ocrTimeline;
    let i = 0;
    while (i + 1 < timeline.length && timeline[i + 1][0] <= cycle) i += 1;
    if (timeline[i][1]) return cycle;
    for (let j = i + 1; j < timeline.length; j += 1) if (timeline[j][1]) return timeline[j][0];
    return null;
  }
}

export { VECTOR_TABLE_WORDS };
