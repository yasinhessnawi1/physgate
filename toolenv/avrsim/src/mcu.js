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

// Data-memory addresses (an I/O register's `_SFR_IO8(n)` lies at n + 0x20).
export const REG = Object.freeze({
  PINB: 0x23, DDRB: 0x24, PORTB: 0x25,
  PINC: 0x26, DDRC: 0x27, PORTC: 0x28,
  PIND: 0x29, DDRD: 0x2a, PORTD: 0x2b,
  PINE: 0x2c, DDRE: 0x2d, PORTE: 0x2e,
  PINF: 0x2f, DDRF: 0x30, PORTF: 0x31,
  TIFR0: 0x35, TIFR1: 0x36, TIFR3: 0x38, TIFR4: 0x39,
  PCIFR: 0x3b, EIFR: 0x3c, EIMSK: 0x3d,
  EECR: 0x3f, EEDR: 0x40, EEARL: 0x41, EEARH: 0x42,
  TCCR0A: 0x44, TCCR0B: 0x45, TCNT0: 0x46, OCR0A: 0x47, OCR0B: 0x48,
  PLLCSR: 0x49,
  SPCR: 0x4c, SPSR: 0x4d, SPDR: 0x4e,
  ACSR: 0x50, PLLFRQ: 0x52, SMCR: 0x53, MCUSR: 0x54,
  SPL: 0x5d, SPH: 0x5e, SREG: 0x5f,
  WDTCSR: 0x60, CLKPR: 0x61,
  PCICR: 0x68, EICRA: 0x69, EICRB: 0x6a, PCMSK0: 0x6b,
  TIMSK0: 0x6e, TIMSK1: 0x6f, TIMSK3: 0x71, TIMSK4: 0x72,
  ADCL: 0x78, ADCH: 0x79, ADCSRA: 0x7a, ADCSRB: 0x7b, ADMUX: 0x7c, DIDR0: 0x7e,
  TCCR1A: 0x80, TCCR1B: 0x81, TCCR1C: 0x82, TCNT1L: 0x84, ICR1L: 0x86,
  OCR1AL: 0x88, OCR1BL: 0x8a, OCR1CL: 0x8c,
  TCCR3A: 0x90, TCCR3B: 0x91, TCCR3C: 0x92, TCNT3L: 0x94, ICR3L: 0x96,
  OCR3AL: 0x98, OCR3BL: 0x9a, OCR3CL: 0x9c,
  TWBR: 0xb8, TWSR: 0xb9, TWAR: 0xba, TWDR: 0xbb, TWCR: 0xbc, TWAMR: 0xbd,
  TCNT4: 0xbe, TC4H: 0xbf, TCCR4A: 0xc0, TCCR4B: 0xc1, TCCR4C: 0xc2, TCCR4D: 0xc3,
  TCCR4E: 0xc4,
  UCSR1A: 0xc8, UCSR1B: 0xc9, UCSR1C: 0xca, UCSR1D: 0xcb, UBRR1L: 0xcc, UBRR1H: 0xcd,
  UDR1: 0xce,
  OCR4A: 0xcf, OCR4B: 0xd0, OCR4C: 0xd1, OCR4D: 0xd2, DT4: 0xd4,
  UHWCON: 0xd7, USBCON: 0xd8, USBSTA: 0xd9,
  UDCON: 0xe0, UDINT: 0xe1, UDIEN: 0xe2, UDADDR: 0xe3, UDFNUML: 0xe4, UDFNUMH: 0xe5,
  UEINTX: 0xe8, UENUM: 0xe9, UEDATX: 0xf1,
}); // prettier-ignore

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

// The ADC: single-ended ADC0..ADC7 by MUX4:0 (ADC2 and ADC3 have no pin on the 32U4), the
// 1.1 V band gap at 0b11110 and ground at 0b11111; REFS1:0 = 11 is the internal 2.56 V.
// MUX5 (ADCSRB bit 5) is not modelled: avr8js reads MUX5 from bit 3, the ATmega2560's place,
// and the mask below drops it, so a conversion of ADC8..ADC13 or the temperature sensor reads
// the channel its low five bits name. Such a conversion is listed as unmodelled.
const ADC_CHANNELS = {};
for (let channel = 0; channel < 8; channel += 1) {
  ADC_CHANNELS[channel] = { type: ADCMuxInputType.SingleEnded, channel };
}
ADC_CHANNELS[0x1e] = { type: ADCMuxInputType.Constant, voltage: 1.1 };
ADC_CHANNELS[0x1f] = { type: ADCMuxInputType.Constant, voltage: 0 };
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
  // Erase only and write only 1.8 ms each, an atomic erase-and-write their sum, 3.4 ms (avr8js
  // sums them), as the datasheet's "EEPROM Mode Bits" table gives them.
  eraseCycles: 28_800,
  writeCycles: 28_800,
};

// MCUSR's reset flags.
export const MCUSR_PORF = 0x01;
export const MCUSR_WDRF = 0x08;

/** The four-cycle interrupt response for a part with a two-byte program counter, of which avr8js
 * counts two (datasheet "Interrupt Response Time"). */
const RESPONSE_CYCLES_MISSING = 2;

/**
 * The 2-wire interface, timed at its bit rate.
 *
 * avr8js's TWI hands each bus step to an event handler and completes when the handler says. This
 * one completes each step after the time the bus takes for it at the configured rate, f_SCL =
 * f_CPU / (16 + 2 * TWBR * 4^TWPS) (datasheet "Bit Rate Generator Unit"): a START or a STOP one
 * SCL period, an address or data byte nine (eight bits and the acknowledge). What answers on the
 * bus is the board's (`bus` below); a START the bus cannot give (SDA held low) never completes.
 * Changes from avr8js, each to the datasheet's TWI: TWINT is not set after a STOP; TWINT is not
 * cleared by the vector's execution, only by writing a one to it, so its interrupt is a level;
 * writing a zero to TWINT leaves it set; and clearing TWEN ends whatever the interface was doing,
 * a START waiting for the bus included.
 */
class TimedTWI extends AVRTWI {
  constructor(cpu, bus, onTransfer) {
    super(cpu, TWI, FREQUENCY_HZ);
    this.TWI.constant = true;
    this.bus = bus;
    this.onTransfer = onTransfer;
    this.pending = null;
    const twi = this;
    const enabled = () => !!(cpu.data[REG.TWCR] & 0x04);
    this.eventHandler = {
      start(repeated) {
        if (!enabled()) return;
        twi.later(1, () => (twi.bus.start(repeated) ? twi.completeStart() : null));
      },
      stop() {
        if (!enabled()) return;
        twi.later(1, () => {
          twi.bus.stop();
          twi.completeStop();
        });
      },
      connectToSlave(address, write) {
        if (!enabled()) return;
        twi.later(9, () => {
          const ack = twi.bus.connect(address, write);
          twi.onTransfer({ kind: 'address', address, write, ack });
          twi.completeConnect(ack);
        });
      },
      writeByte(value) {
        if (!enabled()) return;
        twi.later(9, () => {
          const ack = twi.bus.write(value);
          twi.onTransfer({ kind: 'write', value, ack });
          twi.completeWrite(ack);
        });
      },
      readByte(ack) {
        if (!enabled()) return;
        twi.later(9, () => {
          const value = twi.bus.read(ack);
          twi.onTransfer({ kind: 'read', value, ack });
          twi.completeRead(value);
        });
      },
    };
    const write = cpu.writeHooks[REG.TWCR];
    cpu.writeHooks[REG.TWCR] = (value, old, addr, mask) => {
      if (!(value & 0x04)) this.abort();
      if (!write(value, old, addr, mask)) cpu.data[REG.TWCR] = value & ~0x80;
      if (!(value & 0x80) && old & 0x80) cpu.data[REG.TWCR] |= 0x80;
      return true;
    };
  }

  /** CPU cycles per SCL period at the configured rate. */
  get cyclesPerBit() {
    return 16 + 2 * this.cpu.data[REG.TWBR] * this.prescaler;
  }

  later(bits, step) {
    const run = () => {
      this.pending = null;
      step();
    };
    this.pending = run;
    this.cpu.addClockEvent(run, bits * this.cyclesPerBit);
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
 * - The counter runs from the 128 kHz oscillator, nominally; a time-out comes after 2K << WDP
 *   oscillator cycles (WDP3..0 = 0 is 16 ms, 9 is 8 s), restarted by WDR and when the timer is
 *   enabled or its prescaler changed.
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
    this.schedule();
  }

  get running() {
    return !!(this.cpu.data[REG.WDTCSR] & 0x48);
  }

  get period() {
    const wdtcsr = this.cpu.data[REG.WDTCSR];
    const wdp = ((wdtcsr & 0x20) >> 2) | (wdtcsr & 0x07);
    return Math.round((FREQUENCY_HZ / 128_000) * (2048 << Math.min(wdp, 9)));
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
    if (this.running && (!wasRunning || (next & 0x27) !== oldPrescaler)) this.restart();
    this.schedule();
  }

  restart() {
    this.timeout = this.cpu.cycles + this.period;
    this.schedule();
  }

  schedule() {
    if (this.scheduled) this.cpu.clearClockEvent(this.expire);
    this.scheduled = false;
    if (!this.running) return;
    if (this.timeout <= this.cpu.cycles) this.timeout = this.cpu.cycles + this.period;
    this.cpu.addClockEvent(this.expire, this.timeout - this.cpu.cycles);
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
    this.timeout = cpu.cycles + this.period;
    this.schedule();
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
 * Its registers store what is written, with these behaviours: the PLL sets PLOCK a fixed time
 * after PLLE is set (the rig's 100 us, not a datasheet figure) and clears it with PLLE; UDINT's
 * flags can only be cleared by software, by writing a zero; USB_GEN is a level, pending while
 * any flag in UDINT has its enable in UDIEN. No host means no bus reset, no enumeration and no
 * data: VBUS reads 0. Start-of-frame interrupts at 1 kHz can be switched on as a load (`sof`),
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
      if (value & 0x02 && !(old & 0x02)) cpu.addClockEvent(this.lock, FREQUENCY_HZ / 10_000);
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

/** Register ranges the chip keeps as plain storage: a write to one is listed in the summary. */
export const UNMODELLED = Object.freeze({
  timer4: [REG.TIFR4, REG.TIMSK4, REG.TCNT4, REG.TC4H, REG.TCCR4A, REG.TCCR4B, REG.TCCR4C,
    REG.TCCR4D, REG.TCCR4E, REG.OCR4A, REG.OCR4B, REG.OCR4C, REG.OCR4D, REG.DT4],
  spi: [REG.SPCR, REG.SPSR, REG.SPDR],
  analog_comparator: [REG.ACSR],
  usb_endpoint_data: [REG.UEDATX],
  sleep_mode_register: [REG.SMCR],
}); // prettier-ignore

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
   *   sof?: boolean, bus: object, onTransfer?: Function, onUnmodelled?: Function}} options
   */
  constructor(program, options) {
    const cpu = new CPU(program, SRAM_BYTES);
    this.cpu = cpu;
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
    this.eeprom = new AVREEPROM(cpu, options.eeprom, EEPROM);
    this.watchdog = new Watchdog(this);
    this.usb = new Usb(this, { sof: !!options.sof });
    this.watchUnmodelled(options.onUnmodelled ?? (() => {}));
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

  watchUnmodelled(report) {
    const { cpu } = this;
    for (const [what, addresses] of Object.entries(UNMODELLED)) {
      for (const address of addresses) observeWrite(cpu, address, () => report(what));
    }
    observeWrite(cpu, REG.CLKPR, () => {
      // The rig runs at 16 MHz whatever the prescaler: a write that changes it is listed.
      if ((cpu.data[REG.CLKPR] & 0x0f) !== 0) report('clock_prescaler');
    });
    observeWrite(cpu, REG.ADCSRA, (value) => {
      if (value & 0x40 && cpu.data[REG.ADCSRB] & 0x20) report('adc_mux5');
    });
  }
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
