"""Every register of the ATmega32U4's summary is modelled, reported or ends the evidence.

avr8js leaves any register it has no peripheral for as plain memory, and the rig's default for
what it was never told about must not be to give such a register's plain memory as the part's
behaviour. The table below is the datasheet's register summary (Atmel-7766, "Register
Summary": the I/O and the extended I/O space, 0x20 to 0xFF), written out independently of the
rig, with for each register one of three outcomes:

- modelled: a model acts on it (an avr8js peripheral the rig configures, the rig's own watchdog,
  USB, TWI, ADC or sleep code), or it is storage whose only behaviour is to keep what is written;
- reported: a use the rig does not model is named in the summary's ``unmodelled`` (and gates what
  it changes);
- ends the evidence: the run's evidence stops at the use (a reserved address, a module stopped
  by its power reduction bit, a TWI slave, an ADC input nothing is attached to).

A register that does none of the three is a defect, and the first row names each one.
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

import pytest
from avrsim_rig import environment

pytestmark = pytest.mark.integration

#: The register summary's named registers by data-space address (the datasheet's second column
#: names the I/O address; the first, in brackets, is this one). Every other address from 0x20
#: to 0xFF is "Reserved" there.
SUMMARY: list[tuple[int, str]] = [
    (0x23, "PINB"),
    (0x24, "DDRB"),
    (0x25, "PORTB"),
    (0x26, "PINC"),
    (0x27, "DDRC"),
    (0x28, "PORTC"),
    (0x29, "PIND"),
    (0x2A, "DDRD"),
    (0x2B, "PORTD"),
    (0x2C, "PINE"),
    (0x2D, "DDRE"),
    (0x2E, "PORTE"),
    (0x2F, "PINF"),
    (0x30, "DDRF"),
    (0x31, "PORTF"),
    (0x35, "TIFR0"),
    (0x36, "TIFR1"),
    (0x38, "TIFR3"),
    (0x39, "TIFR4"),
    (0x3B, "PCIFR"),
    (0x3C, "EIFR"),
    (0x3D, "EIMSK"),
    (0x3E, "GPIOR0"),
    (0x3F, "EECR"),
    (0x40, "EEDR"),
    (0x41, "EEARL"),
    (0x42, "EEARH"),
    (0x43, "GTCCR"),
    (0x44, "TCCR0A"),
    (0x45, "TCCR0B"),
    (0x46, "TCNT0"),
    (0x47, "OCR0A"),
    (0x48, "OCR0B"),
    (0x49, "PLLCSR"),
    (0x4A, "GPIOR1"),
    (0x4B, "GPIOR2"),
    (0x4C, "SPCR"),
    (0x4D, "SPSR"),
    (0x4E, "SPDR"),
    (0x50, "ACSR"),
    (0x51, "MONDR"),
    (0x52, "PLLFRQ"),
    (0x53, "SMCR"),
    (0x54, "MCUSR"),
    (0x55, "MCUCR"),
    (0x57, "SPMCSR"),
    (0x5B, "RAMPZ"),
    (0x5D, "SPL"),
    (0x5E, "SPH"),
    (0x5F, "SREG"),
    (0x60, "WDTCSR"),
    (0x61, "CLKPR"),
    (0x64, "PRR0"),
    (0x65, "PRR1"),
    (0x66, "OSCCAL"),
    (0x67, "RCCTRL"),
    (0x68, "PCICR"),
    (0x69, "EICRA"),
    (0x6A, "EICRB"),
    (0x6B, "PCMSK0"),
    (0x6E, "TIMSK0"),
    (0x6F, "TIMSK1"),
    (0x71, "TIMSK3"),
    (0x72, "TIMSK4"),
    (0x78, "ADCL"),
    (0x79, "ADCH"),
    (0x7A, "ADCSRA"),
    (0x7B, "ADCSRB"),
    (0x7C, "ADMUX"),
    (0x7D, "DIDR2"),
    (0x7E, "DIDR0"),
    (0x7F, "DIDR1"),
    (0x80, "TCCR1A"),
    (0x81, "TCCR1B"),
    (0x82, "TCCR1C"),
    (0x84, "TCNT1L"),
    (0x85, "TCNT1H"),
    (0x86, "ICR1L"),
    (0x87, "ICR1H"),
    (0x88, "OCR1AL"),
    (0x89, "OCR1AH"),
    (0x8A, "OCR1BL"),
    (0x8B, "OCR1BH"),
    (0x8C, "OCR1CL"),
    (0x8D, "OCR1CH"),
    (0x90, "TCCR3A"),
    (0x91, "TCCR3B"),
    (0x92, "TCCR3C"),
    (0x94, "TCNT3L"),
    (0x95, "TCNT3H"),
    (0x96, "ICR3L"),
    (0x97, "ICR3H"),
    (0x98, "OCR3AL"),
    (0x99, "OCR3AH"),
    (0x9A, "OCR3BL"),
    (0x9B, "OCR3BH"),
    (0x9C, "OCR3CL"),
    (0x9D, "OCR3CH"),
    (0xB8, "TWBR"),
    (0xB9, "TWSR"),
    (0xBA, "TWAR"),
    (0xBB, "TWDR"),
    (0xBC, "TWCR"),
    (0xBD, "TWAMR"),
    (0xBE, "TCNT4"),
    (0xBF, "TC4H"),
    (0xC0, "TCCR4A"),
    (0xC1, "TCCR4B"),
    (0xC2, "TCCR4C"),
    (0xC3, "TCCR4D"),
    (0xC4, "TCCR4E"),
    (0xC5, "CLKSEL0"),
    (0xC6, "CLKSEL1"),
    (0xC7, "CLKSTA"),
    (0xC8, "UCSR1A"),
    (0xC9, "UCSR1B"),
    (0xCA, "UCSR1C"),
    (0xCB, "UCSR1D"),
    (0xCC, "UBRR1L"),
    (0xCD, "UBRR1H"),
    (0xCE, "UDR1"),
    (0xCF, "OCR4A"),
    (0xD0, "OCR4B"),
    (0xD1, "OCR4C"),
    (0xD2, "OCR4D"),
    (0xD4, "DT4"),
    (0xD7, "UHWCON"),
    (0xD8, "USBCON"),
    (0xD9, "USBSTA"),
    (0xDA, "USBINT"),
    (0xE0, "UDCON"),
    (0xE1, "UDINT"),
    (0xE2, "UDIEN"),
    (0xE3, "UDADDR"),
    (0xE4, "UDFNUML"),
    (0xE5, "UDFNUMH"),
    (0xE6, "UDMFN"),
    (0xE8, "UEINTX"),
    (0xE9, "UENUM"),
    (0xEA, "UERST"),
    (0xEB, "UECONX"),
    (0xEC, "UECFG0X"),
    (0xED, "UECFG1X"),
    (0xEE, "UESTA0X"),
    (0xEF, "UESTA1X"),
    (0xF0, "UEIENX"),
    (0xF1, "UEDATX"),
    (0xF2, "UEBCLX"),
    (0xF3, "UEBCHX"),
    (0xF4, "UEINT"),
]
ADDRESS = dict(SUMMARY)
BY_NAME = {name: address for address, name in SUMMARY}

#: Timer4 clocked with a compare output connected: a use, and every register that configures it
#: is then one the rig does not model.
TIMER4_USED = "w(0xc1, 0x01); w(0xc0, 0x40);"

Spec = tuple[str, ...]


def modelled(how: str, why: str) -> Spec:
    return ("modelled", how, why)


def reported(feature: str, op: str, setup: str = "") -> Spec:
    return ("reported", feature, op, setup)


def ends(cause: str, op: str, setup: str = "") -> Spec:
    return ("ends", cause, op, setup)


#: What each named register is, by its name. ``hook``: a model's own access hook sits on it;
#: ``ref``: the rig's model code reads or writes it by name (checked in the sources);
#: ``storage``: it keeps what is written, which is all it does without a host; ``core``: avr8js's
#: CPU core uses it.
_HOOKED = "hook"
OUTCOMES: dict[str, Spec] = {
    **{
        name: modelled(_HOOKED, "avr8js I/O port")
        for name in ("PINB", "DDRB", "PORTB", "PINC", "DDRC", "PORTC", "PIND", "DDRD", "PORTD")
    },
    **{name: modelled(_HOOKED, "avr8js I/O port") for name in ("PINE", "DDRE", "PORTE")},
    **{name: modelled(_HOOKED, "avr8js I/O port") for name in ("PINF", "DDRF", "PORTF")},
    **{name: modelled(_HOOKED, "avr8js timer") for name in ("TIFR0", "TIFR1", "TIFR3")},
    **{name: modelled(_HOOKED, "avr8js timer") for name in ("TCCR0A", "TCCR0B", "TCNT0")},
    **{name: modelled(_HOOKED, "avr8js timer") for name in ("OCR0A", "OCR0B")},
    **{
        name: modelled(_HOOKED, "avr8js timer")
        for name in ("TIMSK0", "TIMSK1", "TIMSK3", "TCCR1A", "TCCR1B", "TCCR1C", "TCCR3A")
    },
    **{
        name: modelled(_HOOKED, "avr8js timer")
        for name in ("TCCR3B", "TCCR3C", "TCNT1L", "TCNT1H", "ICR1L", "ICR1H", "TCNT3L")
    },
    **{
        name: modelled(_HOOKED, "avr8js timer")
        for name in ("OCR1AL", "OCR1AH", "OCR1BL", "OCR1BH", "OCR1CL", "OCR1CH", "TCNT3H")
    },
    **{
        name: modelled(_HOOKED, "avr8js timer")
        for name in ("ICR3L", "ICR3H", "OCR3AL", "OCR3AH", "OCR3BL", "OCR3BH", "OCR3CL", "OCR3CH")
    },
    **{name: modelled(_HOOKED, "avr8js pin and external interrupts") for name in ("PCIFR", "EIFR")},
    **{name: modelled(_HOOKED, "avr8js pin and external interrupts") for name in ("EIMSK",)},
    **{
        name: modelled(_HOOKED, "avr8js pin and external interrupts")
        for name in ("EICRA", "EICRB", "PCMSK0")
    },
    "PCICR": modelled("ref", "avr8js pin-change interrupt, configured in mcu.js"),
    "EECR": modelled(_HOOKED, "avr8js EEPROM"),
    "EEDR": modelled("ref", "avr8js EEPROM, configured in mcu.js"),
    "EEARL": modelled("ref", "avr8js EEPROM, configured in mcu.js"),
    "EEARH": modelled("ref", "avr8js EEPROM, configured in mcu.js"),
    "PLLCSR": modelled(_HOOKED, "the rig's USB controller: the PLL's lock"),
    "MCUSR": modelled(_HOOKED, "the rig's watchdog and reset flags"),
    "MCUCR": modelled(_HOOKED, "the rig: IVSEL and PUD reported, JTD without effect"),
    "WDTCSR": modelled(_HOOKED, "the rig's watchdog"),
    "SMCR": modelled("ref", "the rig's sleep: idle halts, any other mode ends the evidence"),
    "ADCSRA": modelled(_HOOKED, "avr8js ADC, guarded by the rig"),
    "ADCL": modelled("ref", "avr8js ADC, configured in mcu.js"),
    "ADCH": modelled("ref", "avr8js ADC, configured in mcu.js"),
    "ADCSRB": modelled("ref", "avr8js ADC, configured in mcu.js, MUX5 guarded by the rig"),
    "ADMUX": modelled("ref", "avr8js ADC, configured in mcu.js"),
    "TWBR": modelled("ref", "the rig's TWI at its bit rate"),
    "TWSR": modelled(_HOOKED, "the rig's TWI"),
    "TWDR": modelled("ref", "the rig's TWI"),
    "TWCR": modelled(_HOOKED, "the rig's TWI"),
    **{
        name: modelled(_HOOKED, "avr8js USART")
        for name in ("UCSR1A", "UCSR1B", "UCSR1C", "UBRR1L", "UBRR1H", "UDR1")
    },
    "USBCON": modelled("ref", "the rig's USB controller with no host"),
    "USBSTA": modelled(_HOOKED, "the rig's USB controller with no host"),
    "USBINT": modelled(_HOOKED, "the rig's USB controller: no VBUS, so its flag never sets"),
    "UDCON": modelled("ref", "the rig's USB controller with no host: DETACH"),
    "UDINT": modelled(_HOOKED, "the rig's USB controller with no host"),
    "UDIEN": modelled(_HOOKED, "the rig's USB controller with no host"),
    "UDFNUML": modelled("ref", "the rig's USB controller: the frame number"),
    "UDFNUMH": modelled("ref", "the rig's USB controller: the frame number"),
    "UHWCON": modelled(
        "storage", "USB pad regulator, ID and VBUS pin control: observable only with a host"
    ),
    **{
        name: modelled(
            "storage", "a general purpose register: keeping what is written is all it does"
        )
        for name in ("GPIOR0", "GPIOR1", "GPIOR2")
    },
    **{name: modelled("core", "avr8js's CPU core") for name in ("RAMPZ", "SPL", "SPH", "SREG")},
    # Reported.
    "TIFR4": reported("timer4", "r(0x39)"),
    "TCNT4": reported("timer4", "r(0xbe)"),
    "TC4H": reported("timer4", "r(0xbf)"),
    "TIMSK4": reported("timer4", "w(0x72, 0x04)", "w(0xc1, 0x01);"),
    "TCCR4A": reported("timer4", "w(0xc0, 0x40)", "w(0xc1, 0x01);"),
    "TCCR4B": reported("timer4", "w(0xc1, 0x01)", "w(0xc0, 0x40);"),
    "TCCR4C": reported("timer4", "w(0xc2, 0x04)", "w(0xc1, 0x01);"),
    "TCCR4D": reported("timer4", "w(0xc3, 0x01)", TIMER4_USED),
    "TCCR4E": reported("timer4", "w(0xc4, 0x01)", TIMER4_USED),
    "OCR4A": reported("timer4", "w(0xcf, 0x10)", TIMER4_USED),
    "OCR4B": reported("timer4", "w(0xd0, 0x10)", TIMER4_USED),
    "OCR4C": reported("timer4", "w(0xd1, 0x10)", TIMER4_USED),
    "OCR4D": reported("timer4", "w(0xd2, 0x10)", TIMER4_USED),
    "DT4": reported("timer4", "w(0xd4, 0x11)", TIMER4_USED),
    "GTCCR": reported("timer_prescaler_sync", "w(0x43, 0x81)"),
    "SPCR": reported("spi", "w(0x4c, 0x40)"),
    "SPSR": reported("spi", "r(0x4d)"),
    "SPDR": reported("spi", "w(0x4e, 0x01)"),
    "ACSR": reported("analog_comparator", "r(0x50)"),
    "MONDR": reported("on_chip_debug", "w(0x51, 0x01)"),
    "PLLFRQ": reported("pll_frequency", "w(0x52, 0x40)"),
    "SPMCSR": reported("self_programming", "w(0x57, 0x01)"),
    "CLKPR": reported("clock_prescaler", "w(0x61, 0x03)"),
    "OSCCAL": reported("rc_oscillator", "w(0x66, 0x01)"),
    "RCCTRL": reported("rc_oscillator", "w(0x67, 0x01)"),
    "DIDR2": reported("digital_input_disable", "w(0x7d, 0x01)"),
    "DIDR0": reported("digital_input_disable", "w(0x7e, 0x01)"),
    "DIDR1": reported("digital_input_disable", "w(0x7f, 0x01)"),
    "CLKSEL0": reported("clock_source", "w(0xc5, 0x04)"),
    "CLKSEL1": reported("clock_source", "w(0xc6, 0x04)"),
    "CLKSTA": reported("clock_source", "r(0xc7)"),
    "UCSR1D": reported("usart1_flow_control", "w(0xcb, 0x03)"),
    "UDADDR": reported("usb_endpoint", "w(0xe3, 0x85)"),
    "UDMFN": reported("usb_endpoint", "r(0xe6)"),
    "UEINTX": reported("usb_endpoint", "r(0xe8)"),
    "UENUM": reported("usb_endpoint", "w(0xe9, 0x01)"),
    "UERST": reported("usb_endpoint", "w(0xea, 0x01)"),
    "UECONX": reported("usb_endpoint", "w(0xeb, 0x01)"),
    "UECFG0X": reported("usb_endpoint", "w(0xec, 0x01)"),
    "UECFG1X": reported("usb_endpoint", "w(0xed, 0x01)"),
    "UESTA0X": reported("usb_endpoint", "r(0xee)"),
    "UESTA1X": reported("usb_endpoint", "r(0xef)"),
    "UEIENX": reported("usb_endpoint", "w(0xf0, 0x01)"),
    "UEDATX": reported("usb_endpoint_data", "r(0xf1)"),
    "UEBCLX": reported("usb_endpoint", "r(0xf2)"),
    "UEBCHX": reported("usb_endpoint", "r(0xf3)"),
    "UEINT": reported("usb_endpoint", "r(0xf4)"),
    # Ends the evidence.
    "PRR0": ends("power_reduction", "w(0x64, 0x01)"),
    "PRR1": ends("power_reduction", "w(0x65, 0x01)"),
    "TWAR": ends("twi_slave", "w(0xba, 0x02)"),
    "TWAMR": ends("twi_slave", "w(0xbd, 0x01)"),
}

RESERVED = [a for a in range(0x20, 0x100) if a not in ADDRESS]
#: Where avr8js's own CPU core reads each register it owns (SPL and SPH are held by a row).
CORE_TOKEN = {"RAMPZ": "data[0x5b]", "SREG": "data[95]", "SPL": "data[93]", "SPH": "data[94]"}

#: One chip per stimulus, from reset: its setup, then its operation with what the chip said
#: before it forgotten; what it reported, what ended the evidence, and what a read gave.
OBSERVE = """
const src = %(src)s;
const mcu = await import(`${src}/mcu.js`);
const bus = { start: () => true, stop() {}, connect: () => true, write: () => true, read: () => 0 };
const fresh = () => {
  const seen = { reports: {}, ends: [] };
  const chip = new mcu.ATmega32U4(new Uint16Array(0x4000), {
    eeprom: new mcu.EEPROMMemoryBackend(1024), bus,
    onUnmodelled: (what) => { seen.reports[what] = (seen.reports[what] ?? 0) + 1; },
    onEvidenceEnd: (cause, detail) => seen.ends.push({ cause, ...detail }),
  });
  return { chip, seen };
};
const results = [];
for (const entry of %(entries)s) {
  const { chip, seen } = fresh();
  const { cpu } = chip;
  const w = (address, value) => cpu.writeData(address, value);
  const r = (address) => cpu.readData(address);
  const hooks = [!!cpu.writeHooks[entry.address], !!cpu.readHooks[entry.address]];
  const result = { id: entry.id, hooks };
  new Function('w', 'r', entry.setup)(w, r);
  seen.reports = {}; seen.ends = [];
  result.value = new Function('w', 'r', entry.op)(w, r) ?? null;
  result.reports = seen.reports; result.ends = seen.ends; result.sp = chip.sp;
  results.push(result);
}
console.log(JSON.stringify(results));
"""

FEATURES = """
const src = %(src)s;
const mcu = await import(`${src}/mcu.js`);
const features = new Set();
for (const entry of Object.values(mcu.REGISTER_OUTCOMES)) {
  if (entry.feature) features.add(entry.feature);
  if (entry.cause === 'twi_slave') features.add('twi_slave');
}
// Every name a register's `uses` can give, for each value and for a read and a write, with the
// chip's data space all clear and all set (the registers' uses read the chip's other registers).
const used = new Set();
for (const entry of Object.values(mcu.REGISTER_OUTCOMES)) {
  if (!entry.uses || entry.silent) continue; // a silent end names no feature
  for (const fill of [0x00, 0xff]) {
    const chip = { cpu: { data: new Uint8Array(0x10000).fill(fill) } };
    for (const access of ['read', 'write']) {
      for (let value = 0; value < 256; value += 1) {
        for (const name of entry.uses(value, access, chip)) used.add(name);
      }
    }
  }
}
console.log(JSON.stringify({
  features: [...features].sort(), used: [...used].sort(), effects: mcu.FEATURE_EFFECTS,
  unlisted: mcu.effectsOf('a_feature_nobody_listed'),
  sensor: [mcu.effectsOf('lsm6ds33:CTRL7_G'), mcu.effectsOf('lis3mdl:CTRL_REG1')],
}));
"""

OUTCOME_TABLE = """
const src = %(src)s;
const mcu = await import(`${src}/mcu.js`);
console.log(JSON.stringify(mcu.REGISTER_OUTCOMES));
"""


def _node(script: str) -> Any:
    env = environment()
    done = subprocess.run(
        [str(env / "node" / "bin" / "node"), "--input-type=module", "-"],
        input=script,
        cwd="/",
        env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def _src() -> str:
    return json.dumps((environment() / "avrsim" / "src").as_uri())


def _observe(entries: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    found = _node(OBSERVE % {"src": _src(), "entries": json.dumps(entries)})
    return {item["id"]: item for item in found}


def _stimuli() -> list[dict[str, Any]]:
    """Every register's stimulus: a name, its address, a setup and the operation under test."""
    entries: list[dict[str, Any]] = []
    for name, spec in OUTCOMES.items():
        address = BY_NAME[name]
        entry: dict[str, Any] = {"id": name, "address": address, "setup": "", "op": ""}
        if spec[0] == "modelled":
            entry["op"] = "return null;"
            if spec[1] == "storage":
                entry["op"] = f"w({address}, 0xa5); return r({address});"
            if spec[1] == "core" and name in ("SPL", "SPH"):
                entry["op"] = f"w({address}, 0x5a); return r({address});"
        else:
            entry["setup"] = spec[3]
            entry["op"] = spec[2]
        entries.append(entry)
    for address in RESERVED:
        entries.append(
            {
                "id": f"R{address:02X}w",
                "address": address,
                "setup": "",
                "op": f"w({address}, 0x01);",
            }
        )
        entries.append(
            {"id": f"R{address:02X}r", "address": address, "setup": "", "op": f"r({address});"}
        )
    return entries


def _sources() -> str:
    """The rig's own model code: everything but the table of outcomes itself."""
    rig = environment() / "avrsim" / "src"
    return "\n".join(
        (rig / name).read_text(encoding="utf-8") for name in ("mcu.js", "rig.js", "board.js")
    )


def _core() -> str:
    cpu = environment() / "avrsim" / "node_modules" / "avr8js" / "dist" / "esm" / "cpu"
    return "\n".join(
        (cpu / name).read_text(encoding="utf-8") for name in ("cpu.js", "instruction.js")
    )


def test_the_summary_is_the_datasheet_s_register_summary_with_every_other_address_reserved() -> (
    None
):
    # 150 named registers; the 74 other addresses of 0x20..0xFF are "Reserved" in the datasheet.
    assert len(SUMMARY) == 150 and len(RESERVED) == 74
    assert len(ADDRESS) == len(SUMMARY) and set(OUTCOMES) == set(BY_NAME)
    assert len(OUTCOMES) == 150


def test_each_register_is_modelled_reported_or_ends_the_evidence_and_none_falls_through() -> None:
    observed = _observe(_stimuli())
    sources, core = _sources(), _core()
    failing: list[str] = []
    for name, spec in OUTCOMES.items():
        seen = observed[name]
        address = BY_NAME[name]
        if spec[0] == "reported":
            if spec[1] not in seen["reports"]:
                failing.append(f"{name} {address:#04x}: {spec[2]} reported {seen['reports']}")
        elif spec[0] == "ends":
            if spec[1] not in {e["cause"] for e in seen["ends"]}:
                failing.append(f"{name} {address:#04x}: {spec[2]} ended {seen['ends']}")
        elif spec[1] == _HOOKED:
            if not any(seen["hooks"]):
                failing.append(f"{name} {address:#04x}: no model's hook sits on it")
        elif spec[1] == "ref":
            if not re.search(rf"\bREG\.{name}\b", sources):
                failing.append(f"{name} {address:#04x}: no model code names it")
        elif spec[1] == "storage":
            if seen["value"] != 0xA5 or seen["reports"] or seen["ends"]:
                failing.append(f"{name} {address:#04x}: does not keep what is written ({seen})")
        elif name in ("SPL", "SPH"):
            if seen["value"] != 0x5A:
                failing.append(f"{name}: the stack pointer does not keep what is written")
        elif CORE_TOKEN[name] not in core:
            failing.append(f"{name} {address:#04x}: avr8js's core does not use it")
    assert not failing, "\n" + "\n".join(failing)


def test_a_reserved_address_ends_the_evidence_on_a_read_and_on_a_write() -> None:
    observed = _observe(_stimuli())
    failing = []
    for address in RESERVED:
        for suffix in ("w", "r"):
            seen = observed[f"R{address:02X}{suffix}"]
            causes = {e["cause"] for e in seen["ends"]}
            if causes != {"reserved_register"} or any(
                e["address"] != address for e in seen["ends"]
            ):
                failing.append(f"{address:#04x} {suffix}: ended {seen['ends']}")
    assert not failing, "\n" + "\n".join(failing[:20])


def test_the_rig_s_own_table_of_outcomes_agrees_with_the_datasheet_s_summary() -> None:
    table = _node(OUTCOME_TABLE % {"src": _src()})
    assert sorted(int(a) for a in table) == list(range(0x20, 0x100))
    wrong: list[tuple[int, Any, Any]] = []
    for address in range(0x20, 0x100):
        entry = table[str(address)]
        if address in ADDRESS:
            spec = OUTCOMES[ADDRESS[address]]
            named = (entry["name"], entry["outcome"]) == (ADDRESS[address], spec[0])
            what = (entry.get("feature"), entry.get("cause"))
            if not named or (spec[0] in ("reported", "ends") and spec[1] not in what):
                wrong.append((address, entry, spec))
        elif (entry["name"], entry["outcome"], entry.get("cause")) != (
            "Reserved",
            "ends",
            "reserved_register",
        ):
            wrong.append((address, entry, "reserved"))
    assert not wrong, wrong[:10]


def test_the_rig_s_table_gives_every_reported_feature_its_effect_on_what_is_evaluable() -> None:
    # A reported use changes what the summary can claim: of time, of values, or (named, with
    # the reason in the table) of neither.
    found = _node(FEATURES % {"src": _src()})
    missing = [f for f in found["features"] if f not in found["effects"]]
    assert not missing, missing
    # Nor does a name the table's `uses` gives, or one the model reports in code (the guards of
    # the ADC, the PLL and memory, the rig's own notes, the sensors), rest on the default
    # `effectsOf` falls back to: each has its own entry. Sensor settings (`lsm6ds33:CTRL7_G`)
    # are named by register and change the values only.
    rig = environment() / "avrsim" / "src"
    code = "\n".join(
        (rig / name).read_text(encoding="utf-8")
        for name in ("mcu.js", "rig.js", "board.js", "imu.js")
    )
    named = set(re.findall(r"\b(?:report|noteUnmodelled|onUnmodelled)\('(\w+)'\)", code))
    assert {"adc_input", "adc_clock", "pll_configuration", "unmapped_memory"} <= named
    assert {"bootloader_session", "spm_instruction", "lsm6ds33_data", "lis3mdl_data"} <= named
    assert {"timer4", "twi_slave", "spm_interrupt", "vector_relocation"} <= set(found["used"])
    unlisted = sorted((named | set(found["used"])) - set(found["effects"]))
    assert not unlisted, unlisted
    # What no table lists is taken to change both, and a sensor setting only the values.
    assert found["unlisted"] == ["timing", "behaviour"]
    assert found["sensor"] == [["behaviour"], ["behaviour"]]
    # No effect is only for a use whose register the board's crystal clock makes inert.
    inert = sorted(f for f, effect in found["effects"].items() if not effect)
    assert inert == ["on_chip_debug", "pll_frequency", "rc_oscillator"]
