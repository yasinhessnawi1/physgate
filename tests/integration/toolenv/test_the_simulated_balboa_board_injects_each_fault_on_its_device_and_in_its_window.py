"""The simulated Balboa board injects each fault on the device it names and only while it lasts.

The board model wires the inertial sensors to the chip's 2-wire interface and holds the
scenario's faults. Each row builds the board on a fresh ATmega32U4 of the provisioned rig, sets
the chip's clock to the instant it asks about, and works the bus as the chip's interface would:
a fault reaches only the device it names, from its start up to (not at) its end; a stale sensor
holds the sample it had when the fault began; a bus held low is released by nine SCL clocks
driven with the interface off, and by nothing else.
"""

from __future__ import annotations

import json
import math
import subprocess
from typing import Any

import pytest
from avrsim_rig import environment

pytestmark = pytest.mark.integration

#: The board under `faults`, on a fresh chip; `at(s)` sets the chip's clock to `s` seconds.
BOARD = """
const src = %(src)s;
const mcu = await import(`${src}/mcu.js`);
const { Balboa32U4 } = await import(`${src}/board.js`);
const { readScenario } = await import(`${src}/scenario.js`);
const { REG } = mcu;
const scenario = readScenario(JSON.stringify({ avrsim_scenario: 1, duration_s: 2,
  imu: { pitch_rad: [[0, 0]], pitch_rate_rad_s: [[0, 0], [2, 2]] }, faults: %(faults)s }));
const board = new Balboa32U4(scenario);
const chip = new mcu.ATmega32U4(new Uint16Array(0x4000), {
  eeprom: new mcu.EEPROMMemoryBackend(1024), bus: board.bus });
board.attach(chip);
const { cpu } = chip;
const at = (s) => { cpu.cycles = Math.round(s * mcu.FREQUENCY_HZ); };
const bus = board.bus;
%(body)s
"""


def _node(script: str) -> Any:
    done = subprocess.run(
        [str(environment() / "node" / "bin" / "node"), "--input-type=module", "-"],
        input=script, cwd="/", env={"PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
        capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr[-3000:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def _board(faults: list[dict[str, Any]], body: str) -> Any:
    src = json.dumps((environment() / "avrsim" / "src").as_uri())
    return _node(BOARD % {"src": src, "faults": json.dumps(faults), "body": body})


def test_a_nack_reaches_only_its_device_from_its_start_up_to_its_end() -> None:
    found = _board(
        [{"kind": "nack", "device": "lis3mdl", "start_s": 0.2, "end_s": 0.4}],
        """
        const acks = (s) => { at(s); const r = [bus.connect(0x6b, true), bus.connect(0x1e, true)];
          bus.stop(); return r; };
        console.log(JSON.stringify([0.1999, 0.2, 0.3, 0.4].map(acks)));
        """,
    )
    assert found == [[True, True], [True, False], [True, False], [True, True]]


def test_a_stale_sensor_holds_the_sample_it_had_when_the_fault_began() -> None:
    # The pitch rate is t rad/s; at 208 Hz and 1000 dps the newest sample at 0.5 s is k = 104.
    found = _board(
        [{"kind": "stale", "start_s": 0.5, "end_s": 1.0}],
        """
        const transfer = (register, bytes) => {
          bus.connect(0x6b, true); bus.write(register);
          if (bytes === undefined) return null;
          bus.connect(0x6b, false);
          const values = Array.from({ length: bytes }, () => bus.read(true)); bus.stop();
          return values;
        };
        at(0); bus.connect(0x6b, true); bus.write(0x11); bus.write(0x58); bus.stop();
        const y = (s) => {
          at(s); const g = transfer(0x22, 6); return ((g[3] << 8) | g[2]) << 16 >> 16; };
        console.log(JSON.stringify([y(0.4), y(0.7), y(0.9), y(1.1)]));
        """,
    )

    def sample(k: int) -> int:
        return round(math.degrees(k / 208) * 1000 / 35)

    assert found == [sample(83), sample(104), sample(104), sample(228)]


@pytest.mark.parametrize("release", ["scl_pulses", "end"])
def test_a_held_bus_is_released_only_by_nine_scl_clocks_driven_with_the_interface_off(
    release: str,
) -> None:
    found = _board(
        [{"kind": "sda_held", "release": release, "start_s": 0, "end_s": 1}],
        """
        const sda = () => (cpu.readData(REG.PIND) >> 1) & 1;
        const pulses = (n) => { for (let i = 0; i < n; i += 1) {
          cpu.writeData(REG.PORTD, 0x00); cpu.writeData(REG.PORTD, 0x01); } };
        at(0.1);
        cpu.writeData(REG.PORTD, 0x01); cpu.writeData(REG.DDRD, 0x01);   // SCL driven high
        cpu.writeData(REG.TWCR, 0x04); pulses(9);                       // the interface on
        const withTwi = [sda(), bus.start()];
        cpu.writeData(REG.TWCR, 0x00); pulses(8);
        const eight = [sda(), bus.start()];
        pulses(1);
        console.log(JSON.stringify({ withTwi, eight, nine: [sda(), bus.start()] }));
        """,
    )
    held = [0, False]
    assert found == {
        "withTwi": held,
        "eight": held,
        "nine": [1, True] if release == "scl_pulses" else held,
    }


def test_a_held_bus_is_released_by_nine_clocks_of_scl_as_an_open_drain_line_too() -> None:
    # Bus recovery clocks SCL; an open-drain master drives it low and releases it to the
    # board's pull-up (DDR set with PORT low, then DDR cleared). A clock is SCL's level rising,
    # whatever raises it.
    found = _board(
        [{"kind": "sda_held", "release": "scl_pulses", "start_s": 0, "end_s": 1}],
        """
        const sda = () => (cpu.readData(REG.PIND) >> 1) & 1;
        const clocks = (n) => { for (let i = 0; i < n; i += 1) {
          cpu.writeData(REG.DDRD, 0x01); cpu.writeData(REG.DDRD, 0x00); } };
        at(0.1); cpu.writeData(REG.PORTD, 0x00);
        clocks(8); const eight = sda();
        clocks(1);
        console.log(JSON.stringify({ eight, nine: [sda(), bus.start()] }));
        """,
    )
    assert found == {"eight": 0, "nine": [1, True]}


@pytest.mark.parametrize("sensor", ["gyro", "accel"])
def test_a_saturation_reaches_only_the_sensor_it_names(sensor: str) -> None:
    # The fault names its sensor and axes; the other sensor reads its true counts.
    found = _board(
        [{"kind": "saturated", "sensor": sensor, "axes": ["x"], "start_s": 0, "end_s": 2}],
        """
        const read = (register) => { bus.connect(0x6b, true); bus.write(register);
          bus.connect(0x6b, false); const v = [bus.read(true), bus.read(true)]; bus.stop();
          return ((v[1] << 8) | v[0]) << 16 >> 16; };
        at(0); bus.connect(0x6b, true); bus.write(0x10); bus.write(0x40); bus.write(0x58);
        bus.stop();
        at(0.5);
        console.log(JSON.stringify({ gyro: read(0x22), accel: read(0x28) }));
        """,
    )
    upright = round(1000 / 0.061)
    assert found == {
        "gyro": 32767 if sensor == "gyro" else 0,
        "accel": 32767 if sensor == "accel" else upright,
    }
