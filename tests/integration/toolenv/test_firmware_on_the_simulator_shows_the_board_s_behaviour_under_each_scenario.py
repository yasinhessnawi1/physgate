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
#: The sketch's first instruction after power-on: the fuses' start-up time, 16K CK + 14CK + 65 ms.
START = round(0.065 * F) + 14 + 16_384
#: The gyroscope's y counts at 1000 dps (35 mdps a count), its zero-rate level of 10 dps by
#: default (datasheet G_TyOff) included, and the command the bench derives.
GYRO_Y = round((math.degrees(RATE) + 10) * 1000 / 35)
COMMAND = int(GYRO_Y / 8)
#: The accelerometer's x at +-2 g (0.061 mg a count): 1 g upright and its zero-g level of 40 mg
#: by default (datasheet LA_TyOff).
ACCEL_X = round(1040 / 0.061)


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
    # Power-on: the bootloader clears PORF (and BORF) before the sketch (Caterina.c main()).
    assert lines[0] == "RESET:0"
    assert lines[-1] == f"G:{GYRO_Y} X:{ACCEL_X} A:0 L:0 R:0"
    assert summary["imu"]["registers_written"] == {"CTRL1_XL": 0x40, "CTRL2_G": 0x58}
    # The sketch starts some 66 ms after power-on and the gyroscope then turns on for 80 ms
    # (AN4682 Table 16): of some 92 updates, the first ones find no sample or an invalid one,
    # which the summary counts.
    assert summary["imu"]["gyro_samples_read"] >= 85
    assert summary["imu"]["invalid_samples_read"]["gyro"] >= 1
    # OCR1A and OCR1B carry the command; Timer1 in phase- and frequency-correct mode to 400.
    assert summary["motors"]["left"]["last"] == summary["motors"]["right"]["last"] == COMMAND
    # The bench does not wait for data ready: during the turn-on it reads the outputs before any
    # sample and the samples to discard, which read -32768 (the rig's value for them): a command
    # of -4096, which the library limits to its 300, in reverse.
    assert summary["motors"]["right"]["max"] == 300
    assert summary["timer1"] == {"icr1": 400, "wgm": 8, "tccr1a": 0b10100000, "tccr1b": 0b00010001}
    for pin in ("PB5", "PB6"):
        pwm = summary["pwm"][pin]
        assert pwm["frequency_hz"] == pytest.approx(20_000, rel=0.01)
        # The last high time is the command's (the mean holds the reverse ones at the start).
        assert pwm["last_high_cycles"] == pytest.approx(2 * COMMAND, abs=4)
    # The direction pins went high for that reverse command and are low for the positive one.
    direction = [e["value"] for e in trace if e["type"] == "pin" and e["pin"] in ("PB1", "PB2")]
    assert 1 in direction and direction[-2:] == [0, 0]
    # The update runs at 100 Hz from the sketch's start, 65 ms after power-on.
    update = summary["probes"]["update"]
    assert update["entries"] >= 90
    entries = [e["c"] for e in trace if e["type"] == "probe" and e["symbol"] == "update"]
    steady = entries[5:]
    assert (steady[-1] - steady[0]) / (len(steady) - 1) == pytest.approx(F / 100, rel=0.001)
    # Lateness is against the grid of the 10 ms period through the earliest phase seen.
    # millis() counts from init(), and before setup() the core waits for the PLL's lock (some
    # 10 ms here), so the first updates are due at once and come back to back: late on the grid
    # the later ones keep, by up to that wait. Against the first entry they read early instead.
    late = update["lateness_cycles"]
    assert late["min"] == 0 and _cycle(0.005) <= late["max"] <= _cycle(0.015)
    assert update["lateness_from_first_entry_cycles"]["max"] <= 0
    # Past the catch-up, millis() steps by 1.024 ms and no update strays by more than that.
    steady_late = [c - steady[0] - i * (F / 100) for i, c in enumerate(steady)]
    assert max(steady_late) - min(steady_late) <= _cycle(0.0011)
    period = update["period_cycles"]
    assert 0 < period["min"] <= period["max"] <= _cycle(0.0111)
    duration = update["duration_cycles"]
    assert update["entries"] - 1 <= duration["count"] <= update["entries"]
    assert 0 < duration["min"] <= duration["max"] < F / 100
    # The bound runs from the oldest sample read since each compare register's last write, the
    # accelerometer's included: at 104 Hz up to 9.6 ms old when read, and the 12-byte read at
    # 100 kHz takes some 1.1 ms more.
    delay = summary["input_to_output"]
    assert delay["upper_bound_cycles"]["count"] >= 2 * 85
    assert 0 < delay["upper_bound_cycles"]["max"] < _cycle(1 / 104 + 0.0015)
    assert delay["newest_sample_cycles"]["max"] <= delay["upper_bound_cycles"]["max"]
    # What ran, and the stack it took.
    vectors = summary["vectors"]
    assert vectors["TIMER0_OVF"]["count"] == pytest.approx((F - START) / 64 / 256, abs=2)
    assert vectors["TWI"]["count"] > 0 and vectors["USART1_UDRE"]["count"] > 0
    assert all(
        v["inclusive_cycles"]["max"] >= v["exclusive_cycles"]["min"] > 0 for v in vectors.values()
    )
    assert 0 < summary["stack"]["max_depth_bytes"] < 2560
    assert summary["stack"]["headroom_bytes"] > 0
    assert summary["resets"] == [
        {"cycle": 0, "cause": "power_on", "sketch_start_cycle": START, "mcusr_at_sketch_start": 0}
    ]
    # Ordinary Arduino firmware touches nothing the rig does not model: its core's start-up
    # (the timers, the ADC, USB's attach) and the Wire master's TWEA are not uses of it.
    assert summary["unmodelled"] == {} and summary["evidence_end"] is None
    assert (summary["timing_evaluable"], summary["behaviour_evaluable"]) == (True, True)


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
                # From 0.1 s, once encoders.init() has run (the sketch starts at 65 ms).
                "left_rev_s": [[0, 0], [0.1, 0], [0.1001, 2], [0.6, 2], [0.6001, 0]],
                "right_rev_s": [[0, 0], [0.1, 0], [0.1001, -1], [0.6, -1], [0.6001, 0]],
            },
            buttons=[{"button": "A", "start_s": 0.72, "end_s": 0.88}],
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
    # Every edge after setup() enabled the two interrupts is one: the sketch starts at 65 ms and
    # setup() waits some 10 ms for the PLL first, so the edges of the first 75 to 90 ms are not
    # seen (on the board neither).
    for vector in ("PCINT0", "INT6"):
        assert 540 <= summary["vectors"][vector]["count"] <= 555
    # The bench prints every tenth update, so its last line is at most 100 ms (60 edges) old.
    left, right = (int(word[2:]) for word in _lines(summary)[-1].split()[-2:])
    seen = summary["vectors"]["PCINT0"]["count"], summary["vectors"]["INT6"]["count"]
    assert seen[0] - 60 <= left <= seen[0] and -seen[1] <= right <= -seen[1] + 60


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
        # Nothing on the bus while it is held, whatever the firmware clocks: no START completes,
        # so no address is ever sent; motors off.
        assert acked == []
        assert not [
            e for e in trace
            if e["type"] == "twi" and e["kind"] == "address"
            and _cycle(0.31) <= e["c"] < _cycle(0.8)
        ]  # fmt: skip
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
    # On the board the bootloader clears WDRF before the sketch reads MCUSR: both starts read 0.
    assert lines.count("RESET:0") == 2
    (event,) = summary["events"]
    assert event["kind"] == "stall"
    assert event["motors_off_cycle"] == resets[1]["cycle"]
    # The reset also returns OCR1A and OCR1B to 0, their reset value.
    assert event["ocr_zero_cycle"] == resets[1]["cycle"]
    # Nothing ran between the stall's start and the reset: no motor command, no bus traffic.
    quiet = [
        e
        for e in trace
        if _cycle(0.3) < e["c"] < resets[1]["cycle"] and e["type"] in ("ocr", "twi", "usart1")
    ]
    assert quiet == []
    # After the reset the firmware runs again and drives the motors: the reset ends the stall,
    # so updates come again from the sketch's start, before the stall's own end at 0.5 s.
    assert resets[1]["sketch_start_cycle"] - resets[1]["cycle"] == START
    again = [
        e["c"] for e in trace
        if e["type"] == "probe" and resets[1]["sketch_start_cycle"] <= e["c"] < _cycle(0.5)
    ]  # fmt: skip
    assert again
    assert summary["motors"]["left"]["last"] == COMMAND
    # No interrupt ran in the stall either: Timer0 lost the overflows of its 64 ms or more.
    assert summary["vectors"]["TIMER0_OVF"]["count"] <= round(0.95 * (F - 2 * START) / 64 / 256)


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
    # On the grid of the earliest phase the stall makes the first update after it some 40 ms
    # late; against the first entry, which the PLL's lock before setup() made late itself, the
    # same update reads that much less late.
    late = update["lateness_cycles"]
    assert late["min"] == 0 and _cycle(0.03) <= late["max"] <= _cycle(0.045)
    first = update["lateness_from_first_entry_cycles"]
    assert first["max"] < late["max"] - _cycle(0.005)
    assert summary["vectors"]["TIMER0_OVF"]["count"] == pytest.approx((F - START) / 64 / 256, abs=2)


def test_start_of_frame_interrupts_are_a_load_only_when_asked_for(
    bench: tuple[Path, Path], tmp_path: Path
) -> None:
    env, elf = bench
    without, _ = simulate(env, elf, scenario(duration_s=0.5), tmp_path / "without")
    with_sof, _ = simulate(env, elf, scenario(duration_s=0.5, usb_sof=True), tmp_path / "with")
    assert "USB_GEN" not in without["vectors"]
    # One frame a millisecond once the firmware has attached: after the 65 ms start-up and the
    # PLL's 10 ms lock, some 77 ms in.
    assert 410 <= with_sof["vectors"]["USB_GEN"]["count"] <= 430


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


def test_each_encoder_edge_comes_when_the_wheel_has_turned_half_a_count_past_the_last(
    bench: tuple[Path, Path], tmp_path: Path
) -> None:
    env, elf = bench
    # One motor revolution a second, 12 counts: count k is reached at (k - 0.5) / 12 s.
    encoders = {"left_rev_s": [[0, 1]], "right_rev_s": [[0, -1]]}
    _, trace = simulate(
        env, elf, scenario(duration_s=0.3, encoders=encoders, trace={"input_edges": True}), tmp_path
    )
    for side, sign in (("left", 1), ("right", -1)):
        edges = [e for e in trace if e["type"] == "input" and e["what"] == f"encoder_{side}"]
        assert [e["value"] for e in edges] == [sign * k for k in (1, 2, 3, 4)]
        # An edge is applied once the instruction under way, or an interrupt's entry, is done.
        for k, edge in enumerate(edges, start=1):
            assert 0 <= edge["c"] - _cycle((k - 0.5) / 12) <= 10, (side, k, edge)


def test_an_encoder_s_count_is_the_integral_of_its_rate_profile(
    bench: tuple[Path, Path], tmp_path: Path
) -> None:
    env, elf = bench
    # A ramp to 100 rev/s over 1 ms, then held: 12 * (0.05 + 100 * 0.199) = 239.4 counts by 0.2 s.
    encoders = {"left_rev_s": [[0, 0], [0.001, 100]]}
    summary, _ = simulate(env, elf, scenario(duration_s=0.2, encoders=encoders), tmp_path)
    assert summary["encoders"]["counts"]["left"] == 239
    assert summary["encoders"]["edges"]["left"] == 239


def test_a_short_stall_with_interrupts_off_loses_the_timer_ticks_it_held_off(
    bench: tuple[Path, Path], tmp_path: Path
) -> None:
    env, elf = bench
    # Two stalls of 30 ms, each inside the watchdog's 64 ms: nothing runs, then the firmware goes
    # on. TOV0 holds one overflow, so of the 29 that came in a stall one is served and millis()
    # falls some 28 ms behind each time: every later update is that much later than its
    # schedule. (Two stalls, so that one landing where the firmware already holds interrupts
    # off, as millis() does while it reads its count, cannot by itself make the row pass.)
    summary, trace = simulate(
        env,
        elf,
        scenario(
            stalls=[
                {"start_s": 0.3001, "end_s": 0.3301, "interrupts": False},
                {"start_s": 0.6003, "end_s": 0.6303, "interrupts": False},
            ]
        ),
        tmp_path,
    )
    assert [r["cause"] for r in summary["resets"]] == ["power_on"]
    assert _lines(summary)[-1] == f"G:{GYRO_Y} X:{ACCEL_X} A:0 L:0 R:0"
    assert summary["motors"]["left"]["last"] == COMMAND
    entries = [e["c"] for e in trace if e["type"] == "probe" and e["symbol"] == "update"]
    first, last = entries[0], entries[-1]
    behind = last - (first + (len(entries) - 1) * F / 100)
    assert _cycle(0.04) <= behind <= _cycle(0.06), behind / F


#: A sketch that takes 1800 bytes from the heap and then recurses some 40 frames deep.
HEAP = r"""#include <Arduino.h>
uint8_t *volatile buffer;
static volatile uint16_t sink;
__attribute__((noinline)) uint16_t deep(uint8_t d) {
  volatile uint8_t pad[20];
  pad[0] = d;
  return d ? deep(d - 1) + pad[0] : 0;
}
void setup() {
  buffer = (uint8_t *)malloc(1800);
  if (buffer) memset(buffer, 0x5a, 1800);
  sink = deep(40);
}
void loop() {}
"""


def test_a_stack_that_grows_into_the_heap_is_shown_as_a_collision(tmp_path: Path) -> None:
    # avr-libc's malloc() keeps the heap's end in __brkval: 1800 bytes and their two-byte size
    # past __heap_start. The recursion takes the stack below that end: the headroom is negative.
    env = environment()
    elf = build(env, tmp_path / "heap", HEAP)
    summary, _ = simulate(env, elf, {"avrsim_scenario": 1, "duration_s": 0.1}, tmp_path)
    stack = summary["stack"]
    assert stack["heap_end_max"] == stack["static_end"] + 2 + 1800
    assert stack["headroom_bytes"] == stack["min_sp"] - stack["heap_end_max"] < 0
    assert stack["collision"] is True


#: A sketch that prints on the USB serial port and reads the magnetometer: its identity, then
#: its field from OUT_X_L with the sub-address incrementing, as Pololu's LIS3MDL library does.
MAG = r"""#include <Arduino.h>
#include <Wire.h>
void setup() {
  Serial.begin(115200);
  Serial.println("hello");
  Serial.println("again");
  Serial.write('x');
  Serial1.begin(115200);
  Wire.begin();
  Wire.beginTransmission(0x1E);
  Wire.write(0x0F);
  Wire.endTransmission();
  Wire.requestFrom((uint8_t)0x1E, (uint8_t)1);
  uint8_t who = Wire.read();
  Serial1.print(F("WHO:"));
  Serial1.println(who);
  delay(5);
  Wire.beginTransmission(0x1E);
  Wire.write(0x28 | 0x80);
  Wire.endTransmission();
  Wire.requestFrom((uint8_t)0x1E, (uint8_t)6);
  int16_t x = Wire.read() | (Wire.read() << 8);
  Serial1.print(F("X:"));
  Serial1.println(x);
}
void loop() {}
"""


def test_a_firmware_that_reads_the_magnetometer_is_not_shown_a_zero_field(tmp_path: Path) -> None:
    # The part answers its identity (0x3D) as on the board; its field is not modelled, so the
    # first byte of OUT_X_L ends the evidence rather than reading zero on three axes without
    # noise, and the summary names it. Serial's writes to a USB with no host, of a buffer and of
    # a byte, are counted.
    env = environment()
    elf = build(env, tmp_path / "mag", MAG)
    summary, _ = simulate(env, elf, {"avrsim_scenario": 1, "duration_s": 0.3}, tmp_path)
    assert summary["usart1"]["text"].startswith("WHO:61")
    end = summary["evidence_end"]
    assert end is not None and end["cause"] == "lis3mdl_data" and end["register"] == 0x28
    assert "X:" not in summary["usart1"]["text"]
    assert "lis3mdl_data" in summary["unmodelled"]
    assert summary["simulated_cycles"] < 0.3 * F
    assert (summary["timing_evaluable"], summary["behaviour_evaluable"]) == (False, False)
    assert summary["usb"]["host"] == "none" and summary["usb"]["serial_write_calls"] >= 3
