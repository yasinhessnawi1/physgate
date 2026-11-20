// One run: the firmware on the chip on the board, driven by the scenario, measured.
//
// Measurements are taken from the CPU as it runs, never from the firmware's own reports:
//
// - an interrupt's execution time is the cycles from the CPU's acceptance of it (the cycle count
//   before the vector is entered, the interrupt response included) to the end of its RETI;
//   nested interrupts are counted in the one they interrupted as well as in their own;
// - the stack's high-water mark is the least stack pointer after any instruction;
// - a probe is a function symbol of the ELF: an entry is the CPU arriving at its address, its
//   return the RET (or RETI) executed at the stack depth it was entered at;
// - a PWM output's period and high time are taken between the pin's own edges while a timer's
//   compare unit drives it;
// - the motors are off while the firmware's last writes to both OCR1A and OCR1B are 0 (as they
//   are from reset): that the PWM pins then stay low is the timer's, shown by the PWM edges.

import { avrInstruction } from 'avr8js';

import { BOARD, BOARD_VERSION, Balboa32U4, MOTOR_PINS } from './board.js';
import { lsm6Name } from './imu.js';
import {
  ATmega32U4,
  EEPROM_BYTES,
  EEPROMMemoryBackend,
  FREQUENCY_HZ,
  MCUSR_PORF,
  MCUSR_WDRF,
  RAMEND,
  REG,
  VECTORS,
  VECTOR_TABLE_WORDS,
  observeWrite,
  vectorName,
} from './mcu.js';

const F_RET = 1;
const F_RETI = 2;
const F_PROBE = 4;
const F_SLEEP = 8;
const F_SPM = 16;
const OP_RET = 0x9508;
const OP_RETI = 0x9518;
const OP_SLEEP = 0x9588;
const OP_SPM = 0x95e8;
const OP_SPM_Z = 0x95f8;
const MAX_USART_TEXT = 64 << 10;
/** How late a timer-driven edge can be stamped: the longest instruction, four cycles. */
export const EDGE_RESOLUTION_CYCLES = 4;

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
   */
  constructor(elf, scenario, trace) {
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
        first: null,
        last: null,
        periods: stats(),
        durations: stats(),
        lateness: stats(),
      });
    }
    const heap = elf.symbols.get('__heap_start') ?? elf.symbols.get('_end');
    this.heapStart = heap ? heap.value & 0xffff : null;
    this.eeprom = new EEPROMMemoryBackend(EEPROM_BYTES);
    if (elf.eeprom) this.eeprom.memory.set(elf.eeprom);

    this.vectors = new Map();
    this.frames = [];
    this.minSp = RAMEND;
    this.resets = [];
    this.unmodelled = {};
    this.ocr = { OCR1A: { value: 0, writes: 0, max: 0 }, OCR1B: { value: 0, writes: 0, max: 0 } };
    this.offTimeline = [[0, true]];
    this.pwm = {};
    this.usart = { bytes: 0, text: '' };
    this.imuWrites = {};
    this.gyroReady = null;
    this.lastGyroSeen = null;
    this.ddrSeen = {};
    this.inputToOutput = stats();
    this.twi = { addresses: 0, nacks: 0, bytes: 0 };
    this.board = new Balboa32U4(scenario, {
      onImuWrite: (register, value) => {
        const name = lsm6Name(register);
        this.imuWrites[name] = value;
        this.trace.event(this.chip.cpu.cycles, { type: 'imu_write', register: name, value });
      },
      onInput: (what, t, value) => {
        if (scenario.trace.input_edges) this.trace.event(this.chip.cpu.cycles, { type: 'input', what, value });
      },
    });
    this.chip = null;
  }

  build(mcusr, carried, cause) {
    const chip = new ATmega32U4(this.program, {
      ...carried,
      mcusr,
      eeprom: this.eeprom,
      sof: this.scenario.usb_sof,
      bus: this.board.bus,
      onTransfer: (transfer) => this.transfer(transfer),
      onUnmodelled: (what) => {
        if (!(what in this.unmodelled)) {
          this.unmodelled[what] = chip.cpu.cycles;
          this.trace.event(chip.cpu.cycles, { type: 'unmodelled', what });
        }
      },
    });
    this.chip = chip;
    const { cpu } = chip;
    this.resets.push({ cycle: cpu.cycles, cause });
    this.trace.event(cpu.cycles, { type: 'reset', cause });
    for (const name of ['OCR1A', 'OCR1B']) this.ocr[name].value = 0;
    this.motorsChanged(cpu.cycles);
    this.frames = [];
    this.ddrSeen = {};
    for (const probe of this.probes.values()) probe.open = [];

    const compare = { OCR1A: [REG.OCR1AL, 'nextOcrA'], OCR1B: [REG.OCR1BL, 'nextOcrB'] };
    for (const [name, [address, field]] of Object.entries(compare)) {
      observeWrite(cpu, address, () => {
        const value = chip.timer1[field];
        const entry = this.ocr[name];
        entry.value = value;
        entry.writes += 1;
        if (value > entry.max) entry.max = value;
        this.trace.event(cpu.cycles, { type: 'ocr', register: name, value });
        if (this.gyroReady !== null) {
          add(this.inputToOutput, cpu.cycles - Math.round(this.gyroReady * FREQUENCY_HZ));
          this.gyroReady = null;
        }
        this.motorsChanged(cpu.cycles);
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
    observeWrite(cpu, REG.WDTCSR, () => this.trace.event(cpu.cycles, { type: 'watchdog', register: 'WDTCSR', value: cpu.data[REG.WDTCSR] }));
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
    if (transfer.kind === 'address') {
      this.twi.addresses += 1;
      if (!transfer.ack) this.twi.nacks += 1;
    } else {
      this.twi.bytes += 1;
    }
    this.trace.event(cycle, { type: 'twi', ...transfer });
    const ready = this.board.lsm6.lastGyroReady;
    if (transfer.kind === 'read' && ready !== null && ready !== this.lastGyroSeen) {
      this.lastGyroSeen = this.board.lsm6.lastGyroReady;
      this.gyroReady = this.lastGyroSeen;
      this.trace.event(cycle, { type: 'imu_sample', sensor: 'gyro', ready_cycle: Math.round(this.gyroReady * FREQUENCY_HZ) });
    }
  }

  motorsChanged(cycle) {
    const off = this.ocr.OCR1A.value === 0 && this.ocr.OCR1B.value === 0;
    const last = this.offTimeline[this.offTimeline.length - 1];
    if (last[1] !== off) this.offTimeline.push([cycle, off]);
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
    this.build(MCUSR_PORF, { cycles: 0 }, 'power_on');
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
    while (this.chip.cpu.cycles < end) {
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
      this.execute(limit, stall);
      if (this.chip.resetRequest) {
        const cause = this.chip.resetRequest;
        const mcusr = (cause === 'watchdog' ? MCUSR_WDRF : MCUSR_PORF) | (this.chip.cpu.data[REG.MCUSR] & ~0x08);
        this.build(mcusr, this.chip.carried(), cause);
        if (stall) stalledByReset = stallIndex;
      }
      this.board.advance();
    }
    this.trace.flush();
    return this.summary(end);
  }

  /** Execute until `limit` cycles, a reset, or the stall's end. */
  execute(limit, stall) {
    const chip = this.chip;
    const { cpu } = chip;
    const { data } = cpu;
    const { flags } = this;
    let minSp = this.minSp;
    while (cpu.cycles < limit && !chip.resetRequest) {
      const pc = cpu.pc;
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
      const flag = flags[pc];
      if (flag) {
        if (flag & F_PROBE) this.probeEntry(pc, cpu);
        if (flag & (F_SLEEP | F_SPM)) this.unmodelledInstruction(flag);
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
      const after = cpu.pc;
      cpu.tick();
      if (cpu.pc !== after && !chip.resetRequest) this.entered(after);
    }
    this.minSp = minSp;
  }

  unmodelledInstruction(flag) {
    const what = flag & F_SLEEP ? 'sleep_instruction' : 'spm_instruction';
    if (!(what in this.unmodelled)) {
      this.unmodelled[what] = this.chip.cpu.cycles;
      this.trace.event(this.chip.cpu.cycles, { type: 'unmodelled', what });
    }
  }

  /** An interrupt was accepted: the CPU now stands at its vector. */
  entered() {
    const { cpu } = this.chip;
    // avr8js counts two cycles of the response; the part takes four.
    const start = cpu.cycles - 2;
    cpu.cycles += 2;
    const vector = cpu.pc;
    if (vector === VECTORS.WDT) this.chip.watchdog.vectored();
    const sp = cpu.data[93] | (cpu.data[94] << 8);
    if (sp < this.minSp) this.minSp = sp;
    this.frames.push({ vector, start, sp });
  }

  returned(flag, spBefore) {
    const { cpu } = this.chip;
    if (flag & F_RETI && this.frames.length) {
      const frame = this.frames.pop();
      const name = vectorName(frame.vector);
      let s = this.vectors.get(name);
      if (!s) {
        s = stats();
        this.vectors.set(name, s);
      }
      add(s, cpu.cycles - frame.start);
    }
    if (!this.probes.size) return;
    for (const probe of this.probes.values()) {
      const open = probe.open[probe.open.length - 1];
      if (open && open.sp === spBefore) {
        probe.open.pop();
        const duration = cpu.cycles - open.entry;
        add(probe.durations, duration);
        this.trace.event(open.entry, { type: 'probe', symbol: probe.symbol, cycles: duration });
      }
    }
  }

  probeEntry(pc, cpu) {
    const probe = this.probes.get(pc);
    const entry = cpu.cycles;
    const sp = cpu.data[93] | (cpu.data[94] << 8);
    probe.open.push({ entry, sp });
    if (probe.last !== null) add(probe.periods, entry - probe.last);
    if (probe.first === null) probe.first = entry;
    if (probe.period) {
      // The n-th entry is due n periods after the first: an entry missed makes the later ones late.
      add(probe.lateness, entry - (probe.first + probe.periods.count * probe.period));
    }
    probe.last = entry;
  }

  summary(end) {
    const vectors = {};
    for (const name of [...this.vectors.keys()].sort()) vectors[name] = report(this.vectors.get(name));
    const pwm = {};
    for (const name of Object.keys(this.pwm).sort()) {
      const pin = this.pwm[name];
      pwm[name] = {
        period_cycles: report(pin.period),
        high_cycles: report(pin.high),
        last_period_cycles: pin.lastPeriod,
        last_high_cycles: pin.lastHigh,
        frequency_hz: pin.period.count ? FREQUENCY_HZ / (pin.period.total / pin.period.count) : null,
      };
    }
    const probes = {};
    for (const probe of this.probes.values()) {
      probes[probe.symbol] = {
        entries: probe.periods.count + (probe.first === null ? 0 : 1),
        first_entry_cycle: probe.first,
        period_cycles: report(probe.periods),
        duration_cycles: report(probe.durations),
        lateness_cycles: probe.period ? report(probe.lateness) : null,
        nominal_period_cycles: probe.period,
      };
    }
    const events = [];
    const push = (kind, cycle, extra = {}) => events.push({ kind, cycle, ...extra, ...this.motorsOffAfter(cycle) });
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
    const { cpu, timer1 } = this.chip;
    return {
      board: { model: BOARD, version: BOARD_VERSION },
      frequency_hz: FREQUENCY_HZ,
      simulated_cycles: cpu.cycles,
      simulated_s: toSeconds(cpu.cycles),
      scenario_end_cycle: end,
      resets: this.resets,
      vectors,
      stack: {
        min_sp: this.minSp,
        ramend: RAMEND,
        max_depth_bytes: RAMEND - this.minSp,
        heap_start: this.heapStart,
        headroom_bytes: this.heapStart === null ? null : this.minSp - this.heapStart,
      },
      motors: { left: motor('left'), right: motor('right') },
      timer1: { icr1: timer1.icr, wgm: timer1.WGM, tccr1a: cpu.data[REG.TCCR1A], tccr1b: cpu.data[REG.TCCR1B] },
      pwm,
      probes,
      events,
      imu: {
        registers_written: this.imuWrites,
        whoami_reads: this.board.lsm6.counts.whoami_reads,
        gyro_samples_read: this.board.lsm6.counts.gyro_samples_read,
        accel_samples_read: this.board.lsm6.counts.accel_samples_read,
      },
      input_to_output_cycles: report(this.inputToOutput),
      twi: this.twi,
      encoders: { edges: this.board.encoderEdges(), counts: this.board.encoderCounts() },
      usart1: { bytes: this.usart.bytes, text: this.usart.text, text_truncated: this.usart.bytes > this.usart.text.length },
      unmodelled: this.unmodelled,
      trace: { lines: this.trace.lines, truncated_at_cycle: this.trace.truncatedAt },
    };
  }

  /** The first cycle at or after `cycle` at which the motors are off, and how long they stay so. */
  motorsOffAfter(cycle) {
    const timeline = this.offTimeline;
    let i = 0;
    while (i + 1 < timeline.length && timeline[i + 1][0] <= cycle) i += 1;
    let off = null;
    if (timeline[i][1]) off = cycle;
    else if (i + 1 < timeline.length) off = timeline[i + 1][0];
    if (off === null) return { motors_off_cycle: null, motors_off_delay_s: null, motors_off_until_cycle: null };
    let j = i;
    while (j + 1 < timeline.length && timeline[j + 1][0] <= off) j += 1;
    const until = j + 1 < timeline.length ? timeline[j + 1][0] : null;
    return { motors_off_cycle: off, motors_off_delay_s: toSeconds(off - cycle), motors_off_until_cycle: until };
  }
}

export { VECTOR_TABLE_WORDS };
