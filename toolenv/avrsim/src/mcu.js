// The ATmega32U4, built from avr8js's parts.
//
// avr8js models the ATmega328P's peripherals; the 32U4 shares most of their register layouts at
// the same addresses but not its interrupt vectors, its pin assignments, its USB controller or
// its second set of external interrupts. Every address and vector number below is therefore the
// rig's own claim, taken from the toolchain's device header (avr-libc's <avr/iom32u4.h>, which
// the provisioned avr-gcc builds against) and the ATmega32U4 datasheet (Atmel-7766, "ATmega16U4/
// ATmega32U4"), and a wrong one is a wrong result. A vector's word address is twice its number in
// the header's `_VECTOR(n)`, since each entry of the 32U4's table is a two-word JMP.
//
// What the chip does here and what it does not is listed in `LIMITS` at the end, so the summary
// of a run can say which unmodelled parts the firmware touched.

import {
  AVREEPROM,
  AVRIOPort,
  AVRTimer,
  AVRTWI,
  AVRUSART,
  AVRADC,
  ADCMuxInputType,
  ADCReference,
  CPU,
  EEPROMMemoryBackend,
  PinState,
} from 'avr8js';

import { REG, REGISTER_OUTCOMES } from './registers.js';

export { FEATURE_EFFECTS, REG, REGISTER_OUTCOMES, UNMODELLED_FEATURES, effectsOf } from './registers.js';

export const FREQUENCY_HZ = 16_000_000; // the Balboa's crystal (board a-star32U4: f_cpu 16000000L)
export const FLASH_BYTES = 0x8000; // FLASHEND 0x7FFF
export const SRAM_BYTES = 0xa00; // RAMSIZE; RAMSTART 0x100
export const RAMEND = 0x100 + SRAM_BYTES - 1; // 0x0AFF
export const EEPROM_BYTES = 0x400; // E2END 0x3FF
/** The vector table's end in words: 43 vectors of two words (_VECTORS_SIZE 43 * 4 bytes). */
export const VECTOR_TABLE_WORDS = 43 * 2;

/** Each vector by the header's name, as the word address the CPU jumps to. */
export const VECTORS = Object.freeze({
  RESET: 0x00,
  INT0: 0x02,
  INT1: 0x04,
  INT2: 0x06,
  INT3: 0x08,
  INT6: 0x0e,
  PCINT0: 0x12,
  USB_GEN: 0x14,
  USB_COM: 0x16,
  WDT: 0x18,
  TIMER1_CAPT: 0x20,
  TIMER1_COMPA: 0x22,
  TIMER1_COMPB: 0x24,
  TIMER1_COMPC: 0x26,
  TIMER1_OVF: 0x28,
  TIMER0_COMPA: 0x2a,
  TIMER0_COMPB: 0x2c,
  TIMER0_OVF: 0x2e,
  SPI_STC: 0x30,
  USART1_RX: 0x32,
  USART1_UDRE: 0x34,
  USART1_TX: 0x36,
  ANALOG_COMP: 0x38,
  ADC: 0x3a,
  EE_READY: 0x3c,
  TIMER3_CAPT: 0x3e,
  TIMER3_COMPA: 0x40,
  TIMER3_COMPB: 0x42,
  TIMER3_COMPC: 0x44,
  TIMER3_OVF: 0x46,
  TWI: 0x48,
  SPM_READY: 0x4a,
  TIMER4_COMPA: 0x4c,
  TIMER4_COMPB: 0x4e,
  TIMER4_COMPD: 0x50,
  TIMER4_OVF: 0x52,
  TIMER4_FPF: 0x54,
});
const VECTOR_NAMES = new Map(Object.entries(VECTORS).map(([name, address]) => [address, name]));

/** The name of the vector at a word address, or `vector@0x..` for one the table does not name. */
export function vectorName(address) {
  return VECTOR_NAMES.get(address) ?? `vector@0x${address.toString(16)}`;
}

/** Each port by its letter: its three registers, as avr8js's port model names them. */
const PORTS = {
  B: { PIN: REG.PINB, DDR: REG.DDRB, PORT: REG.PORTB },
  C: { PIN: REG.PINC, DDR: REG.DDRC, PORT: REG.PORTC },
  D: { PIN: REG.PIND, DDR: REG.DDRD, PORT: REG.PORTD },
  E: { PIN: REG.PINE, DDR: REG.DDRE, PORT: REG.PORTE },
  F: { PIN: REG.PINF, DDR: REG.DDRF, PORT: REG.PORTF },
};

// External interrupts (datasheet "External Interrupts"): INT0..INT3 on PD0..PD3, sensed as
// EICRA's ISCn1:0 pairs; INT6 on PE6, sensed by EICRB's ISC61:60 (bits 5:4).
const external = (index, eicr, iscOffset, interrupt) => ({
  EICR: eicr,
  EIMSK: REG.EIMSK,
  EIFR: REG.EIFR,
  index,
  iscOffset,
  interrupt,
});
const INT0 = external(0, REG.EICRA, 0, VECTORS.INT0);
const INT1 = external(1, REG.EICRA, 2, VECTORS.INT1);
const INT2 = external(2, REG.EICRA, 4, VECTORS.INT2);
const INT3 = external(3, REG.EICRA, 6, VECTORS.INT3);
const INT6 = external(6, REG.EICRB, 4, VECTORS.INT6);
// Pin-change interrupts: only PCINT0..7, all on port B, behind PCICR's PCIE0.
const PCINT0 = {
  PCIE: 0,
  PCICR: REG.PCICR,
  PCIFR: REG.PCIFR,
  PCMSK: REG.PCMSK0,
  pinChangeInterrupt: VECTORS.PCINT0,
  mask: 0xff,
  offset: 0,
};
const PORT_CONFIGS = {
  B: { ...PORTS.B, pinChange: PCINT0, externalInterrupts: [] },
  C: { ...PORTS.C, externalInterrupts: [] },
  D: { ...PORTS.D, externalInterrupts: [INT0, INT1, INT2, INT3] },
  E: { ...PORTS.E, externalInterrupts: [null, null, null, null, null, null, INT6] },
  F: { ...PORTS.F, externalInterrupts: [] },
};

// Timers: the prescaler table is the 328P's (clk/1, 8, 64, 256, 1024, external), which the
// datasheet gives for Timer0, Timer1 and Timer3 alike. Output-compare pins: OC0A PB7, OC0B PD0,
// OC1A PB5, OC1B PB6, OC1C PB7, OC3A PC6 (Timer3's B and C units have no pin). External clock
// inputs: Timer0's on PD7, Timer1's on PD6.
const DIVIDERS = { 0: 0, 1: 1, 2: 8, 3: 64, 4: 256, 5: 1024, 6: 0, 7: 0 };
const BITS_8 = { TOV: 1, OCFA: 2, OCFB: 4, OCFC: 0, TOIE: 1, OCIEA: 2, OCIEB: 4, OCIEC: 0 };
const BITS_16 = { TOV: 1, OCFA: 2, OCFB: 4, OCFC: 8, TOIE: 1, OCIEA: 2, OCIEB: 4, OCIEC: 8 };
export const TIMER0 = {
  bits: 8, captureInterrupt: 0, compAInterrupt: VECTORS.TIMER0_COMPA,
  compBInterrupt: VECTORS.TIMER0_COMPB, compCInterrupt: 0, ovfInterrupt: VECTORS.TIMER0_OVF,
  TIFR: REG.TIFR0, OCRA: REG.OCR0A, OCRB: REG.OCR0B, OCRC: 0, ICR: 0, TCNT: REG.TCNT0,
  TCCRA: REG.TCCR0A, TCCRB: REG.TCCR0B, TCCRC: 0, TIMSK: REG.TIMSK0, dividers: DIVIDERS,
  compPortA: REG.PORTB, compPinA: 7, compPortB: REG.PORTD, compPinB: 0, compPortC: 0,
  compPinC: 0, externalClockPort: REG.PORTD, externalClockPin: 7, ...BITS_8,
}; // prettier-ignore
export const TIMER1 = {
  bits: 16, captureInterrupt: VECTORS.TIMER1_CAPT, compAInterrupt: VECTORS.TIMER1_COMPA,
  compBInterrupt: VECTORS.TIMER1_COMPB, compCInterrupt: VECTORS.TIMER1_COMPC,
  ovfInterrupt: VECTORS.TIMER1_OVF, TIFR: REG.TIFR1, OCRA: REG.OCR1AL, OCRB: REG.OCR1BL,
  OCRC: REG.OCR1CL, ICR: REG.ICR1L, TCNT: REG.TCNT1L, TCCRA: REG.TCCR1A, TCCRB: REG.TCCR1B,
  TCCRC: REG.TCCR1C, TIMSK: REG.TIMSK1, dividers: DIVIDERS, compPortA: REG.PORTB, compPinA: 5,
  compPortB: REG.PORTB, compPinB: 6, compPortC: REG.PORTB, compPinC: 7,
  externalClockPort: REG.PORTD, externalClockPin: 6, ...BITS_16,
}; // prettier-ignore
export const TIMER3 = {
  bits: 16, captureInterrupt: VECTORS.TIMER3_CAPT, compAInterrupt: VECTORS.TIMER3_COMPA,
  compBInterrupt: VECTORS.TIMER3_COMPB, compCInterrupt: VECTORS.TIMER3_COMPC,
  ovfInterrupt: VECTORS.TIMER3_OVF, TIFR: REG.TIFR3, OCRA: REG.OCR3AL, OCRB: REG.OCR3BL,
  OCRC: REG.OCR3CL, ICR: REG.ICR3L, TCNT: REG.TCNT3L, TCCRA: REG.TCCR3A, TCCRB: REG.TCCR3B,
  TCCRC: REG.TCCR3C, TIMSK: REG.TIMSK3, dividers: DIVIDERS, compPortA: REG.PORTC, compPinA: 6,
  compPortB: 0, compPinB: 0, compPortC: 0, compPinC: 0, externalClockPort: 0,
  externalClockPin: 0, ...BITS_16,
}; // prettier-ignore

const USART1 = {
  rxCompleteInterrupt: VECTORS.USART1_RX,
  dataRegisterEmptyInterrupt: VECTORS.USART1_UDRE,
  txCompleteInterrupt: VECTORS.USART1_TX,
  UCSRA: REG.UCSR1A,
  UCSRB: REG.UCSR1B,
  UCSRC: REG.UCSR1C,
  UBRRL: REG.UBRR1L,
  UBRRH: REG.UBRR1H,
  UDR: REG.UDR1,
};

const TWI = {
  twiInterrupt: VECTORS.TWI,
  TWBR: REG.TWBR,
  TWSR: REG.TWSR,
  TWAR: REG.TWAR,
  TWDR: REG.TWDR,
  TWCR: REG.TWCR,
  TWAMR: REG.TWAMR,
};

// The ADC: avr8js reads every mux code it has no entry for as a constant 0 V and a reserved
// reference as AVCC, so the chip stands in front of its conversions (`guardAdc`): only the inputs
// below have a value, and a conversion of anything else ends the evidence. What has one: the
// battery's channel 6 (the only thing wired to an ADC pin: ADC0 and ADC1 are the right encoder's
// B channel and a pin nothing is connected to, and the other single-ended channels are
// likewise not given a voltage), the 1.1 V band gap at 0b011110 and ground at 0b011111; and of
// the references AVCC (REFS1:0 = 01) and the internal 2.56 V (11). MUX5 (ADCSRB bit 5) selects
// ADC8..ADC13, the temperature sensor and the high-gain pairs, none of which has a value here;
// avr8js reads MUX5 from bit 3, the ATmega2560's place, so the mask below drops it.
const ADC_CHANNELS = {
  6: { type: ADCMuxInputType.SingleEnded, channel: 6 },
  0x1e: { type: ADCMuxInputType.Constant, voltage: 1.1 },
  0x1f: { type: ADCMuxInputType.Constant, voltage: 0 },
};
/** The ADC clock range for the full 10 bits (datasheet "ADC Clock Source"): 50 to 200 kHz. */
const ADC_CLOCK_HZ = Object.freeze({ min: 50_000, max: 200_000 });
const ADC = {
  ADMUX: REG.ADMUX,
  ADCSRA: REG.ADCSRA,
  ADCSRB: REG.ADCSRB,
  ADCL: REG.ADCL,
  ADCH: REG.ADCH,
  DIDR0: REG.DIDR0,
  adcInterrupt: VECTORS.ADC,
  numChannels: 8,
  muxInputMask: 0x1f,
  muxChannels: ADC_CHANNELS,
  adcReferences: [
    ADCReference.AREF,
    ADCReference.AVCC,
    ADCReference.Reserved,
    ADCReference.Internal2V56,
  ],
};

const EEPROM = {
  eepromReadyInterrupt: VECTORS.EE_READY,
  EECR: REG.EECR,
  EEDR: REG.EEDR,
  EEARL: REG.EEARL,
  EEARH: REG.EEARH,
  // Erase only and write only 1.8 ms each, as the datasheet's "EEPROM Mode Bits" table gives
  // them; avr8js takes an atomic erase-and-write as their sum, 3.6 ms, 0.2 ms longer than the
  // table's 3.4 ms (a later EEPROM-ready, which does not flatter firmware).
  eraseCycles: 28_800,
  writeCycles: 28_800,
};

// MCUSR's reset flags (datasheet "MCUSR - MCU Status Register").
export const MCUSR_PORF = 0x01;
export const MCUSR_EXTRF = 0x02;
export const MCUSR_BORF = 0x04;
export const MCUSR_WDRF = 0x08;

/** The PLL's lock time. The datasheet ("PLLCSR", PLOCK) gives only "about several ms"; the rig
 * takes 10 ms, the long end of that reading, so a start-up that waits on PLOCK is not shortened. */
export const PLL_LOCK_CYCLES = FREQUENCY_HZ / 100;

/** The four-cycle interrupt response for a part with a two-byte program counter, of which avr8js
 * counts two (datasheet "Interrupt Response Time"). */
const RESPONSE_CYCLES_MISSING = 2;

/**
 * The 2-wire interface, timed at its bit rate.
 *
 * avr8js's TWI hands each bus step to an event handler and completes when the handler says. This
 * one completes each step after the time the bus takes for it at the configured rate, f_SCL =
 * f_CPU / (16 + 2 * TWBR * 4^TWPS) (datasheet "Bit Rate Generator Unit"): a START or a STOP one
 * SCL period, an address or data byte nine (eight bits and the acknowledge), counted from the
 * TWCR write that began the step. What answers on the bus is the board's (`bus` below). Changes
 * from avr8js, each to the datasheet's TWI:
 *
 * - TWCR is 0 at reset ("TWCR", initial value 0x00); TWSR's status bits are read-only (only TWPS
 *   is written).
 * - TWINT is not set after a STOP; TWINT is not cleared by the vector's execution, only by
 *   writing a one to it, so its interrupt is a level; writing a zero to TWINT leaves it set; and
 *   clearing TWEN ends whatever the interface was doing, a START waiting for the bus included.
 * - With SDA held low by a device: a START never completes (TWSTA: the TWI waits for the bus to
 *   be free); a STOP cannot be sent, so TWSTO stays set until SDA is released; and a master
 *   sending a 1 (an address or data bit, or a NOT ACK) loses arbitration, status 0x38 ("Arbitration
 *   lost in SLA+W or data bytes" / "in SLA+R or NOT ACK bit"), while a 0 sent or an ACK reads back
 *   as itself. The loss is reported when the byte's nine bit periods are over.
 */
class TimedTWI extends AVRTWI {
  constructor(cpu, bus, onTransfer) {
    super(cpu, TWI, FREQUENCY_HZ);
    this.TWI.constant = true;
    cpu.data[REG.TWCR] = 0; // avr8js sets TWINT at construction; the part's TWCR resets to 0
    this.bus = bus;
    this.onTransfer = onTransfer;
    this.pending = null;
    this.stepFrom = 0;
    const twi = this;
    const enabled = () => !!(cpu.data[REG.TWCR] & 0x04);
    const held = () => !!(twi.bus.held && twi.bus.held());
    this.eventHandler = {
      start(repeated) {
        if (!enabled()) return;
        twi.later(1, () => (twi.bus.start(repeated) ? twi.completeStart() : null));
      },
      stop() {
        if (!enabled()) return;
        const attempt = () => {
          if (twi.bus.stop() === false) {
            twi.stepFrom = twi.cpu.cycles;
            twi.later(1, attempt); // SDA held: no STOP can be sent; TWSTO stays set
            return;
          }
          twi.completeStop();
        };
        twi.later(1, attempt);
      },
      connectToSlave(address, write) {
        if (!enabled()) return;
        twi.later(9, () => {
          if (held() && (address << 1) | (write ? 0 : 1)) return twi.lost({ kind: 'address', address, write });
          const ack = held() || twi.bus.connect(address, write);
          twi.onTransfer({ kind: 'address', address, write, ack });
          return twi.completeConnect(ack);
        });
      },
      writeByte(value) {
        if (!enabled()) return;
        twi.later(9, () => {
          if (held() && value) return twi.lost({ kind: 'write', value });
          const ack = held() || twi.bus.write(value);
          twi.onTransfer({ kind: 'write', value, ack });
          return twi.completeWrite(ack);
        });
      },
      readByte(ack) {
        if (!enabled()) return;
        twi.later(9, () => {
          if (held() && !ack) return twi.lost({ kind: 'read', value: 0, ack });
          const value = twi.bus.read(ack);
          twi.onTransfer({ kind: 'read', value, ack });
          return twi.completeRead(value);
        });
      },
    };
    const write = cpu.writeHooks[REG.TWCR];
    cpu.writeHooks[REG.TWCR] = (value, old, addr, mask) => {
      if (!(value & 0x04)) this.abort();
      if (value & 0x80) this.stepFrom = cpu.cycles;
      if (!write(value, old, addr, mask)) cpu.data[REG.TWCR] = value & ~0x80;
      if (!(value & 0x80) && old & 0x80) cpu.data[REG.TWCR] |= 0x80;
      return true;
    };
    cpu.writeHooks[REG.TWSR] = (value, old) => {
      cpu.data[REG.TWSR] = (old & 0xf8) | (value & 0x03); // TWS7:3 read-only, bit 2 reserved
      return true;
    };
  }

  /** CPU cycles per SCL period at the configured rate. */
  get cyclesPerBit() {
    return 16 + 2 * this.cpu.data[REG.TWBR] * this.prescaler;
  }

  /** Run `step` `bits` SCL periods after the TWCR write that began it (avr8js hands the step on
   * one cycle after that write). */
  later(bits, step) {
    const run = () => {
      this.pending = null;
      step();
    };
    this.pending = run;
    this.cpu.addClockEvent(run, this.stepFrom + bits * this.cyclesPerBit - this.cpu.cycles);
  }

  lost(transfer) {
    this.bus.lost?.();
    this.onTransfer({ ...transfer, ack: false, arbitration_lost: true });
    this.busy = false;
    this.updateStatus(0x38);
  }

  abort() {
    if (this.pending) this.cpu.clearClockEvent(this.pending);
    this.pending = null;
    this.busy = false;
    this.cpu.data[REG.TWSR] = (this.cpu.data[REG.TWSR] & 0x07) | 0xf8;
  }

  completeStop() {
    this.busy = false;
    this.cpu.data[REG.TWCR] &= ~0x10; // TWSTO is cleared when the STOP has been sent
    this.cpu.data[REG.TWSR] = (this.cpu.data[REG.TWSR] & 0x07) | 0xf8; // no relevant state
  }
}

/**
 * The watchdog (datasheet "Watchdog Timer"), with safety level 1 (WDTON unprogrammed).
 *
 * - The counter runs from the watchdog oscillator, 128 kHz nominally (a typical figure: the
 *   datasheet's curves at 5 V lie lower, and it gives no bound); its frequency is the chip's
 *   `watchdogHz`. A time-out comes after 2K << WDP oscillator cycles (WDP3..0 = 0 is 16 ms, 9 is 8 s), counted again from WDR and from the
 *   timer's enabling. A change of WDP keeps the count: the new period runs from the last restart,
 *   so a shorter one already passed times out at once (datasheet "WDTCSR", the note to WDP: "a
 *   change in the WDP bits can result in a time-out when switching to a shorter time-out period").
 * - WDE may be set at any time; clearing it or changing WDP needs the timed sequence: WDCE and
 *   WDE written as one in one operation, then within four cycles the new WDE and WDP with WDCE
 *   clear. WDIE is free to write; WDIF is cleared by writing a one, or by the vector.
 * - A time-out with WDIE set sets WDIF; with WDE set and WDIE clear it resets the chip; with both
 *   set the first time-out is an interrupt, whose vector clears WDIE, and the next one resets
 *   (as does a time-out while WDIF is still set).
 * - WDRF in MCUSR forces WDE on, so after a watchdog reset the timer runs at 16 ms until the
 *   firmware clears WDRF and then WDE.
 */
class Watchdog {
  constructor(chip) {
    this.chip = chip;
    const { cpu } = chip;
    this.cpu = cpu;
    this.interrupt = {
      address: VECTORS.WDT,
      flagRegister: REG.WDTCSR,
      flagMask: 0x80,
      enableRegister: REG.WDTCSR,
      enableMask: 0x40,
    };
    this.changeUntil = -1;
    this.timeout = 0;
    this.started = 0;
    // Never taken off the clock's queue while it runs: avr8js reuses a removed entry for the
    // next one added, and would drop it when the running one returns.
    this.scheduled = false;
    this.expire = () => {
      this.scheduled = false;
      this.expired();
    };
    cpu.onWatchdogReset = () => this.restart();
    cpu.writeHooks[REG.WDTCSR] = (value, old) => {
      this.write(value, old);
      return true;
    };
    cpu.writeHooks[REG.MCUSR] = (value, old) => {
      // A flag is cleared by writing a zero to it; writing a one leaves it as it is.
      cpu.data[REG.MCUSR] = old & value;
      return true;
    };
    if (cpu.data[REG.MCUSR] & MCUSR_WDRF) cpu.data[REG.WDTCSR] = 0x08;
    if (this.running) this.restart();
  }

  get running() {
    return !!(this.cpu.data[REG.WDTCSR] & 0x48);
  }

  get period() {
    const wdtcsr = this.cpu.data[REG.WDTCSR];
    const wdp = ((wdtcsr & 0x20) >> 2) | (wdtcsr & 0x07);
    return Math.round((FREQUENCY_HZ / this.chip.watchdogHz) * (2048 << Math.min(wdp, 9)));
  }

  write(value, old) {
    const { cpu } = this;
    const wasRunning = this.running;
    const oldPrescaler = old & 0x27;
    let next = old & ~0x10;
    if (value & 0x80) {
      next &= ~0x80;
      cpu.clearInterrupt(this.interrupt, false);
    }
    next = (next & ~0x40) | (value & 0x40);
    if (value & 0x10 && value & 0x08) {
      this.changeUntil = cpu.cycles + 4;
      next |= 0x08;
    } else if (cpu.cycles <= this.changeUntil) {
      next = (next & ~0x2f) | (value & 0x2f);
      this.changeUntil = -1;
    } else if (value & 0x08) {
      next |= 0x08;
    }
    if (cpu.data[REG.MCUSR] & MCUSR_WDRF) next |= 0x08;
    cpu.data[REG.WDTCSR] = next;
    cpu.updateInterruptEnable(this.interrupt, next);
    if (this.running && !wasRunning) {
      this.restart();
      return;
    }
    if ((next & 0x27) !== oldPrescaler) this.timeout = this.started + this.period;
    this.schedule();
  }

  restart() {
    this.started = this.cpu.cycles;
    this.timeout = this.started + this.period;
    this.schedule();
  }

  schedule() {
    if (this.scheduled) this.cpu.clearClockEvent(this.expire);
    this.scheduled = false;
    if (!this.running) return;
    this.cpu.addClockEvent(this.expire, this.timeout - this.cpu.cycles); // at once if passed
    this.scheduled = true;
  }

  expired() {
    const { cpu } = this;
    const wdtcsr = cpu.data[REG.WDTCSR];
    const reset = wdtcsr & 0x08 && (!(wdtcsr & 0x40) || wdtcsr & 0x80);
    if (reset) {
      this.chip.requestReset('watchdog');
      return;
    }
    if (wdtcsr & 0x40) cpu.setInterruptFlag(this.interrupt);
    this.restart();
  }

  /** The vector's execution clears WDIF (avr8js does that) and, in interrupt-and-reset mode,
   * WDIE. */
  vectored() {
    if (this.cpu.data[REG.WDTCSR] & 0x08) this.cpu.data[REG.WDTCSR] &= ~0x40;
  }
}

/**
 * The USB controller with no host (datasheet "USB Controller").
 *
 * Its registers store what is written, with these behaviours: the PLL sets PLOCK PLL_LOCK_CYCLES
 * after PLLE is set and clears it with PLLE; UDINT's
 * flags can only be cleared by software, by writing a zero; USB_GEN is a level, pending while
 * any flag in UDINT has its enable in UDIEN. No host means no bus reset, no enumeration and no
 * data: VBUS reads 0, so USBINT's flag never sets. Start-of-frame interrupts at 1 kHz can be switched on as a load (`sof`),
 * which a real host gives only after enumeration; each sets SOFI and steps the frame number,
 * while the controller is enabled, its clock running, the PLL locked and the device attached.
 */
class Usb {
  constructor(chip, { sof }) {
    const { cpu } = chip;
    this.cpu = cpu;
    this.interrupt = {
      address: VECTORS.USB_GEN,
      flagRegister: REG.UDINT,
      flagMask: 0,
      enableRegister: REG.UDIEN,
      enableMask: 0,
      constant: true,
    };
    cpu.data[REG.USBCON] = 0x20; // FRZCLK set at reset
    cpu.data[REG.UDCON] = 0x01; // DETACH set at reset
    this.lock = () => {
      if (cpu.data[REG.PLLCSR] & 0x02) cpu.data[REG.PLLCSR] |= 0x01;
    };
    cpu.writeHooks[REG.PLLCSR] = (value, old) => {
      const locked = old & 0x01;
      cpu.data[REG.PLLCSR] = (value & ~0x01) | (value & 0x02 ? locked : 0);
      if (value & 0x02 && !(old & 0x02)) cpu.addClockEvent(this.lock, PLL_LOCK_CYCLES);
      if (!(value & 0x02)) cpu.clearClockEvent(this.lock);
      return true;
    };
    cpu.writeHooks[REG.UDINT] = (value, old) => {
      cpu.data[REG.UDINT] = old & value;
      this.update();
      return true;
    };
    cpu.writeHooks[REG.UDIEN] = (value) => {
      cpu.data[REG.UDIEN] = value;
      this.update();
      return true;
    };
    cpu.writeHooks[REG.USBINT] = (value, old) => {
      cpu.data[REG.USBINT] = old & value; // VBUSTI is cleared by writing a zero, never set by a write
      return true;
    };
    cpu.writeHooks[REG.USBSTA] = (value, old) => {
      cpu.data[REG.USBSTA] = (old & 0x01) | (value & ~0x01); // VBUS is read-only
      return true;
    };
    if (sof) {
      this.frame = () => {
        this.startOfFrame();
        cpu.addClockEvent(this.frame, FREQUENCY_HZ / 1000);
      };
      cpu.addClockEvent(this.frame, FREQUENCY_HZ / 1000);
    }
  }

  get attached() {
    const { data } = this.cpu;
    return (
      (data[REG.USBCON] & 0xa0) === 0x80 && data[REG.PLLCSR] & 0x01 && !(data[REG.UDCON] & 0x01)
    );
  }

  startOfFrame() {
    if (!this.attached) return;
    const { data } = this.cpu;
    const frame = ((data[REG.UDFNUMH] << 8) | data[REG.UDFNUML]) + 1;
    data[REG.UDFNUML] = frame & 0xff;
    data[REG.UDFNUMH] = (frame >> 8) & 0x07;
    data[REG.UDINT] |= 0x04;
    this.update();
  }

  update() {
    const { data } = this.cpu;
    if (data[REG.UDINT] & data[REG.UDIEN] & 0x7d) this.cpu.queueInterrupt(this.interrupt);
    else this.cpu.clearInterrupt(this.interrupt, false);
  }
}

/**
 * The EEPROM's cells, counting each programming operation on each (datasheet "EEPROM Data
 * Memory": an endurance of at least 100,000 write/erase cycles). An atomic erase-and-write is one
 * operation on the cell, an erase only or a write only one each; `now` is the chip's cycle count,
 * which tells the two halves of an atomic operation (the same cycle) from two operations.
 */
export class CountingEEPROM extends EEPROMMemoryBackend {
  constructor(size) {
    super(size);
    this.now = () => 0;
    this.cells = new Uint32Array(size);
    this.writes = 0;
    this.erased = null;
  }

  count(address) {
    this.cells[address] += 1;
    this.writes += 1;
  }

  eraseMemory(address) {
    this.count(address);
    this.erased = { address, at: this.now() };
    super.eraseMemory(address);
  }

  writeMemory(address, value) {
    const half = this.erased && this.erased.address === address && this.erased.at === this.now();
    if (!half) this.count(address);
    this.erased = null;
    super.writeMemory(address, value);
  }

  counts() {
    return { writes: this.writes, per_address_max: this.cells.reduce((a, b) => Math.max(a, b), 0) };
  }
}

/**
 * One ATmega32U4 from reset.
 *
 * A reset makes a new chip: every register at its reset value, the program counter at the reset
 * vector, the cycle count carried on. SRAM and EEPROM keep their contents, as they do on the
 * part. `board` is told of each new chip so it can wire its devices to the new peripherals.
 */
export class ATmega32U4 {
  /**
   * @param {Uint16Array} program the flash image, in words
   * @param {{cycles?: number, mcusr?: number, sram?: Uint8Array, eeprom: EEPROMMemoryBackend,
   *   sof?: boolean, bus: object, onTransfer?: Function, onUnmodelled?: Function,
   *   onEvidenceEnd?: Function, watchdogHz?: number}} options
   */
  constructor(program, options) {
    const cpu = new CPU(program, SRAM_BYTES);
    this.cpu = cpu;
    this.watchdogHz = options.watchdogHz ?? 128_000;
    cpu.cycles = options.cycles ?? 0;
    if (options.sram) cpu.data.set(options.sram, 0x100);
    cpu.data[REG.MCUSR] = options.mcusr ?? MCUSR_PORF;
    this.resetRequest = null;
    this.ports = {};
    for (const [letter, config] of Object.entries(PORT_CONFIGS)) {
      this.ports[letter] = new AVRIOPort(cpu, config);
    }
    this.timer0 = new AVRTimer(cpu, TIMER0);
    this.timer1 = new AVRTimer(cpu, TIMER1);
    this.timer3 = new AVRTimer(cpu, TIMER3);
    for (const timer of [this.timer0, this.timer1, this.timer3]) completeTimer(cpu, timer);
    this.usart1 = new AVRUSART(cpu, USART1, FREQUENCY_HZ);
    this.twi = new TimedTWI(cpu, options.bus, options.onTransfer ?? (() => {}));
    this.adc = new AVRADC(cpu, ADC);
    if ('now' in options.eeprom) options.eeprom.now = () => cpu.cycles;
    this.eeprom = new AVREEPROM(cpu, options.eeprom, EEPROM);
    this.watchdog = new Watchdog(this);
    this.usb = new Usb(this, { sof: !!options.sof });
    const unmodelled = options.onUnmodelled ?? (() => {});
    const end = options.onEvidenceEnd ?? (() => {});
    this.guardAdc(unmodelled, end);
    this.watchRegisters(unmodelled, end);
  }

  /**
   * Every register's entry of REGISTER_OUTCOMES, acted on: an access that is a use of what the rig
   * does not model is reported (`report(feature)`), and one that ends the evidence says so
   * (`end(cause, detail)`), after the register has done what it does (a write is stored first).
   */
  watchRegisters(report, end) {
    const { cpu } = this;
    for (const [key, entry] of Object.entries(REGISTER_OUTCOMES)) {
      const address = Number(key);
      const act = (access, value) => {
        const features = entry.uses ? entry.uses(value, access, this) : [entry.feature ?? entry.cause];
        if (!features.length) return;
        if (entry.outcome === 'ends') {
          if (!entry.silent) report(entry.cause);
          end(entry.cause, entry.detail ? entry.detail(value, access, this, entry.name) : {});
        } else {
          for (const feature of features) report(feature);
        }
      };
      const on = entry.on ?? 'write';
      if (entry.outcome === 'modelled' && !entry.uses) continue;
      if (on !== 'read') observeWrite(cpu, address, (value) => act('write', value));
      if (on !== 'write') observeRead(cpu, address, (value) => act('read', value));
    }
  }

  /**
   * The ADC's conversions: avr8js gives an input it has no entry for a constant 0 V, a reserved
   * reference AVCC, and a start with the ADC disabled an interrupt flag the part never sets. A
   * conversion the model has no value for ends the evidence instead of starting; a clock outside
   * 50 to 200 kHz, at which the part does not resolve the 10 bits it is read as, is reported.
   */
  guardAdc(report, end) {
    const { cpu } = this;
    const start = cpu.writeHooks[REG.ADCSRA];
    cpu.writeHooks[REG.ADCSRA] = (value, old, address, mask) => {
      if (value & 0x40 && !this.adc.converting) {
        const mux = (cpu.data[REG.ADMUX] & 0x1f) | (cpu.data[REG.ADCSRB] & 0x20);
        const refs = cpu.data[REG.ADMUX] >> 6;
        let why = null;
        if (!(value & 0x80)) why = 'a conversion started with the ADC disabled, which the part does not start';
        else if (!(mux in ADC_CHANNELS)) why = 'an input nothing models: no pin or source of the board is attached to it';
        else if (refs !== 1 && refs !== 3) why = 'a reference that is not AVCC or the internal 2.56 V';
        if (why) {
          report('adc_input');
          end('adc_input', { mux, refs, why });
          cpu.data[REG.ADCSRA] = value & ~0x40;
          return true;
        }
        const divisor = Math.max(2, 1 << (value & 0x07)); // ADPS2:0 (0 and 1 both divide by 2)
        const clock = FREQUENCY_HZ / divisor;
        if (clock > ADC_CLOCK_HZ.max || clock < ADC_CLOCK_HZ.min) report('adc_clock');
      }
      return start(value, old, address, mask);
    };
  }

  requestReset(cause) {
    this.resetRequest ??= cause;
  }

  /** What the next chip carries over from this one. */
  carried() {
    return { cycles: this.cpu.cycles, sram: this.cpu.data.slice(0x100) };
  }

  get sp() {
    return this.cpu.data[REG.SPL] | (this.cpu.data[REG.SPH] << 8);
  }

  pinState(letter, index) {
    return this.ports[letter].pinState(index);
  }

  /** Whether a pin is an output driven high. */
  drivenHigh(letter, index) {
    return this.ports[letter].pinState(index) === PinState.High;
  }
}

/** Run `observe()` after every read of `address`, whatever the register gives. */
export function observeRead(cpu, address, observe) {
  const previous = cpu.readHooks[address];
  cpu.readHooks[address] = (addr) => {
    const value = previous ? previous(addr) : cpu.data[addr];
    observe(value);
    return value;
  };
}

/** Run `observe(value)` after every write to `address`, whatever the register does with it. */
export function observeWrite(cpu, address, observe) {
  const previous = cpu.writeHooks[address];
  cpu.writeHooks[address] = (value, old, addr, mask) => {
    const handled = previous ? previous(value, old, addr, mask) : false;
    if (!handled) cpu.data[address] = value;
    observe(value, old);
    return true;
  };
}

/**
 * What avr8js's timer leaves out of the 32U4's TIFRn and TIMSKn: the C compare unit's flag and
 * enable, and a write of a zero to a flag, which leaves it set (avr8js stores the written byte).
 */
function completeTimer(cpu, timer) {
  const { config } = timer;
  const interrupts = [timer.OVF, timer.OCFA, timer.OCFB];
  if (config.OCFC) interrupts.push(timer.OCFC);
  cpu.writeHooks[config.TIFR] = (value) => {
    for (const interrupt of interrupts) cpu.clearInterruptByFlag(interrupt, value);
    return true;
  };
  if (config.OCFC) {
    const previous = cpu.writeHooks[config.TIMSK];
    cpu.writeHooks[config.TIMSK] = (value, old, addr, mask) => {
      previous(value, old, addr, mask);
      cpu.data[config.TIMSK] = value;
      cpu.updateInterruptEnable(timer.OCFC, value);
      return true;
    };
  }
}

export { EEPROMMemoryBackend, PinState };
