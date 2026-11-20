"""The simulated ATmega32U4 has the 32U4's vectors and registers, not the 328P's it was built from.

avr8js models the ATmega328P; the rig sets the 32U4 up from its parts, so every vector address
and register behaviour is the rig's own claim. Each is held here on the provisioned rig itself:
small programs written in machine code raise each interrupt the board model relies on and the
summary names the vector the CPU took; register rows write a register as firmware would and
read what the datasheet says follows (a zero written to a flag leaves it, the watchdog's timed
sequence, USB's level interrupt, the PLL's lock, the TWI's held flag and its abort).
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest
from avrsim_rig import environment

pytestmark = pytest.mark.integration

#: A program in words, run on the rig for some cycles; the summary's vectors back. `asm` holds
#: encoders for the few instructions the programs need.
PROGRAM = """
const src = %(src)s;
const { Rig, Trace } = await import(`${src}/rig.js`);
const { readScenario } = await import(`${src}/scenario.js`);
const asm = {
  ldi: (d, k) => [0xe000 | ((k & 0xf0) << 4) | ((d - 16) << 4) | (k & 0x0f)],
  sts: (k, r) => [0x9200 | (r << 4), k],
  jmp: (k) => [0x940c, k],
  inc: (d) => [0x9403 | (d << 4)],
  sei: () => [0x9478],
  reti: () => [0x9518],
  self: () => [0xcfff],
};
const words = new Uint16Array(0x4000);
let at = 0x56;                         // after the 43 two-word vectors
const handler = at;
for (const w of [...asm.inc(20), ...asm.reti()]) words[at++] = w;
for (let v = 2; v < 0x56; v += 2) words.set(asm.jmp(handler), v);
const main = at;
words.set(asm.jmp(main), 0);
const store = (address, value) => {
  for (const w of [...asm.ldi(16, value), ...asm.sts(address, 16)]) words[at++] = w;
};
%(setup)s
for (const w of [...asm.sei(), ...asm.self()]) words[at++] = w;
const flash = new Uint8Array(words.buffer);
const scenario = readScenario(JSON.stringify({ avrsim_scenario: 1, duration_s: %(seconds)s }));
const elf = { flash, eeprom: null, symbols: new Map() };
const rig = new Rig(elf, scenario, new Trace(() => {}, 1000));
const summary = rig.run();
const counts = Object.entries(summary.vectors).map(([k, v]) => [k, v.count]);
console.log(JSON.stringify(Object.fromEntries(counts)));
"""

#: A register row: `chip` is a fresh ATmega32U4, `REG` its addresses; `step(n)` runs n cycles of
#: clock events with no program.
REGISTERS = """
const src = %(src)s;
const mcu = await import(`${src}/mcu.js`);
const { REG } = mcu;
const bus = { start: () => true, stop() {}, connect: () => true, write: () => true, read: () => 0 };
const eeprom = new mcu.EEPROMMemoryBackend(1024);
const chip = new mcu.ATmega32U4(new Uint16Array(0x4000), { eeprom, bus });
const { cpu } = chip;
const step = (n) => {
  const end = cpu.cycles + n;
  while (cpu.cycles < end) { cpu.cycles += 1; cpu.tick(); }
};
// Whether the CPU, interrupts on, takes the vector at `address` now (and is put back).
const pending = (address) => {
  cpu.data[95] = 0x80; const pc = cpu.pc; cpu.tick();
  const taken = cpu.pc !== pc ? cpu.pc : null; cpu.pc = pc;
  return taken === address;
};
%(body)s
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


def _vectors(setup: str, seconds: float = 0.001) -> dict[str, int]:
    found = _node(PROGRAM % {"src": _src(), "setup": setup, "seconds": seconds})
    assert isinstance(found, dict)
    return found


def _registers(body: str) -> Any:
    return _node(REGISTERS % {"src": _src(), "body": body})


def test_each_external_interrupt_takes_its_own_vector() -> None:
    # Rising edges on INT0..INT3 (EICRA) and INT6 (EICRB's ISC61:60), driven as outputs.
    setup = """
    store(0x69, 0xff); store(0x6a, 0x30); store(0x3d, 0x4f);
    store(0x2a, 0x0f); store(0x2d, 0x40);
    store(0x2b, 0x0f); store(0x2e, 0x40);
    """
    found = _vectors(setup)
    assert {name: found.get(name) for name in ("INT0", "INT1", "INT2", "INT3", "INT6")} == {
        "INT0": 1,
        "INT1": 1,
        "INT2": 1,
        "INT3": 1,
        "INT6": 1,
    }


def test_a_pin_change_on_port_b_takes_pcint0() -> None:
    setup = "store(0x68, 0x01); store(0x6b, 0x01); store(0x24, 0x01); store(0x25, 0x01);"
    assert _vectors(setup).get("PCINT0") == 1


def test_timer1_s_third_compare_unit_and_timer3_s_overflow_take_their_vectors() -> None:
    # Normal mode from clk/1: OCR1C at 0x100 matches once and TCNT3 overflows once per 65536
    # cycles: matches at 256, 65792, 131328 and 196864, overflows at 65536, 131072, 196608.
    setup = """
    store(0x8d, 0x01); store(0x8c, 0x00); store(0x6f, 0x08); store(0x81, 0x01);
    store(0x71, 0x01); store(0x91, 0x01);
    """
    found = _vectors(setup, seconds=0.0125)  # 200,000 cycles
    assert found.get("TIMER1_COMPC") == 4
    assert found.get("TIMER3_OVF") == 3
    assert "TIMER1_COMPA" not in found and "TIMER1_OVF" not in found


def test_a_zero_written_to_a_flag_register_leaves_its_flags_and_a_one_clears_one() -> None:
    found = _registers(
        """
        cpu.data[REG.TIFR1] = 0x0f;
        cpu.writeData(REG.TIFR1, 0x00); const kept = cpu.data[REG.TIFR1];
        cpu.writeData(REG.TIFR1, 0x08); const one = cpu.data[REG.TIFR1];
        cpu.data[REG.MCUSR] = 0x0f;
        cpu.writeData(REG.MCUSR, 0x0f); const mcusrKept = cpu.data[REG.MCUSR];
        cpu.writeData(REG.MCUSR, 0x07); const mcusrCleared = cpu.data[REG.MCUSR];
        console.log(JSON.stringify({ kept, one, mcusrKept, mcusrCleared }));
        """
    )
    assert found == {"kept": 0x0F, "one": 0x07, "mcusrKept": 0x0F, "mcusrCleared": 0x07}


def test_the_watchdog_changes_only_through_its_timed_sequence_and_resets_on_time_out() -> None:
    found = _registers(
        """
        cpu.writeData(REG.WDTCSR, 0x08);                    // WDE may be set at any time
        const set = cpu.data[REG.WDTCSR];
        cpu.writeData(REG.WDTCSR, 0x00);                    // but not cleared outside the sequence
        const stillSet = cpu.data[REG.WDTCSR];
        cpu.writeData(REG.WDTCSR, 0x18); step(2); cpu.writeData(REG.WDTCSR, 0x00);
        const cleared = cpu.data[REG.WDTCSR];
        cpu.writeData(REG.WDTCSR, 0x18); step(6); cpu.writeData(REG.WDTCSR, 0x01);
        const late = cpu.data[REG.WDTCSR] & 0x27;           // too late to change the prescaler
        cpu.writeData(REG.WDTCSR, 0x18); cpu.writeData(REG.WDTCSR, 0x48);  // interrupt and reset
        step(256_000 - 10); const early = [chip.resetRequest, cpu.data[REG.WDTCSR] & 0x80];
        step(20);
        const flagged = !!(cpu.data[REG.WDTCSR] & 0x80);
        const first = [chip.resetRequest, flagged, pending(mcu.VECTORS.WDT)];
        chip.watchdog.vectored(); cpu.data[REG.WDTCSR] &= ~0x80;
        const wdie = cpu.data[REG.WDTCSR] & 0x40;
        step(256_000); const second = chip.resetRequest;
        console.log(JSON.stringify({ set, stillSet, cleared, late, early, first, wdie, second }));
        """
    )
    assert found == {
        "set": 0x08,
        "stillSet": 0x08,
        "cleared": 0x00,
        "late": 0x00,
        "early": [None, 0],
        "first": [None, True, True],
        "wdie": 0,
        "second": "watchdog",
    }


def test_after_a_watchdog_reset_its_flag_holds_the_watchdog_on_at_its_shortest_period() -> None:
    found = _registers(
        """
        const next = new mcu.ATmega32U4(new Uint16Array(0x4000), {
          eeprom: new mcu.EEPROMMemoryBackend(1024), bus, mcusr: mcu.MCUSR_WDRF, cycles: 1000 });
        const n = next.cpu;
        const at = [n.data[REG.MCUSR], n.data[REG.WDTCSR], n.cycles, n.pc];
        n.writeData(REG.WDTCSR, 0x18); n.writeData(REG.WDTCSR, 0x00);
        const whileFlagged = n.data[REG.WDTCSR];
        n.writeData(REG.MCUSR, 0x00);
        n.writeData(REG.WDTCSR, 0x18); n.writeData(REG.WDTCSR, 0x00);
        console.log(JSON.stringify({ at, whileFlagged, after: n.data[REG.WDTCSR] }));
        """
    )
    assert found == {"at": [0x08, 0x08, 1000, 0], "whileFlagged": 0x08, "after": 0x00}


def test_usb_with_no_host_locks_its_pll_and_raises_a_level_interrupt_from_udint_and_udien() -> None:
    found = _registers(
        """
        const reset = [cpu.data[REG.USBCON], cpu.data[REG.UDCON], cpu.data[REG.USBSTA]];
        cpu.writeData(REG.PLLCSR, 0x12);
        step(1590); const early = cpu.data[REG.PLLCSR] & 0x01;
        step(20); const locked = cpu.data[REG.PLLCSR] & 0x01;
        cpu.writeData(REG.PLLCSR, 0x01); const unlocked = cpu.data[REG.PLLCSR] & 0x01;
        cpu.data[REG.UDINT] = 0x04;
        cpu.writeData(REG.UDIEN, 0x04); const raised = pending(mcu.VECTORS.USB_GEN);
        const again = pending(mcu.VECTORS.USB_GEN);          // a level: still pending
        cpu.writeData(REG.UDINT, 0xff); const kept = cpu.data[REG.UDINT];
        cpu.writeData(REG.UDINT, 0xfb);
        const cleared = [cpu.data[REG.UDINT], pending(mcu.VECTORS.USB_GEN)];
        const found = { reset, early, locked, unlocked, raised, again, kept, cleared };
        console.log(JSON.stringify(found));
        """
    )
    assert found == {
        "reset": [0x20, 0x01, 0x00],
        "early": 0,
        "locked": 1,
        "unlocked": 0,
        "raised": True,
        "again": True,
        "kept": 0x04,
        "cleared": [0x00, False],
    }


def test_the_twi_flag_is_cleared_only_by_a_one_and_disabling_the_interface_ends_a_start() -> None:
    found = _registers(
        """
        chip.twi.bus = { ...bus, start: () => false };       // SDA held: no START completes
        cpu.writeData(REG.TWBR, 72);                          // 100 kHz
        cpu.writeData(REG.TWCR, 0xa4);                        // TWINT | TWSTA | TWEN
        step(200 * 160);
        const stuck = [chip.twi.busy, cpu.data[REG.TWCR] & 0x80, cpu.data[REG.TWSR] & 0xf8];
        cpu.writeData(REG.TWCR, 0x00); const freed = [chip.twi.busy, cpu.data[REG.TWSR] & 0xf8];
        chip.twi.bus = bus;
        cpu.writeData(REG.TWCR, 0xa4); step(159); const before = cpu.data[REG.TWCR] & 0x80;
        step(2); const started = [cpu.data[REG.TWCR] & 0x80, cpu.data[REG.TWSR] & 0xf8];
        cpu.writeData(REG.TWCR, 0x04); const kept = cpu.data[REG.TWCR] & 0x80;
        cpu.writeData(REG.TWCR, 0x94); step(161);   // STOP: TWSTO clears, TWINT stays clear
        const stopped = [cpu.data[REG.TWCR] & 0x90, cpu.data[REG.TWSR] & 0xf8];
        console.log(JSON.stringify({ stuck, freed, before, started, kept, stopped }));
        """
    )
    assert found == {
        "stuck": [True, 0, 0xF8],
        "freed": [False, 0xF8],
        "before": 0,
        "started": [0x80, 0x08],
        "kept": 0x80,
        "stopped": [0x00, 0xF8],
    }


def test_the_watchdog_in_interrupt_mode_interrupts_every_period_and_never_resets() -> None:
    # WDIE alone, WDP = 0: every 2K cycles of the 128 kHz oscillator, 256,000 CPU cycles.
    setup = "store(0x60, 0x40);"
    found = _vectors(setup, seconds=0.1)  # 1,600,000 cycles: six time-outs
    assert found.get("WDT") == 6
