// What the rig does with every register of the ATmega32U4's I/O and extended I/O space.
//
// The rule is default-deny: avr8js leaves any register it has no peripheral for as plain memory,
// and a firmware that uses such a register would read back what it wrote, or a zero, and be shown
// a part that works. So each address of 0x20 to 0xFF has exactly one entry here, from the
// datasheet's register summary (Atmel-7766, "Register Summary"), and each entry is one of
//
// - `modelled`: a model acts on the register (an avr8js peripheral the chip configures, the rig's
//   own watchdog, USB, TWI, ADC or sleep code), or it is storage whose only behaviour is to keep
//   what is written (`by: 'storage'`, with its reason in `why`);
// - `reported`: a use the rig does not model is named in the summary's `unmodelled` under
//   `feature`, and what FEATURE_EFFECTS says of it is then not evaluable;
// - `ends`: the use ends the run's evidence (`cause`).
//
// An address the summary calls "Reserved" ends the evidence on any access. `uses(value, access,
// chip)` says which features a given access is (none: it is not a use, as the Arduino core's own
// start-up sets Timer4 up without clocking an output); `on` is `write` (the default), `read` or
// `access`. A new address cannot fall through: the table is filled to every address below, and
// the row that walks the datasheet's summary fails on one that does none of the three.

/** Data-memory addresses (an I/O register's `_SFR_IO8(n)` lies at n + 0x20). */
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
  ACSR: 0x50, PLLFRQ: 0x52, SMCR: 0x53, MCUSR: 0x54, MCUCR: 0x55, SPMCSR: 0x57,
  SPL: 0x5d, SPH: 0x5e, SREG: 0x5f,
  WDTCSR: 0x60, CLKPR: 0x61, PRR0: 0x64, PRR1: 0x65,
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
  CLKSEL0: 0xc5, CLKSEL1: 0xc6,
  UCSR1A: 0xc8, UCSR1B: 0xc9, UCSR1C: 0xca, UCSR1D: 0xcb, UBRR1L: 0xcc, UBRR1H: 0xcd,
  UDR1: 0xce,
  OCR4A: 0xcf, OCR4B: 0xd0, OCR4C: 0xd1, OCR4D: 0xd2, DT4: 0xd4,
  UHWCON: 0xd7, USBCON: 0xd8, USBSTA: 0xd9, USBINT: 0xda,
  UDCON: 0xe0, UDINT: 0xe1, UDIEN: 0xe2, UDADDR: 0xe3, UDFNUML: 0xe4, UDFNUMH: 0xe5,
  UEINTX: 0xe8, UENUM: 0xe9, UEDATX: 0xf1,
}); // prettier-ignore

/**
 * What each reported feature changes in what the summary can claim: `timing` (every figure of
 * time is withheld), `behaviour` (the values firmware reads are not the part's), or neither (a
 * use whose register has no effect on a board that runs from its crystal; it is named and
 * gates nothing). A name ending `:` plus a register (`lsm6ds33:CTRL7_G`) is a sensor setting the
 * model does not act on, and changes the values only.
 */
export const FEATURE_EFFECTS = Object.freeze({
  timer4: ['timing', 'behaviour'],
  input_capture: ['timing', 'behaviour'],
  vector_relocation: ['timing', 'behaviour'],
  pull_up_disable: ['timing', 'behaviour'],
  adc_auto_trigger: ['timing', 'behaviour'],
  clock_prescaler: ['timing', 'behaviour'],
  spi: ['timing', 'behaviour'],
  analog_comparator: ['timing', 'behaviour'],
  usb_endpoint_data: ['timing', 'behaviour'],
  usb_endpoint: ['timing', 'behaviour'],
  spm_instruction: ['timing', 'behaviour'],
  spm_interrupt: ['timing', 'behaviour'],
  self_programming: ['timing', 'behaviour'],
  clock_source: ['timing', 'behaviour'],
  timer_prescaler_sync: ['timing', 'behaviour'],
  usart1_flow_control: ['timing', 'behaviour'],
  twi_slave: ['timing', 'behaviour'],
  adc_input: ['timing', 'behaviour'],
  reserved_register: ['timing', 'behaviour'],
  lis3mdl_data: ['timing', 'behaviour'],
  lsm6ds33_data: ['timing', 'behaviour'],
  bootloader_session: ['timing'],
  digital_input_disable: ['behaviour'],
  adc_clock: ['behaviour'],
  on_chip_debug: [],
  pll_frequency: [],
  rc_oscillator: [],
}); // prettier-ignore

/** What a reported feature changes (FEATURE_EFFECTS); a sensor setting changes the values. */
export function effectsOf(feature) {
  if (feature.startsWith('lsm6ds33:') || feature.startsWith('lis3mdl:')) return ['behaviour'];
  return FEATURE_EFFECTS[feature] ?? ['timing', 'behaviour'];
}

/** The features whose use makes timing not evaluable. */
export const UNMODELLED_FEATURES = Object.freeze(
  Object.keys(FEATURE_EFFECTS).filter((name) => FEATURE_EFFECTS[name].includes('timing')),
);

/** Timer4 clocked (TCCR4B CS4) with an interrupt enabled (TIMSK4) or a compare output connected
 * (COM4A/B in TCCR4A, COM4D or the COM4A/B shadow bits in TCCR4C): a use of it. */
const timer4Used = (chip) => {
  const { data } = chip.cpu;
  return (
    !!(data[REG.TCCR4B] & 0x0f) &&
    !!(data[REG.TIMSK4] & 0xe4 || data[REG.TCCR4A] & 0xf0 || data[REG.TCCR4C] & 0xfc)
  );
};

const modelled = (by, extra = {}) => ({ outcome: 'modelled', by, ...extra });
const reported = (feature, extra = {}) => ({ outcome: 'reported', feature, ...extra });
const ends = (cause, extra = {}) => ({ outcome: 'ends', cause, ...extra });
const always = (feature) => () => [feature];
const writes = (mask, feature) => (value) => (value & mask ? [feature] : []);

const table = {};
const put = (address, name, entry) => {
  table[address] = { name, ...entry };
};
const each = (names, entry) => names.forEach(([address, name]) => put(address, name, entry));

each(
  [[0x23, 'PINB'], [0x24, 'DDRB'], [0x25, 'PORTB'], [0x26, 'PINC'], [0x27, 'DDRC'], [0x28, 'PORTC'],
   [0x29, 'PIND'], [0x2a, 'DDRD'], [0x2b, 'PORTD'], [0x2c, 'PINE'], [0x2d, 'DDRE'], [0x2e, 'PORTE'],
   [0x2f, 'PINF'], [0x30, 'DDRF'], [0x31, 'PORTF']],
  modelled('avr8js I/O port'),
); // prettier-ignore
each(
  [[0x35, 'TIFR0'], [0x36, 'TIFR1'], [0x38, 'TIFR3']],
  modelled('avr8js timer, its C compare flag and a zero written to a flag in completeTimer'),
); // prettier-ignore
each(
  [[0x3b, 'PCIFR'], [0x3c, 'EIFR'], [0x3d, 'EIMSK'], [0x68, 'PCICR'], [0x69, 'EICRA'],
   [0x6a, 'EICRB'], [0x6b, 'PCMSK0']],
  modelled('avr8js pin-change and external interrupts'),
); // prettier-ignore
each(
  [[0x3f, 'EECR'], [0x40, 'EEDR'], [0x41, 'EEARL'], [0x42, 'EEARH']],
  modelled('avr8js EEPROM, its programming operations counted'),
); // prettier-ignore
each(
  [[0x3e, 'GPIOR0'], [0x4a, 'GPIOR1'], [0x4b, 'GPIOR2']],
  modelled('storage', { why: 'a general purpose register: keeping what is written is all it does' }),
); // prettier-ignore
each(
  [[0x44, 'TCCR0A'], [0x45, 'TCCR0B'], [0x46, 'TCNT0'], [0x47, 'OCR0A'], [0x48, 'OCR0B'],
   [0x6e, 'TIMSK0']],
  modelled('avr8js timer'),
); // prettier-ignore
each(
  [[0x80, 'TCCR1A'], [0x81, 'TCCR1B'], [0x82, 'TCCR1C'], [0x84, 'TCNT1L'], [0x85, 'TCNT1H'],
   [0x86, 'ICR1L'], [0x87, 'ICR1H'], [0x88, 'OCR1AL'], [0x89, 'OCR1AH'], [0x8a, 'OCR1BL'],
   [0x8b, 'OCR1BH'], [0x8c, 'OCR1CL'], [0x8d, 'OCR1CH'], [0x90, 'TCCR3A'], [0x91, 'TCCR3B'],
   [0x92, 'TCCR3C'], [0x94, 'TCNT3L'], [0x95, 'TCNT3H'], [0x96, 'ICR3L'], [0x97, 'ICR3H'],
   [0x98, 'OCR3AL'], [0x99, 'OCR3AH'], [0x9a, 'OCR3BL'], [0x9b, 'OCR3BH'], [0x9c, 'OCR3CL'],
   [0x9d, 'OCR3CH']],
  modelled('avr8js 16-bit timer'),
); // prettier-ignore
each(
  [[0x6f, 'TIMSK1'], [0x71, 'TIMSK3']],
  modelled('avr8js timer', { uses: writes(0x20, 'input_capture') }),
); // prettier-ignore
each(
  [[0x78, 'ADCL'], [0x79, 'ADCH'], [0x7c, 'ADMUX']],
  modelled('avr8js ADC, an input without a model ending the evidence'),
); // prettier-ignore
put(0x7a, 'ADCSRA', modelled('avr8js ADC, guarded by the chip (adc_input, adc_clock)', {
  uses: (value) => ((value & 0xa0) === 0xa0 ? ['adc_auto_trigger'] : []),
})); // prettier-ignore
put(0x7b, 'ADCSRB', modelled('avr8js ADC: MUX5 guarded by the chip, ACME reported', {
  uses: writes(0x40, 'analog_comparator'),
})); // prettier-ignore
each(
  [[0x7d, 'DIDR2'], [0x7e, 'DIDR0'], [0x7f, 'DIDR1']],
  reported('digital_input_disable', { uses: writes(0xff, 'digital_input_disable') }),
); // prettier-ignore

// Timer4: reads of its count and flags are always a use (a count that does not count here); its
// other registers only when it is clocked with an interrupt or a connected output.
each([[0x39, 'TIFR4'], [0xbe, 'TCNT4'], [0xbf, 'TC4H']], reported('timer4', {
  on: 'access',
  uses: (value, access, chip) => (access === 'read' || timer4Used(chip) ? ['timer4'] : []),
})); // prettier-ignore
each(
  [[0x72, 'TIMSK4'], [0xc0, 'TCCR4A'], [0xc1, 'TCCR4B'], [0xc2, 'TCCR4C'], [0xc3, 'TCCR4D'],
   [0xc4, 'TCCR4E'], [0xcf, 'OCR4A'], [0xd0, 'OCR4B'], [0xd1, 'OCR4C'], [0xd2, 'OCR4D'],
   [0xd4, 'DT4']],
  reported('timer4', { uses: (value, access, chip) => (timer4Used(chip) ? ['timer4'] : []) }),
); // prettier-ignore

put(0x43, 'GTCCR', reported('timer_prescaler_sync', { uses: writes(0x81, 'timer_prescaler_sync') }));
put(0x49, 'PLLCSR', modelled('the chip\'s USB controller: PLOCK follows PLLE'));
put(0x4c, 'SPCR', reported('spi', { uses: writes(0x40, 'spi') }));
put(0x4d, 'SPSR', reported('spi', { on: 'read', uses: always('spi') }));
put(0x4e, 'SPDR', reported('spi', { on: 'access', uses: always('spi') }));
put(0x50, 'ACSR', reported('analog_comparator', {
  on: 'access',
  uses: (value, access) => (access === 'read' || value & 0x08 ? ['analog_comparator'] : []),
})); // prettier-ignore
put(0x51, 'MONDR', reported('on_chip_debug'));
put(0x52, 'PLLFRQ', reported('pll_frequency'));
put(0x53, 'SMCR', modelled('the rig\'s sleep: idle halts, any other mode ends the evidence'));
put(0x54, 'MCUSR', modelled('the chip\'s watchdog and reset flags'));
put(0x55, 'MCUCR', modelled('IVSEL and PUD reported, JTD without effect (JTAGEN is unprogrammed)', {
  uses: (value) => [...(value & 0x02 ? ['vector_relocation'] : []), ...(value & 0x10 ? ['pull_up_disable'] : [])],
})); // prettier-ignore
put(0x57, 'SPMCSR', reported('self_programming', {
  uses: (value) => [...(value & 0x80 ? ['spm_interrupt'] : []), ...(value & 0x01 ? ['self_programming'] : [])],
})); // prettier-ignore
each(
  [[0x5b, 'RAMPZ'], [0x5d, 'SPL'], [0x5e, 'SPH'], [0x5f, 'SREG']],
  modelled('avr8js CPU core'),
); // prettier-ignore
put(0x60, 'WDTCSR', modelled('the chip\'s watchdog'));
put(0x61, 'CLKPR', reported('clock_prescaler', {
  uses: (value, access, chip) => (chip.cpu.data[REG.CLKPR] & 0x0f ? ['clock_prescaler'] : []),
})); // prettier-ignore
// A module stopped by its power reduction bit: its registers can no longer be read or written
// ("Power Reduction Register"), which the rig does not model; the run's evidence ends.
const powerReduction = (register, bits) => ends('power_reduction', {
  silent: true,
  uses: (value) => (Object.keys(bits).some((bit) => value & Number(bit)) ? ['power_reduction'] : []),
  detail: (value) => ({
    register,
    value,
    modules: Object.entries(bits).filter(([bit]) => value & Number(bit)).map(([, module]) => module),
  }),
}); // prettier-ignore
put(0x64, 'PRR0', powerReduction('PRR0', { 0x80: 'twi', 0x20: 'timer0', 0x08: 'timer1', 0x04: 'spi', 0x01: 'adc' }));
put(0x65, 'PRR1', powerReduction('PRR1', { 0x80: 'usb', 0x10: 'timer4', 0x08: 'timer3', 0x01: 'usart1' }));
each([[0x66, 'OSCCAL'], [0x67, 'RCCTRL']], reported('rc_oscillator'));

put(0xb8, 'TWBR', modelled('the chip\'s TWI at its bit rate'));
put(0xb9, 'TWSR', modelled('the chip\'s TWI: status bits read-only'));
put(0xbb, 'TWDR', modelled('the chip\'s TWI'));
put(0xbc, 'TWCR', modelled('the chip\'s TWI as a master'));
// A slave: its address (TWAR, or its general-call bit) or its mask (TWAMR) is set. The rig has no
// master on the bus and raises no slave interrupt, so a firmware that listens would be shown a quiet
// bus. A master's own start-up clears TWAR (Arduino's Wire.begin() writes 0, address 0 without the
// general-call bit): that is not a use.
const slave = (name) => ({
  uses: (value) => (value ? ['twi_slave'] : []),
  detail: (value) => ({ register: name, value }),
});
put(0xba, 'TWAR', ends('twi_slave', slave('TWAR')));
put(0xbd, 'TWAMR', ends('twi_slave', slave('TWAMR')));
each([[0xc5, 'CLKSEL0'], [0xc6, 'CLKSEL1']], reported('clock_source'));
put(0xc7, 'CLKSTA', reported('clock_source', { on: 'read', uses: always('clock_source') }));
each(
  [[0xc8, 'UCSR1A'], [0xc9, 'UCSR1B'], [0xca, 'UCSR1C'], [0xcc, 'UBRR1L'], [0xcd, 'UBRR1H'],
   [0xce, 'UDR1']],
  modelled('avr8js USART; nothing sends to its receiver, as on an unconnected pin'),
); // prettier-ignore
put(0xcb, 'UCSR1D', reported('usart1_flow_control', { uses: writes(0x03, 'usart1_flow_control') }));

// USB, detached with no host (class Usb in mcu.js). UHWCON's bits (pad regulator, ID and VBUS
// pin control) matter only to a host connection; the endpoint registers matter only once a host
// has enumerated the device, which this rig does not have: their use is reported, not modelled.
put(0xd7, 'UHWCON', modelled('storage', {
  why: 'USB pad regulator, ID and VBUS pin control: observable only with a host',
})); // prettier-ignore
each(
  [[0xd8, 'USBCON'], [0xd9, 'USBSTA'], [0xda, 'USBINT'], [0xe0, 'UDCON'], [0xe1, 'UDINT'],
   [0xe2, 'UDIEN'], [0xe4, 'UDFNUML'], [0xe5, 'UDFNUMH']],
  modelled('the chip\'s USB controller with no host'),
); // prettier-ignore
each(
  [[0xe3, 'UDADDR'], [0xe6, 'UDMFN'], [0xe8, 'UEINTX'], [0xe9, 'UENUM'], [0xea, 'UERST'],
   [0xeb, 'UECONX'], [0xec, 'UECFG0X'], [0xed, 'UECFG1X'], [0xee, 'UESTA0X'], [0xef, 'UESTA1X'],
   [0xf0, 'UEIENX'], [0xf2, 'UEBCLX'], [0xf3, 'UEBCHX'], [0xf4, 'UEINT']],
  reported('usb_endpoint', { on: 'access', uses: always('usb_endpoint') }),
); // prettier-ignore
put(0xf1, 'UEDATX', reported('usb_endpoint_data', { on: 'access', uses: always('usb_endpoint_data') }));

// Whatever the summary calls Reserved, and anything past it: no entry means the evidence ends.
for (let address = 0x20; address < 0x100; address += 1) {
  table[address] ??= {
    name: 'Reserved',
    ...ends('reserved_register', { on: 'access', detail: (value, access) => ({ address, access }) }),
  };
}

/** The register map by data-space address (0x20 to 0xFF). */
export const REGISTER_OUTCOMES = Object.freeze(table);
