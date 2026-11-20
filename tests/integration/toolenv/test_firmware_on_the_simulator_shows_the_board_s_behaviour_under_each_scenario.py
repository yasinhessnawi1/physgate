"""Firmware built with the environment runs on its simulator and shows the board's behaviour.

One bench firmware, built offline with the environment's own PlatformIO, is run under one
scenario per behaviour the simulator is to show: the inertial sensor read over the bus at the
configured full scale, the motors' PWM and commands, the encoders' and buttons' inputs, the
battery reading, a sensor that stops acknowledging, a bus held low with and without the
firmware's recovery, a main program stalled with interrupts on and off, the watchdog's reset and
what the firmware finds after it, and the same inputs giving the same bytes twice. Each answer is
known from the firmware's source, the scenario and the datasheets, and is read from the
simulator's summary and trace, never from what the firmware says of itself alone.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pytest
from avrsim_rig import build, environment, simulate

pytestmark = pytest.mark.integration

F = 16_000_000

BENCH = r"""#include <Arduino.h>
#include <Wire.h>
#include <avr/wdt.h>
#include <Balboa32U4.h>

Balboa32U4Motors motors;
Balboa32U4Encoders encoders;
Balboa32U4ButtonA buttonA;

static uint8_t resetFlags __attribute__((section(".noinit")));
// Read and clear the reset flags before anything else, and the watchdog with them.
void takeResetFlags(void) __attribute__((naked, used, section(".init3")));
void takeResetFlags(void) {
  resetFlags = MCUSR;
  MCUSR = 0;
  wdt_disable();
}

static int16_t gyro[3], accel[3];
static uint8_t failures;
static uint16_t updates;

static void writeRegister(uint8_t reg, uint8_t value) {
  Wire.beginTransmission(0x6B);
  Wire.write(reg);
  Wire.write(value);
  Wire.endTransmission();
}

static bool readImu() {
  Wire.beginTransmission(0x6B);
  Wire.write(0x22);
  if (Wire.endTransmission() != 0) return false;
  if (Wire.requestFrom((uint8_t)0x6B, (uint8_t)12) != 12) return false;
  for (uint8_t i = 0; i < 3; i++) {
    uint8_t lo = Wire.read();
    uint8_t hi = Wire.read();
    gyro[i] = (int16_t)((hi << 8) | lo);
  }
  for (uint8_t i = 0; i < 3; i++) {
    uint8_t lo = Wire.read();
    uint8_t hi = Wire.read();
    accel[i] = (int16_t)((hi << 8) | lo);
  }
  return true;
}

// Nine clocks on SCL with the interface off, then the interface again.
static void recoverBus() {
  TWCR = 0;
  DDRD |= 1;
  for (uint8_t i = 0; i < 9; i++) {
    PORTD &= ~1;
    delayMicroseconds(5);
    PORTD |= 1;
    delayMicroseconds(5);
  }
  DDRD &= ~1;
  Wire.begin();
  Wire.setWireTimeout(2000, true);
}

extern "C" __attribute__((noinline, used)) void update() {
  updates++;
  bool ok = readImu();
  if (Wire.getWireTimeoutFlag()) {
    Wire.clearWireTimeoutFlag();
    recoverBus();
  }
  if (ok) {
    failures = 0;
    int16_t command = gyro[1] / 8;
    motors.setSpeeds(command, command);
  } else if (++failures >= 3) {
    motors.setSpeeds(0, 0);
  }
  wdt_reset();
  if (updates % 10 == 0) {
    Serial1.print(F("G:"));
    Serial1.print(gyro[1]);
    Serial1.print(F(" X:"));
    Serial1.print(accel[0]);
    Serial1.print(F(" A:"));
    Serial1.print(buttonA.isPressed());
    Serial1.print(F(" L:"));
    Serial1.print(encoders.getCountsLeft());
    Serial1.print(F(" R:"));
    Serial1.println(encoders.getCountsRight());
  }
}

void setup() {
  Serial1.begin(115200);
  Serial1.print(F("RESET:"));
  Serial1.println(resetFlags);
  Serial1.print(F("BAT:"));
  Serial1.println(readBatteryMillivolts());
  Wire.begin();
  Wire.setWireTimeout(2000, true);
  writeRegister(0x10, 0x40);  // CTRL1_XL: 104 Hz, +-2 g
  writeRegister(0x11, 0x58);  // CTRL2_G: 208 Hz, 1000 dps
  encoders.init();
  wdt_enable(WDTO_60MS);
}

void loop() {
  static uint32_t next = 0;
  uint32_t now = millis();
  if ((int32_t)(now - next) >= 0) {
    next += 10;
    update();
  }
}
"""

RATE = 0.5  # rad/s
#: The gyroscope's y counts at 1000 dps (35 mdps a count), and the command the bench derives.
GYRO_Y = round(math.degrees(RATE) * 1000 / 35)
COMMAND = int(GYRO_Y / 8)


def scenario(**more: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "avrsim_scenario": 1,
        "duration_s": 1.0,
        "imu": {"pitch_rad": [[0, 0]], "pitch_rate_rad_s": [[0, RATE]]},
        "probes": [{"symbol": "update", "period_s": 0.01}],
    }
    return base | more


@pytest.fixture(scope="module")
def bench(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    env = environment()
    return env, build(env, tmp_path_factory.mktemp("bench"), BENCH)


def _lines(summary: dict[str, Any]) -> list[str]:
    return [line for line in summary["usart1"]["text"].splitlines() if line]


def _cycle(seconds: float) -> int:
    return round(seconds * F)


def test_the_sensor_is_read_at_its_full_scale_and_the_motors_driven_from_it(
    bench: tuple[Path, Path], tmp_path: Path
) -> None:
    env, elf = bench
    summary, trace = simulate(env, elf, scenario(), tmp_path)
    lines = _lines(summary)
    assert lines[0] == "RESET:1"  # power-on: PORF
    assert lines[-1] == f"G:{GYRO_Y} X:{round(1000 / 0.061)} A:0 L:0 R:0"
    assert summary["imu"]["registers_written"] == {"CTRL1_XL": 0x40, "CTRL2_G": 0x58}
    assert summary["imu"]["gyro_samples_read"] >= 99
    # OCR1A and OCR1B carry the command; Timer1 in phase- and frequency-correct mode to 400.
    assert summary["motors"]["left"]["last"] == COMMAND
    assert summary["motors"]["right"]["max"] == COMMAND
    assert summary["timer1"] == {"icr1": 400, "wgm": 8, "tccr1a": 0b10100000, "tccr1b": 0b00010001}
    for pin in ("PB5", "PB6"):
        pwm = summary["pwm"][pin]
        assert pwm["frequency_hz"] == pytest.approx(20_000, rel=0.01)
        assert pwm["high_cycles"]["mean"] == pytest.approx(2 * COMMAND, abs=4)
    # The motors' direction pins stay low for a positive command.
    assert not [
        e for e in trace if e["type"] == "pin" and e["pin"] in ("PB1", "PB2") and e["value"]
    ]
    # The update runs at 100 Hz, and the sample it reads reaches the motors within a period.
    update = summary["probes"]["update"]
    assert update["entries"] >= 99
    assert update["period_cycles"]["mean"] == pytest.approx(F / 100, rel=0.01)
    delay = summary["input_to_output_cycles"]
    assert delay["count"] >= 99 and 0 < delay["max"] < F / 100
    # What ran, and the stack it took.
    vectors = summary["vectors"]
    assert vectors["TIMER0_OVF"]["count"] == pytest.approx(F / 64 / 256, abs=2)
    assert vectors["TWI"]["count"] > 0 and vectors["USART1_UDRE"]["count"] > 0
    assert all(v["max"] >= v["min"] > 0 for v in vectors.values())
    assert 0 < summary["stack"]["max_depth_bytes"] < 2560
    assert summary["stack"]["headroom_bytes"] > 0
    assert summary["resets"] == [{"cycle": 0, "cause": "power_on"}]


def test_the_motor_outputs_are_not_driven_high_from_reset_until_the_firmware_commands_them(
    bench: tuple[Path, Path], tmp_path: Path
) -> None:
    env, elf = bench
    _, trace = simulate(env, elf, scenario(duration_s=0.2), tmp_path)
    first_command = next(e["c"] for e in trace if e["type"] == "ocr" and e["value"] > 0)
    before = [e for e in trace if e["c"] < first_command and e.get("pin") in ("PB5", "PB6")]
    assert all(e["type"] == "ddr" or e.get("value") == 0 for e in before), before
    assert not [e for e in trace if e["type"] == "pwm" and e["c"] < first_command]


def test_the_same_firmware_and_scenario_give_the_same_bytes(
    bench: tuple[Path, Path], tmp_path: Path
) -> None:
    env, elf = bench
    simulate(env, elf, scenario(duration_s=0.3), tmp_path / "a")
    simulate(env, elf, scenario(duration_s=0.3), tmp_path / "b")
    for name in ("run.jsonl", "run.summary.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name


def test_encoders_buttons_and_the_battery_are_read_as_the_board_wires_them(
    bench: tuple[Path, Path], tmp_path: Path
) -> None:
    env, elf = bench
    summary, _ = simulate(
        env,
        elf,
        scenario(
            encoders={
                "left_rev_s": [[0, 2], [0.5, 2], [0.5001, 0]],
                "right_rev_s": [[0, -1], [0.5, -1], [0.5001, 0]],
            },
            buttons=[{"button": "A", "start_s": 0.62, "end_s": 0.78}],
            battery_v=7.2,
        ),
        tmp_path,
    )
    lines = _lines(summary)
    # VBAT / 3 on ADC6 against 5 V: 491 counts, which Balboa's own formula reads as 7192 mV.
    assert lines[1] == f"BAT:{(8 * math.floor(7.2 / 3 / 5 * 1024) * 1875 + 511) // 1024}"
    assert lines[-1].endswith(" A:0 L:12 R:-6")
    pressed = [line for line in lines if " A:1 " in line]
    assert pressed, lines
    assert summary["encoders"]["counts"] == {"left": 12, "right": -6}
    # Every left edge is a pin change on PB4, every right one a change on INT6.
    assert summary["vectors"]["PCINT0"]["count"] == summary["encoders"]["edges"]["left"]
    assert summary["vectors"]["INT6"]["count"] == summary["encoders"]["edges"]["right"]


@pytest.mark.parametrize("sof", [False, True])
def test_wheels_turning_steadily_are_counted_edge_by_edge_for_the_whole_run(
    bench: tuple[Path, Path], tmp_path: Path, sof: bool
) -> None:
    env, elf = bench
    # 50 motor revolutions a second, 12 counts each: 600 edges a second on each wheel.
    encoders = {"left_rev_s": [[0, 50]], "right_rev_s": [[0, -50]]}
    summary, _ = simulate(env, elf, scenario(encoders=encoders, usb_sof=sof), tmp_path)
    assert summary["encoders"]["counts"] == {"left": 600, "right": -600}
    # Every edge after setup() enabled the two interrupts, a few milliseconds in, is one.
    assert 595 <= summary["vectors"]["PCINT0"]["count"] <= 600
    assert 595 <= summary["vectors"]["INT6"]["count"] <= 600
    left, right = (int(word[2:]) for word in _lines(summary)[-1].split()[-2:])
    assert 590 <= left <= 600 and -600 <= right <= -590


def test_a_sensor_that_stops_acknowledging_stops_the_motors_and_they_restart_after(
    bench: tuple[Path, Path], tmp_path: Path
) -> None:
    env, elf = bench
    summary, trace = simulate(
        env,
        elf,
        scenario(faults=[{"kind": "nack", "device": "lsm6ds33", "start_s": 0.3, "end_s": 0.5}]),
        tmp_path,
    )
    (event,) = summary["events"]
    assert event["kind"] == "fault:nack" and event["cycle"] == _cycle(0.3)
    # The third failed read at 10 ms intervals: within 30 ms plus one update.
    assert 0.02 <= event["motors_off_delay_s"] <= 0.04
    assert _cycle(0.5) <= event["motors_off_until_cycle"] <= _cycle(0.52)
    nacks = [e for e in trace if e["type"] == "twi" and e["kind"] == "address" and not e["ack"]]
    assert nacks and all(_cycle(0.3) <= e["c"] < _cycle(0.5) for e in nacks)
    assert summary["motors"]["left"]["last"] == COMMAND


@pytest.mark.parametrize("release", ["end", "scl_pulses"])
def test_a_held_bus_blocks_every_start_until_released(
    bench: tuple[Path, Path], tmp_path: Path, release: str
) -> None:
    env, elf = bench
    fault = {"kind": "sda_held", "release": release, "start_s": 0.3, "end_s": 0.8}
    summary, trace = simulate(env, elf, scenario(faults=[fault]), tmp_path)
    acked = [
        e["c"] for e in trace
        if e["type"] == "twi" and e["kind"] == "address" and e["ack"]
        and _cycle(0.31) <= e["c"] < _cycle(0.8)
    ]  # fmt: skip
    (event,) = summary["events"]
    clocks = [e for e in trace if e["type"] == "pin" and e["pin"] == "PD0" and e["value"] == 1]
    assert clocks, "the bench drives no recovery clocks"
    if release == "end":
        # Nothing on the bus while it is held, whatever the firmware clocks; motors off.
        assert acked == []
        assert 0.02 <= event["motors_off_delay_s"] <= 0.05
        assert event["motors_off_until_cycle"] >= _cycle(0.8)
    else:
        # The firmware's nine clocks release it, the reads resume, and the motors never stop.
        assert acked
        assert event["motors_off_cycle"] is None or event["motors_off_cycle"] >= _cycle(0.8)


def test_a_main_program_stalled_with_interrupts_off_is_reset_by_the_watchdog(
    bench: tuple[Path, Path], tmp_path: Path
) -> None:
    env, elf = bench
    summary, trace = simulate(
        env, elf, scenario(stalls=[{"start_s": 0.3, "end_s": 0.5, "interrupts": False}]), tmp_path
    )
    resets = summary["resets"]
    assert [r["cause"] for r in resets] == ["power_on", "watchdog"]
    # WDTO_60MS is 8K cycles of the 128 kHz oscillator, 64 ms, counted from the last wdt_reset
    # in the update before the stall.
    assert _cycle(0.3 + 0.064 - 0.011) <= resets[1]["cycle"] <= _cycle(0.3 + 0.064)
    lines = _lines(summary)
    assert lines.count("RESET:1") == 1 and "RESET:8" in lines  # WDRF after the reset
    (event,) = summary["events"]
    assert event["kind"] == "stall"
    assert event["motors_off_cycle"] == resets[1]["cycle"]
    # Nothing ran between the stall's start and the reset: no motor command, no bus traffic.
    quiet = [
        e
        for e in trace
        if _cycle(0.3) < e["c"] < resets[1]["cycle"] and e["type"] in ("ocr", "twi", "usart1")
    ]
    assert quiet == []
    # After the reset the firmware runs again and drives the motors.
    assert summary["motors"]["left"]["last"] == COMMAND


def test_a_main_program_stalled_with_interrupts_on_misses_updates_while_timers_still_count(
    bench: tuple[Path, Path], tmp_path: Path
) -> None:
    env, elf = bench
    summary, _ = simulate(
        env, elf, scenario(stalls=[{"start_s": 0.3, "end_s": 0.34, "interrupts": True}]), tmp_path
    )
    assert [r["cause"] for r in summary["resets"]] == ["power_on"]
    update = summary["probes"]["update"]
    assert update["period_cycles"]["max"] >= _cycle(0.04)
    assert update["lateness_cycles"]["max"] >= _cycle(0.03)
    assert summary["vectors"]["TIMER0_OVF"]["count"] == pytest.approx(F / 64 / 256, abs=2)


def test_start_of_frame_interrupts_are_a_load_only_when_asked_for(
    bench: tuple[Path, Path], tmp_path: Path
) -> None:
    env, elf = bench
    without, _ = simulate(env, elf, scenario(duration_s=0.5), tmp_path / "without")
    with_sof, _ = simulate(env, elf, scenario(duration_s=0.5, usb_sof=True), tmp_path / "with")
    assert "USB_GEN" not in without["vectors"]
    # One frame a millisecond once the firmware has attached, a few milliseconds in.
    assert 480 <= with_sof["vectors"]["USB_GEN"]["count"] <= 500


def test_a_probe_the_elf_does_not_hold_is_refused_and_nothing_is_written(
    bench: tuple[Path, Path], tmp_path: Path
) -> None:
    import json
    import subprocess

    from avrsim_rig import EMPTY, avrsim

    env, elf = bench
    path = tmp_path / "s.json"
    path.write_text(json.dumps(scenario(probes=[{"symbol": "balance"}])), encoding="utf-8")
    done = subprocess.run(
        [str(avrsim(env)), "run", "--elf", str(elf), "--scenario", str(path)]
        + ["--out", str(tmp_path / "t.jsonl")],
        cwd="/", env=EMPTY, capture_output=True, text=True, timeout=120, check=False,
    )  # fmt: skip
    assert done.returncode == 2
    assert "the probe balance is not a function in the ELF" in done.stderr
    assert not (tmp_path / "t.jsonl").exists()
