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
import re
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
const scenario = readScenario(JSON.stringify({
  avrsim_scenario: 1, duration_s: %(seconds)s, ...%(more)s }));
const elf = { flash, eeprom: null, symbols: new Map() };
const rig = new Rig(elf, scenario, new Trace(() => {}, 1000));
const s = rig.run();
console.log(JSON.stringify({ vectors: s.vectors, resets: s.resets, pwm: s.pwm, motors: s.motors }));
"""

#: A program of calls, its own words given in `%(body)s` from the word address `at` on, probed
#: as the ELF's functions `%(symbols)s` names; the summary's probes and stack back.
CALLS = """
const src = %(src)s;
const { Rig, Trace } = await import(`${src}/rig.js`);
const { readScenario } = await import(`${src}/scenario.js`);
const asm = {
  call: (k) => [0x940e, k], jmp: (k) => [0x940c, k], ret: () => [0x9508], nop: () => [0x0000],
};
const words = new Uint16Array(0x4000);
const at = 0x56;
%(body)s
const flash = new Uint8Array(words.buffer);
const symbols = new Map(Object.entries(%(symbols)s).map(
  ([name, word]) => [name, { type: 'function', value: word * 2 }]));
const scenario = readScenario(JSON.stringify(%(scenario)s));
const rig = new Rig({ flash, eeprom: null, symbols }, scenario, new Trace(() => {}, 1000));
const s = rig.run();
console.log(JSON.stringify({ probes: s.probes, stack: s.stack }));
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


#: The handler every vector of PROGRAM jumps to, unless a row gives its own words.
HANDLER = "[...asm.inc(20), ...asm.reti()]"


def _program(
    setup: str, seconds: float = 0.001, handler: str = HANDLER, **more: Any
) -> dict[str, Any]:
    program = PROGRAM.replace(HANDLER, handler)
    found = _node(
        program % {"src": _src(), "setup": setup, "seconds": seconds, "more": json.dumps(more)}
    )
    assert isinstance(found, dict)
    return found


def _vectors(setup: str, seconds: float = 0.001) -> dict[str, int]:
    return {name: v["count"] for name, v in _program(setup, seconds)["vectors"].items()}


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


def _header() -> tuple[dict[str, int], dict[str, int], int]:
    """The device headers the provisioned avr-gcc builds against: registers, vectors, table size.

    iom32u4.h names the part's registers (a 16-bit one by its low byte's address); common.h the
    stack pointer and SREG, at their I/O addresses for a part like this one.
    """
    include = environment() / "platformio" / "packages" / "toolchain-atmelavr" / "avr" / "include"
    text = (include / "avr" / "iom32u4.h").read_text(encoding="utf-8")
    common = (include / "avr" / "common.h").read_text(encoding="utf-8")
    registers = {
        name: int(address, 16) + (0x20 if kind == "IO" else 0)
        for name, kind, address in re.findall(
            r"^#define (\w+)\s+_SFR_(IO|MEM)(?:8|16)\((0x[0-9A-Fa-f]+)\)", text, re.MULTILINE
        )
    }
    for name in ("SPL", "SPH", "SREG"):
        address = re.search(
            rf"^#\s*define {name} _SFR_IO8\((0x[0-9A-Fa-f]+)\)", common, re.MULTILINE
        )
        assert address is not None, name
        registers[name] = int(address.group(1), 16) + 0x20
    vectors = {
        name: int(number)
        for name, number in re.findall(r"^#define (\w+)_vect_num\s+(\d+)", text, re.MULTILINE)
    }
    size = re.search(r"^#define _VECTORS_SIZE \((\d+) \* 4\)", text, re.MULTILINE)
    assert size is not None
    return registers, vectors, int(size.group(1))


def test_every_vector_and_register_the_chip_names_is_the_toolchain_header_s() -> None:
    registers, vectors, entries = _header()
    found = _registers(
        """
        console.log(JSON.stringify({ VECTORS: mcu.VECTORS, REG, words: mcu.VECTOR_TABLE_WORDS }));
        """
    )
    # A vector's word address is twice its number: each entry of the table is a two-word JMP.
    assert {name: address for name, address in found["VECTORS"].items() if name != "RESET"} == {
        name: 2 * number for name, number in vectors.items()
    }
    assert found["VECTORS"]["RESET"] == 0
    assert {name: registers.get(name) for name in found["REG"]} == found["REG"]
    assert found["words"] == 2 * entries


def test_the_watchdog_s_timed_sequence_opens_only_with_wde_for_four_cycles_and_once() -> None:
    found = _registers(
        """
        const W = REG.WDTCSR;
        cpu.writeData(W, 0x08);
        cpu.writeData(W, 0x18); step(4); cpu.writeData(W, 0x00); const atFour = cpu.data[W];
        cpu.writeData(W, 0x08);
        cpu.writeData(W, 0x18); step(5); cpu.writeData(W, 0x00); const atFive = cpu.data[W];
        cpu.writeData(W, 0x10); cpu.writeData(W, 0x00); const wdceAlone = cpu.data[W];
        cpu.writeData(W, 0x18); cpu.writeData(W, 0x0f); cpu.writeData(W, 0x00);
        const once = cpu.data[W];
        console.log(JSON.stringify({ atFour, atFive, wdceAlone, once }));
        """
    )
    # WDCE without WDE opens nothing, and a sequence is spent by the write it lets through.
    assert found == {"atFour": 0x00, "atFive": 0x08, "wdceAlone": 0x08, "once": 0x0F}


def test_the_watchdog_s_period_is_2k_oscillator_cycles_doubled_by_each_prescaler_step() -> None:
    found = _registers(
        """
        const periods = [];
        for (const wdp of [0x00, 0x01, 0x07, 0x20, 0x21]) {
          cpu.writeData(REG.WDTCSR, 0x18); cpu.writeData(REG.WDTCSR, 0x08 | wdp);
          periods.push(chip.watchdog.period);
        }
        console.log(JSON.stringify(periods));
        """
    )
    # WDP3..0 = 0, 1, 7, 8, 9: 16 ms, 32 ms, 2 s, 4 s and 8 s at 128 kHz, in 16 MHz cycles.
    assert found == [125 * (2048 << wdp) for wdp in (0, 1, 7, 8, 9)]


def test_the_watchdog_counts_again_from_its_enabling_and_its_flags_are_cleared_by_a_one() -> None:
    found = _registers(
        """
        const W = REG.WDTCSR;
        const flag = () => cpu.data[W] & 0x80;
        cpu.writeData(W, 0x40); step(100_000);              // interrupt mode, due at 256,000
        cpu.writeData(W, 0x00); step(50_000);               // off
        cpu.writeData(W, 0x40);                             // on again: due 256,000 from now
        step(256_000 - 10); const reEnabled = [flag()]; step(20); reEnabled.push(flag());
        cpu.writeData(W, 0xc0);                             // WDIF cleared by a one, WDIE kept
        const cleared = cpu.data[W];
        step(256_000); const again = flag();
        cpu.writeData(W, 0xc0); const off = [cpu.data[W], pending(mcu.VECTORS.WDT)];
        cpu.writeData(W, 0x00);                             // WDIE cleared: the watchdog stops
        const stopped = cpu.data[W]; step(600_000);
        console.log(JSON.stringify({ reEnabled, cleared, again, off, stopped,
          after: [cpu.data[W], chip.resetRequest] }));
        """
    )
    assert found == {
        "reEnabled": [0, 0x80],
        "cleared": 0x40,
        "again": 0x80,
        "off": [0x40, False],
        "stopped": 0x00,
        "after": [0x00, None],
    }


def test_a_time_out_while_the_watchdog_s_interrupt_is_still_pending_resets_the_chip() -> None:
    found = _registers(
        """
        cpu.writeData(REG.WDTCSR, 0x48);                    // interrupt and reset; no vector taken
        step(256_000 + 10); const first = [chip.resetRequest, cpu.data[REG.WDTCSR] & 0xc0];
        step(256_000); const second = chip.resetRequest;
        console.log(JSON.stringify({ first, second }));
        """
    )
    assert found == {"first": [None, 0xC0], "second": "watchdog"}


def test_a_one_written_to_a_reset_flag_leaves_it_as_it_is() -> None:
    found = _registers(
        """
        cpu.data[REG.MCUSR] = 0x05; cpu.writeData(REG.MCUSR, 0x0f);
        console.log(JSON.stringify(cpu.data[REG.MCUSR]));
        """
    )
    assert found == 0x05


def test_the_watchdog_s_vector_puts_it_in_reset_mode_so_its_next_time_out_resets() -> None:
    # WDE and WDIE: the first time-out (256,000 cycles) takes the vector, which clears WDIE, so
    # the second (512,000) resets the chip.
    found = _program("store(0x60, 0x48);", seconds=0.04)
    assert found["vectors"]["WDT"]["count"] == 1
    power_on, watchdog = found["resets"]
    assert power_on == {"cycle": 0, "cause": "power_on"}
    assert watchdog["cause"] == "watchdog" and 512_000 <= watchdog["cycle"] <= 512_100


def test_the_twi_takes_its_bit_rate_from_twbr_and_the_prescaler_and_nine_bits_a_byte() -> None:
    found = _registers(
        """
        const sr = () => cpu.data[REG.TWSR] & 0xf8;
        // Cycles until TWINT is set (or, with `bit`, until that TWCR bit clears).
        const until = (bit = 0) => {
          for (let n = 1; n <= 100_000; n += 1) {
            cpu.cycles += 1; cpu.tick();
            const v = cpu.data[REG.TWCR];
            if (bit ? !(v & bit) : v & 0x80) return n;
          }
          return null;
        };
        chip.twi.bus = { start: () => true, stop() {}, connect: (a) => a === 0x6b,
          write: () => true, read: () => 0x5a };
        // TWPS = 1, written as firmware does, keeping the status bits: 16 + 2 * 18 * 4 = 160.
        cpu.writeData(REG.TWSR, cpu.data[REG.TWSR] | 0x01); cpu.writeData(REG.TWBR, 18);
        const step1 = (twcr, twdr) => {
          if (twdr !== undefined) cpu.writeData(REG.TWDR, twdr);
          cpu.writeData(REG.TWCR, twcr); return [until(), sr()];
        };
        const start = step1(0xa4);
        const slaW = step1(0x84, 0x6b << 1);
        const data = step1(0x84, 0x22);
        const repeated = step1(0xa4);
        const slaR = step1(0x84, (0x6b << 1) | 1);
        const acked = [...step1(0xc4), cpu.data[REG.TWDR]];
        const last = step1(0x84);
        cpu.writeData(REG.TWCR, 0x94);
        const stop = [until(0x10), cpu.data[REG.TWCR] & 0x80, sr()];
        step1(0xa4);
        const nack = step1(0x84, 0x50 << 1);
        cpu.writeData(REG.TWCR, 0x94); until(0x10);
        step1(0xa4); cpu.writeData(REG.TWDR, 0x6b << 1); cpu.writeData(REG.TWCR, 0x84); step(100);
        cpu.writeData(REG.TWCR, 0x00);                      // disabled with the address on the bus
        const aborted = [chip.twi.busy, sr()]; step(3000);
        aborted.push(cpu.data[REG.TWCR] & 0x80, sr());
        console.log(JSON.stringify({ start, slaW, data, repeated, slaR, acked, last, stop, nack,
          aborted }));
        """
    )
    # One SCL period a START or STOP, nine a byte; avr8js hands each step on one cycle late.
    one, nine = (160, 161), (9 * 160, 9 * 160 + 1)
    timed = {key: value[0] for key, value in found.items() if key != "aborted"}
    assert all(timed[k] in (one if k in ("start", "repeated", "stop") else nine) for k in timed), (
        timed
    )
    assert {key: value[1:] for key, value in found.items() if key != "aborted"} == {
        "start": [0x08],
        "slaW": [0x18],
        "data": [0x28],
        "repeated": [0x10],
        "slaR": [0x40],
        "acked": [0x50, 0x5A],
        "last": [0x58],
        "stop": [0, 0xF8],
        "nack": [0x20],
    }
    assert found["aborted"] == [False, 0xF8, 0, 0xF8]


def test_the_twi_interrupt_is_a_level_taken_again_until_twint_is_cleared() -> None:
    # TWINT | TWSTA | TWEN | TWIE at 100 kHz: the START completes after 160 cycles and the
    # handler, which never writes TWCR, is entered again after every RETI.
    assert _vectors("store(0xb8, 72); store(0xbc, 0xa5);").get("TWI", 0) > 100


def test_an_interrupt_s_time_counts_its_four_response_cycles_and_its_vector_s_jump() -> None:
    # Timer0's overflow at clk/1: a four-cycle response, the vector's JMP (3), the handler's INC
    # (1) and RETI (4): 12 cycles, counted from the CPU's acceptance to the end of the RETI.
    found = _program("store(0x6e, 0x01); store(0x45, 0x01);")
    isr = found["vectors"]["TIMER0_OVF"]
    assert (isr["min"], isr["max"]) == (12, 12)


def test_of_two_interrupts_pending_at_once_the_lower_vector_is_taken_first() -> None:
    found = _registers(
        """
        cpu.writeData(REG.EICRA, 0x0f); cpu.writeData(REG.EIMSK, 0x03);   // INT0, INT1 rising
        chip.ports.D.setPin(1, true); chip.ports.D.setPin(0, true);
        // The vector taken clears its own flag; the other is still pending, and is taken next.
        console.log(JSON.stringify([pending(mcu.VECTORS.INT0), pending(mcu.VECTORS.INT1)]));
        """
    )
    assert found == [True, True]


def test_each_timer_counts_at_its_prescaler_and_raises_each_compare_at_its_own_vector() -> None:
    # 1,600,000 cycles. Timer0 at clk/1024: an overflow every 262,144 cycles and OCR0A = 0x80
    # once per overflow; Timer3 at clk/8: an overflow every 524,288 and OCR3A = 0x8000 once per
    # overflow; Timer1 in CTC mode to OCR1A = 999 at clk/256: a match every 256,000.
    setup = """
    store(0x47, 0x80); store(0x6e, 0x03); store(0x45, 0x05);
    store(0x99, 0x80); store(0x98, 0x00); store(0x71, 0x03); store(0x91, 0x02);
    store(0x89, 0x03); store(0x88, 0xe7); store(0x6f, 0x02); store(0x81, 0x0c);
    """
    found = _program(setup, seconds=0.1)
    counts = {name: v["count"] for name, v in found["vectors"].items()}
    assert counts == {
        "TIMER0_OVF": 6,
        "TIMER0_COMPA": 6,
        "TIMER3_OVF": 3,
        "TIMER3_COMPA": 3,
        "TIMER1_COMPA": 6,
    }


def test_each_compare_output_drives_its_own_pin_and_each_motor_is_its_own_compare() -> None:
    # Timer1 phase- and frequency-correct to ICR1 = 400, OC1A (PB5) at 100 and OC1B (PB6) at
    # 300, non-inverting: a period of 800 cycles, high for twice the compare value. Timer3 in CTC
    # mode to OCR3A = 99 toggling OC3A (PC6): a period of 200 cycles, high for 100.
    setup = """
    store(0x24, 0x60); store(0x27, 0x40);
    store(0x87, 0x01); store(0x86, 0x90); store(0x89, 0x00); store(0x88, 100);
    store(0x8b, 0x01); store(0x8a, 0x2c); store(0x80, 0xa0); store(0x81, 0x11);
    store(0x99, 0x00); store(0x98, 99); store(0x90, 0x40); store(0x91, 0x09);
    """
    found = _program(setup, seconds=0.002)
    pwm = {
        pin: (round(v["period_cycles"]["mean"]), round(v["high_cycles"]["mean"]))
        for pin, v in found["pwm"].items()
    }
    assert pwm.keys() == {"PB5", "PB6", "PC6"}
    assert pwm["PC6"] == (200, 100)
    for pin, high in (("PB5", 200), ("PB6", 600)):
        assert pwm[pin][0] == 800 and abs(pwm[pin][1] - high) <= 4, pwm
    assert (found["motors"]["right"]["last"], found["motors"]["left"]["last"]) == (100, 300)


def test_a_probe_is_timed_from_its_entry_to_its_own_return_and_the_stack_s_deepest_point() -> None:
    # main: CALL f, JMP main; f: CALL g, RET; g: RET. f lasts CALL g (4) + RET (4) + RET (4) =
    # 12 cycles and comes round every 19; inside g the stack holds two return addresses.
    body = """
    const main = at, f = at + 4, g = at + 7;
    words.set(asm.jmp(main), 0);
    words.set([...asm.call(f), ...asm.jmp(main)], main);
    words.set([...asm.call(g), ...asm.ret()], f);
    words.set(asm.ret(), g);
    """
    scenario = {
        "avrsim_scenario": 1,
        "duration_s": 2000 / 16e6,
        "probes": [{"symbol": "f", "period_s": 19 / 16e6}],
    }
    found = _node(
        CALLS
        % {
            "src": _src(),
            "body": body,
            "symbols": json.dumps({"f": 0x56 + 4}),
            "scenario": json.dumps(scenario),
        }
    )
    f = found["probes"]["f"]
    assert (f["duration_cycles"]["min"], f["duration_cycles"]["max"]) == (12, 12)
    assert (f["period_cycles"]["min"], f["period_cycles"]["max"]) == (19, 19)
    assert (f["lateness_cycles"]["min"], f["lateness_cycles"]["max"]) == (0, 0)
    assert found["stack"]["max_depth_bytes"] == 4


def test_usb_frames_count_only_while_the_controller_is_attached_clocked_and_locked() -> None:
    found = _registers(
        """
        const u = new mcu.ATmega32U4(new Uint16Array(0x4000), {
          eeprom: new mcu.EEPROMMemoryBackend(1024), bus, sof: true });
        const c = u.cpu;
        const run = (n) => {
          const end = c.cycles + n; while (c.cycles < end) { c.cycles += 1; c.tick(); } };
        const sofi = () => c.data[REG.UDINT] & 0x04;
        const frames = () => c.data[REG.UDFNUML] | (c.data[REG.UDFNUMH] << 8);
        c.writeData(REG.PLLCSR, 0x12); run(2000);
        c.writeData(REG.UDCON, 0x00); c.writeData(REG.USBCON, 0xa0); run(40_000);
        const frozen = [sofi(), frames()];
        c.writeData(REG.USBCON, 0x80); run(40_000);
        const attached = [sofi(), frames()];
        c.writeData(REG.UDINT, 0x00); c.writeData(REG.UDCON, 0x01); run(40_000);
        const detached = [sofi(), frames()];
        c.writeData(REG.UDCON, 0x00); c.writeData(REG.PLLCSR, 0x00); run(40_000);
        const unlocked = [sofi(), frames()];
        c.writeData(REG.USBSTA, 0x01);
        console.log(JSON.stringify({ frozen, attached, detached, unlocked,
          vbus: c.data[REG.USBSTA] & 0x01 }));
        """
    )
    frames = found["attached"][1]
    assert frames >= 2
    assert found == {
        "frozen": [0, 0],
        "attached": [0x04, frames],
        "detached": [0, frames],
        "unlocked": [0, frames],
        "vbus": 0,
    }


def test_a_compare_flag_already_set_is_taken_once_its_enable_is_written() -> None:
    # Timer1 in normal mode at clk/1 with OCR1C = 0x10: the match sets OCF1C with OCIE1C clear,
    # and writing OCIE1C then makes the interrupt pending at once (datasheet "Interrupts").
    found = _registers(
        """
        cpu.writeData(REG.OCR1CL + 1, 0x00); cpu.writeData(REG.OCR1CL, 0x10);
        cpu.writeData(REG.TCCR1B, 0x01); step(100);
        const flagged = [cpu.data[REG.TIFR1] & 0x08, pending(mcu.VECTORS.TIMER1_COMPC)];
        cpu.writeData(REG.TIMSK1, 0x08);
        console.log(JSON.stringify({ flagged, enabled: pending(mcu.VECTORS.TIMER1_COMPC) }));
        """
    )
    assert found == {"flagged": [0x08, False], "enabled": True}


def test_an_interrupt_under_way_when_the_main_program_stalls_runs_to_its_reti() -> None:
    # Timer0's overflow at clk/1024 (every 262,144 cycles) runs a handler of some 760 cycles.
    # The main program stalls with interrupts off from cycle 262,400, inside the first handler:
    # that handler still finishes in its usual time, and the later ones run as before.
    handler = "[0xe010 | ((250 & 0xf0) << 4) | (250 & 0x0f), 0x951a, 0xf7f1, ...asm.reti()]"
    found = _program(
        "store(0x6e, 0x01); store(0x45, 0x05);",
        seconds=0.05,
        handler=handler,
        stalls=[{"start_s": 262_400 / 16e6, "end_s": 0.02, "interrupts": False}],
    )
    isr = found["vectors"]["TIMER0_OVF"]
    assert isr["count"] == 3 and isr["min"] == isr["max"] < 1000, isr
