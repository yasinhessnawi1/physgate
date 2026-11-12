"""No session uploads or flashes to hardware, or opens a serial device, by any door it has.

Three doors, one rule: a shell command, a file tool's path, and the arguments of a tool
server's tool. Every refused row has an allowed twin close to it, so a rule that matched
text where it should match commands, or every device where it should match serial ones,
fails the twin. The OS layer denies the same devices, from the same table, to what no text
shows: a path a program builds as it runs is a strict expected failure here, so the day a
text layer closes it the test says so.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from hook_helpers import bash, event, write_config

from physgate.hooks import hardware
from physgate.hooks.config import HookInput
from physgate.hooks.registry import REGISTRY
from physgate.hooks.runtime import dispatch
from physgate.hooks.state import LOG_NAME
from physgate.oslayer.policy import board_devices, sandbox_policy

H = hardware

UPLOADS = [
    "pio run -t upload",
    "pio run --target upload",
    "pio run --target=upload",
    "pio run -tupload",
    "pio run -e balboa -t upload",
    "pio run -t clean -t upload",
    "platformio run -t upload",
    "/opt/env/venv/bin/pio run -t upload",
    "PIO run -T UPLOAD",
    "pio run -t uploadfs",
    "pio run -t uploadfsota",
    "pio run -t program",
    "pio run -t fuses",
    "pio run -t bootloader",
    "pio run -t erase",
    "pio run -t uploadeep",
    "pio remote run -t upload",
    "pio run -- -t upload",
    "pio device monitor",
    "pio device monitor -b 115200",
    "pio remote device monitor",
    "avrdude -p atmega32u4 -c avr109 -U flash:w:firmware.hex",
    "avrdude -v",
    # Through each door a shell offers a command.
    "cd modules/firmware && pio run -t upload",
    "pio run && pio run -t upload",
    "env X=1 pio run -t upload",
    "nohup pio run -t upload",
    "command pio run -t upload",
    "timeout 60 pio run -t upload",
    "uv run pio run -t upload",
    "find . -name platformio.ini -exec pio run -t upload ;",
    "echo x | xargs avrdude",
    "sh -c 'pio run -t upload'",
    "bash -lc 'ls; pio run -t upload'",
    "timeout 5 sh -c 'pio run -t upload'",
    'eval "pio run -t upload"',
    "echo $(pio run -t upload)",
    "echo `avrdude -v`",
    "{ pio run -t upload; }",
    "if pio run -t upload; then echo done; fi",
    "sh <<EOF\npio run -t upload\nEOF",
    "python3 -m platformio run -t upload",
    "python3 -mplatformio run -t upload",
    "trap 'pio run -t upload' EXIT",
    # The program named only when the command runs, given an upload target all the same.
    "p=pio; $p run -t upload",
]

NOT_UPLOADS = [
    "pio run",
    "pio run -e balboa",
    "pio run -t clean",
    "pio run -t size",
    "pio run --target=buildprog",
    "pio run -d modules/firmware",
    "pio check",
    "pio device list",
    "pio pkg list",
    "esptool version",
    "esptool.py image_info firmware.bin",
    "esptool.py elf2image firmware.elf",
    "esptool merge_bin -o all.bin 0x0 a.bin",
    "pio",
    "pio --version",
    "pio -h",
    "pio run -t buildprog",
    "pio run -t cleanall",
    "pio run -t checkprogsize",
    "pio run -t buildfs",
    "pio settings get",
    "pio pkg show",
    "pio pkg outdated",
    "pio pkg search balboa",
    "esptool.py image-info firmware.bin",
    "esptool merge-bin -o all.bin 0x0 a.bin",
    "pio run -t compiledb",
    "pio run -t envdump",
    "pio check --skip-packages",
    "pio system info",
    "pio project config",
    "pio boards atmelavr",
    "pio test --without-uploading --without-testing",
    "pio -c vscode run",
    "arduino-cli compile --fqbn pololu:avr:a-star32U4 .",
    "arduino-cli version",
    "esptool.py",
    "esptool.py --help",
    "which openocd",
    "echo dfu-util",
    "python3 -m platformio run",
    "python3 analysis.py",
    # Text that names an upload is text.
    "echo pio run -t upload",
    "echo 'avrdude writes the flash'",
    "grep -rn 'pio run -t upload' docs/",
    "which avrdude",
    "ls upload",
    "make upload-notes.md",
    "# pio run -t upload\nls",
    "cat > notes.md <<'EOF'\nNever run pio run -t upload or avrdude here.\nEOF\n",
    "python3 -c \"print('pio run -t upload')\"",
    "printf '%s\\n' 'esptool.py write_flash'",
]

#: Programs that only ever reach a board, each as it is usually run.
FLASHERS = [
    "avrdude -c avr109",
    "dfu-util -l",
    "dfu-programmer atmega32u4 erase",
    "bossac -i",
    "openocd -f board.cfg",
    "st-flash write firmware.bin 0x8000000",
    "st-info --probe",
    "pyocd flash firmware.elf",
    "teensy_loader_cli --mcu=TEENSY40 firmware.hex",
    "picotool load firmware.uf2",
    "stm32flash -w firmware.bin",
    "JLinkExe -device ATSAMD21",
    "nrfjprog --program firmware.hex",
    "micronucleus firmware.hex",
    "timeout 30 openocd -f board.cfg",
    "sh -c 'dfu-util -D firmware.bin'",
]

#: A use of a guarded program that is not one of its build-only uses, with the program.
NOT_BUILD_ONLY = [
    ("pio test", "pio"),
    ("pio test -e balboa", "pio"),
    ("pio test --without-uploading", "pio"),
    ("pio test --without-testing", "pio"),
    ("pio debug", "pio"),
    ("pio debug --interface=gdb", "pio"),
    ("pio remote run", "pio"),
    ("pio remote test", "pio"),
    ("pio pkg exec -- avrdude -v", "pio"),
    ("pio pkg exec -p tool-openocd -- openocd", "pio"),
    ("pio pkg install -g -t tool-avrdude", "pio"),
    ("pio home", "pio"),
    ("pio upgrade", "pio"),
    ("pio ci src/main.cpp", "pio"),
    ("pio device", "pio"),
    ("pio settings set enable_telemetry yes", "pio"),
    ("pio account login", "pio"),
    ("pio run -t monitor", "pio"),
    ("pio run -t custom_flash", "pio"),
    ("pio run -t size -t monitor", "pio"),
    ("pio run --upload-port COM3", "pio"),
    ("pio run --monitor-port=COM3", "pio"),
    ("pio -c vscode debug", "pio"),
    ("pio --caller vscode test", "pio"),
    ("platformio debug", "platformio"),
    ("python3 -m platformio debug", "platformio"),
    ("timeout 60 pio test", "pio"),
    ("sh -c 'pio debug'", "pio"),
    ("esptool write_flash 0x1000 firmware.bin", "esptool"),
    ("esptool.py --chip esp32 write_flash 0x1000 firmware.bin", "esptool.py"),
    ("esptool.py erase_flash", "esptool.py"),
    ("esptool write-flash 0x1000 firmware.bin", "esptool"),
    ("esptool erase-flash", "esptool"),
    ("esptool.py chip_id", "esptool.py"),
    ("esptool.py read_flash 0 0x1000 dump.bin", "esptool.py"),
    ("esptool.py write_mem 0x400 1", "esptool.py"),
    ("bash <<'EOF'\nesptool.py erase_flash\nEOF", "esptool.py"),
    ("python -m esptool write_flash 0 firmware.bin", "esptool"),
    ("arduino-cli upload -p COM3", "arduino-cli"),
    ("arduino-cli compile -u --fqbn x:y:z .", "arduino-cli"),
    ("arduino-cli compile --upload .", "arduino-cli"),
    ("arduino-cli compile --port COM3 .", "arduino-cli"),
    ("arduino-cli monitor", "arduino-cli"),
    ("arduino-cli compile -p COM3 .", "arduino-cli"),
    ("arduino-cli compile -P avrisp .", "arduino-cli"),
    ("arduino-cli compile --programmer avrisp .", "arduino-cli"),
    ("esptool.py --port COM3 version", "esptool.py"),
    ("esptool -p COM3 image_info firmware.bin", "esptool"),
    ("pio pkg -c exec list", "pio"),
    # A word this rule does not read exactly as the program does is refused, not guessed:
    # short options run together, an option it has not been told of, a bare "--".
    ("pio run -vt upload", "pio"),
    ("pio run -st upload", "pio"),
    ("pio run -vtupload", "pio"),
    ("pio run -ve balboa", "pio"),
    ("pio run --no-such-option", "pio"),
    ("pio run extra", "pio"),
    ("pio run -- extra", "pio"),
    ("pio run -t", "pio"),
    ("pio run -t=size", "pio"),
    ("pio run --silent=1", "pio"),
    ("pio --no-such-global run", "pio"),
    ("pio check --upload-port=COM3", "pio"),
    ("pio test --without-uploading --without-testing --upload-port COM3", "pio"),
    ("arduino-cli --additional-urls compile upload", "arduino-cli"),
    ("arduino-cli --config-file x.yaml compile .", "arduino-cli"),
    ("arduino-cli compile -vu .", "arduino-cli"),
    ("arduino-cli compile -vp COM3 .", "arduino-cli"),
    ("arduino-cli compile --no-such-option .", "arduino-cli"),
    # An option that rewrites what a build runs is not a build-only option.
    (
        "arduino-cli compile --build-property recipe.hooks.prebuild.1.pattern=avrdude .",
        "arduino-cli",
    ),
    ("arduino-cli compile --build-property=tools.avrdude.path=/x .", "arduino-cli"),
    ("arduino-cli compile --build-properties compiler.path=/x .", "arduino-cli"),
    ("pio run -O upload_command=avrdude", "pio"),
    ("pio run --project-option extra_scripts=flash.py", "pio"),
    ("pio run --project-option=targets=upload", "pio"),
    ("esptool.py --no-such-global version", "esptool.py"),
    ("esptool.py image_info --no-such-option firmware.bin", "esptool.py"),
    ("arduino-cli burn-bootloader", "arduino-cli"),
    ("arduino-cli debug", "arduino-cli"),
    ("arduino-cli board list", "arduino-cli"),
]

#: A device named from where the command runs: the call's own directory, and each one a
#: command of the call moves to. Each row: the call's directory, the command, the name read.
RELATIVE = [
    ("/", "cat dev/ttyACM0", "dev/ttyACM0"),
    ("/", "cat ./dev/cu.usbmodem1", "./dev/cu.usbmodem1"),
    ("/dev", "cat ttyACM0", "ttyACM0"),
    ("/dev", "cat ./cu.usbmodem1", "./cu.usbmodem1"),
    ("/dev", "echo AT > ttyUSB0", "ttyUSB0"),
    ("/usr", "cat ../dev/ttyACM0", "../dev/ttyACM0"),
    (None, "cd / && cat dev/ttyACM0", "dev/ttyACM0"),
    (None, "cd /; cat dev/cu.usbmodem1", "dev/cu.usbmodem1"),
    (None, "(cd / && cat dev/ttyUSB0)", "dev/ttyUSB0"),
    (None, "pushd / && cat dev/ttyUSB0", "dev/ttyUSB0"),
    (None, "cd /usr && cd .. && cat dev/ttyUSB0", "dev/ttyUSB0"),
    (None, "cd /usr/.. && cat dev/ttyUSB0", "dev/ttyUSB0"),
    (None, "sh -c 'cd / && cat dev/ttyACM0'", "dev/ttyACM0"),
    (None, "cd /usr && cat ../dev/hidraw0", "../dev/hidraw0"),
    # Where a command moves is known only when it runs: anywhere, the devices' directory
    # and the one above it among them.
    (None, "cd $WHERE && cat dev/ttyACM0", "dev/ttyACM0"),
    (None, "cd $WHERE && cat ttyACM0", "ttyACM0"),
    (None, 'cd "$(pwd)/.." && cat dev/ttyACM0', "dev/ttyACM0"),
    (None, "cd - && cat ttyUSB0", "ttyUSB0"),
    (None, "cd && cat cu.usbmodem1", "cu.usbmodem1"),
    (None, "cd ~ && cat ttyACM0", "ttyACM0"),
    (None, "cd ./$WHERE && cat ttyACM0", "./$WHERE"),
    (None, "cd ./d* && cat ttyACM0", "ttyACM0"),
    # A directory on the way to a device is one of the places a command could be anywhere.
    (None, "cd $WHERE && cat usb/001/004", "usb/001/004"),
    (None, "cd $WHERE && ls bus/usb", "bus/usb"),
    # After a second move, or one a search path could send elsewhere, nothing is followed.
    (None, "cd modules && cat ttyACM0", "ttyACM0"),
    (None, "cd ./a && cd ./b && cat ttyACM0", "ttyACM0"),
    (None, "cd .. && cat ttyACM0", "ttyACM0"),
    (None, "cd ./a/../b && cat ttyACM0", "ttyACM0"),
    (None, "cd / && cd dev && cat ttyACM0", "ttyACM0"),
    (None, "cd / && cd ./dev && cat ttyACM0", "ttyACM0"),
    ("/", "cd dev && cat ttyACM0", "ttyACM0"),
    # A search path sends a bare relative move wherever it says.
    (None, "CDPATH=/ cd dev && cat ttyACM0", "ttyACM0"),
    (None, "export CDPATH=/; cd dev; cat ttyACM0", "ttyACM0"),
    (None, "CDPATH=/dev cd bus && cat usb/001/001", "usb/001/001"),
]
ENTERS_BY_STEPS = [
    ("/usr", "cd ../dev"),
    ("/", "cd ./dev"),
    (None, "cd /dev/bus && ls"),
    (None, "cd /dev/bus/usb"),
    (None, "cd /tmp && cd /dev"),
]
NOT_RELATIVE = [
    (None, "cat dev/ttyACM0"),
    (None, "cat ttyACM0"),
    (None, "cd ./modules && cat dev/tty.c"),
    (None, "cd ./dev && cat ttyACM0"),
    (None, "cd modules/firmware && pio run"),
    (None, "cd modules && cat src/main.cpp"),
    (None, "cd /tmp && cat dev/ttyACM0"),
    (None, "cd / && cat tmp/ttyACM0"),
    (None, "cd / && ls dev/null"),
    ("/usr", "cat dev/ttyACM0"),
    ("/", "ls dev"),
    ("/dev", "cat /tty.c"),
    (None, "cd $WHERE && echo $NAME"),
    # A move alone opens nothing, and after one an ordinary name is still ordinary.
    (None, "cd dev"),
    (None, "cd bus && ls"),
    (None, "cd ./a && cd .. && ls src"),
    (None, "cd .. && ls src"),
    (None, "cd ../other && cat src/main.c"),
    (None, "CDPATH=/ cd dev && cat x"),
]

UNREAD = [
    "pio run -t $TARGET",
    "pio run $FLAGS",
    "pio $SUB -t upload_later",
    "esptool.py $WHAT 0 firmware.bin",
    "pio run -d build_*",
]

DEVICES = [
    ("cat /dev/cu.usbmodem14101", "/dev/cu.usbmodem14101"),
    ("cat /dev/tty.usbserial-A1", "/dev/tty.usbserial-A1"),
    ("cat /dev/ttyACM0", "/dev/ttyACM0"),
    ("cat /dev/ttyUSB0", "/dev/ttyUSB0"),
    ("cat /dev/hidraw0", "/dev/hidraw0"),
    ("ls /dev/bus/usb", "/dev/bus/usb"),
    ("cat /dev/bus/usb/001/004", "/dev/bus/usb/001/004"),
    ("ls /dev/bus/*", "/dev/bus/*"),
    ("echo AT > /dev/ttyUSB0", "/dev/ttyUSB0"),
    ("exec 3<> /dev/cu.usbmodem1", "/dev/cu.usbmodem1"),
    ("stty -f /dev/cu.usbmodem1 115200", "/dev/cu.usbmodem1"),
    ("screen /dev/tty.usbserial 9600", "/dev/tty.usbserial"),
    ("dd if=firmware.bin of=/dev/ttyACM0", "/dev/ttyACM0"),
    ("socat - /dev/ttyUSB0,raw,echo=0", "/dev/ttyUSB0"),
    ("PORT=/dev/ttyACM0 make flash", "/dev/ttyACM0"),
    ("miniterm -p/dev/ttyUSB0", "-p/dev/ttyUSB0"),
    ("python3 -c \"open('/dev/cu.usbmodem1')\"", "/dev/cu.usbmodem1"),
    ("python3 - <<'EOF'\nimport serial\nserial.Serial('/dev/ttyACM0')\nEOF", "/dev/ttyACM0"),
    ("cat > platformio.ini <<EOF\nupload_port = /dev/ttyACM0\nEOF", "/dev/ttyACM0"),
    ("ls -l /dev/cu.usbmodem1", "/dev/cu.usbmodem1"),
    # Spellings of the same device.
    ("cat /DEV/CU.usbmodem1", "/DEV/CU.usbmodem1"),
    ("cat //dev/cu.usbmodem1", "//dev/cu.usbmodem1"),
    ("cat /dev/./cu.usbmodem1", "/dev/./cu.usbmodem1"),
    ("cat /dev/../dev/ttyACM0", "/dev/../dev/ttyACM0"),
    ("cat /tmp/../dev/ttyACM0", "/tmp/../dev/ttyACM0"),
    ("cat ../../../dev/ttyACM0", "../../../dev/ttyACM0"),
    ("cat /dev/c'u'.usbmodem1", "/dev/cu.usbmodem1"),
    ("cat $'/dev/cu\\x2eusbmodem1'", "/dev/cu.usbmodem1"),
    # Patterns that could expand to one.
    ("cat /dev/cu.*", "/dev/cu.*"),
    ("cat /dev/tty*", "/dev/tty*"),
    ("cat /dev/*", "/dev/*"),
    ("cat /dev/t?yUSB0", "/dev/t?yUSB0"),
    ("cat /d?v/ttyUSB0", "/d?v/ttyUSB0"),
    ("cat /dev/$NAME", "/dev/$NAME"),
    ("cat /dev/[ct]u.x", "/dev/[ct]u.x"),
    ("cat /dev/{null,ttyACM0}", "/dev/ttyACM0"),
    ("cat /{dev,tmp}/ttyUSB0", "/dev/ttyUSB0"),
    ("echo x > /{tmp,dev}/ttyUSB0", "/dev/ttyUSB0"),
    ("cat /$ROOT/ttyUSB0", "/$ROOT/ttyUSB0"),
]

NOT_DEVICES = [
    "cat /dev/null",
    "echo x > /dev/null",
    "tty < /dev/tty",
    "head -c 8 /dev/urandom",
    "ls /dev/fd",
    "cat /dev/stdin",
    "ls /dev/n*",
    "ls /dev/bus",
    "ls /dev/bus/pci",
    "gcc -c src/dev/tty.c",
    "cat ./dev/cu.h",
    "cat ~/dev/tty.notes",
    "cat $HOME/dev/tty.notes",
    "ls dev/",
    "cd ./dev && ls",
    "cat docs/ttyUSB-notes.md",
    "echo ttyACM0",
]

ENTERS = [
    "cd /dev && cat cu.usbmodem1",
    "cd /dev/ && ls",
    "pushd /dev",
    "chdir /dev",
    "cd /tmp/../dev",
    "cd ../../../dev",
    "cd /DEV",
]


def _config(tmp: Path, profile: str = "role") -> Any:  # noqa: ANN401 - the session's model
    return write_config(tmp, profile=profile)[2]


def _shell(tmp: Path, command: str, profile: str = "role", cwd: str | None = None) -> str:
    config = _config(tmp, profile)
    hook_input = HookInput.model_validate(bash(command, cwd=cwd or config.worktree))
    decision = H.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


def _tool(tmp: Path, tool: str, tool_input: dict[str, Any], cwd: str | None = None) -> str:
    config = _config(tmp)
    hook_input = HookInput.model_validate(
        event(tool_name=tool, cwd=cwd or config.worktree, tool_input=tool_input)
    )
    decision = H.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


# ---- the shell --------------------------------------------------------------------------


@pytest.mark.parametrize("command", UPLOADS, ids=UPLOADS)
def test_a_command_that_uploads_or_flashes_is_refused(tmp_path: Path, command: str) -> None:
    assert _shell(tmp_path, command) == H.UPLOAD


@pytest.mark.parametrize("command", NOT_UPLOADS, ids=NOT_UPLOADS)
def test_a_build_and_text_that_names_an_upload_pass(tmp_path: Path, command: str) -> None:
    assert _shell(tmp_path, command) == "allow"


@pytest.mark.parametrize("command", FLASHERS, ids=FLASHERS)
def test_a_program_that_only_ever_reaches_a_board_is_refused(tmp_path: Path, command: str) -> None:
    assert _shell(tmp_path, command) == H.UPLOAD


@pytest.mark.parametrize(("command", "program"), NOT_BUILD_ONLY, ids=[c for c, _ in NOT_BUILD_ONLY])
def test_a_use_of_a_guarded_program_that_is_not_build_only_is_refused(
    tmp_path: Path, command: str, program: str
) -> None:
    assert _shell(tmp_path, command) == H.NOT_BUILD.format(program=program)


@pytest.mark.parametrize(("cwd", "command", "device"), RELATIVE, ids=[c for _, c, _ in RELATIVE])
def test_a_device_named_from_where_the_command_runs_is_refused(
    tmp_path: Path, cwd: str | None, command: str, device: str
) -> None:
    assert _shell(tmp_path, command, cwd=cwd) == H.DEVICE.format(device=device)


@pytest.mark.parametrize(("cwd", "command"), ENTERS_BY_STEPS, ids=[c for _, c in ENTERS_BY_STEPS])
def test_reaching_the_devices_directory_in_steps_is_refused(
    tmp_path: Path, cwd: str | None, command: str
) -> None:
    assert "the devices' directory" in _shell(tmp_path, command, cwd=cwd)


@pytest.mark.parametrize(("cwd", "command"), NOT_RELATIVE, ids=[c for _, c in NOT_RELATIVE])
def test_a_relative_name_that_lands_elsewhere_passes(
    tmp_path: Path, cwd: str | None, command: str
) -> None:
    assert _shell(tmp_path, command, cwd=cwd) == "allow"


def _linked_at_the_root() -> str | None:
    """A directory at the root that is a link to one deeper down, if this machine has one."""
    for name in sorted(os.listdir("/")):
        path = "/" + name
        deeper = os.path.dirname(os.path.realpath(path)) != "/"
        if os.path.islink(path) and os.path.isdir(path) and deeper:
            return path
    return None


def test_a_move_upwards_is_not_followed_since_the_shell_and_the_kernel_may_differ(
    tmp_path: Path,
) -> None:
    # The shell climbs from the directory as it was named, the kernel from where it really
    # is; from a linked directory at the root the first is the root and the second is not.
    linked = _linked_at_the_root()
    if linked is None:
        pytest.skip("no directory at the root of this machine is a link to a deeper one")
    assert os.path.dirname(os.path.realpath(linked)) != "/"
    reason = _shell(tmp_path, "cd .. && cat dev/ttyACM0", cwd=linked)
    assert reason == H.DEVICE.format(device="dev/ttyACM0")
    reason = _shell(tmp_path, "cd ./../ && cat dev/ttyACM0", cwd=linked)
    assert reason == H.DEVICE.format(device="dev/ttyACM0")


def test_the_call_s_directory_is_read_as_it_resolves(tmp_path: Path) -> None:
    link = tmp_path / "top"
    os.symlink("/", link)
    reason = _shell(tmp_path, "cat dev/ttyACM0", cwd=str(link))
    assert reason == H.DEVICE.format(device="dev/ttyACM0")


@pytest.mark.parametrize("command", UNREAD, ids=UNREAD)
def test_a_word_only_running_decides_is_refused_in_a_command_that_can_upload(
    tmp_path: Path, command: str
) -> None:
    assert _shell(tmp_path, command) == H.DYNAMIC


@pytest.mark.parametrize(("command", "device"), DEVICES, ids=[c for c, _ in DEVICES])
def test_a_command_that_names_a_serial_device_is_refused(
    tmp_path: Path, command: str, device: str
) -> None:
    assert _shell(tmp_path, command) == H.DEVICE.format(device=device)


@pytest.mark.parametrize("command", NOT_DEVICES, ids=NOT_DEVICES)
def test_another_device_and_a_file_named_like_one_pass(tmp_path: Path, command: str) -> None:
    assert _shell(tmp_path, command) == "allow"


@pytest.mark.parametrize("command", ENTERS, ids=ENTERS)
def test_moving_into_the_devices_directory_is_refused(tmp_path: Path, command: str) -> None:
    reason = _shell(tmp_path, command)
    assert reason.startswith("Opening a board's device is refused")
    assert "the devices' directory" in reason


@pytest.mark.parametrize("profile", ["role", "baseline", "orchestrator", "reviewer"])
def test_every_profile_is_refused(tmp_path: Path, profile: str) -> None:
    assert _shell(tmp_path, "pio run -t upload", profile) == H.UPLOAD
    assert _shell(tmp_path, "cat /dev/ttyACM0", profile) == H.DEVICE.format(device="/dev/ttyACM0")


def test_an_upload_refusal_wins_over_nothing_and_a_device_is_named_first(tmp_path: Path) -> None:
    # Both faults at once: the device is what the reason names, so a session is told the
    # thing no rewording of the command would get past.
    reason = _shell(tmp_path, "pio run -t upload --upload-port /dev/ttyACM0")
    assert reason == H.DEVICE.format(device="/dev/ttyACM0")


@pytest.mark.xfail(strict=True, reason="a path a program builds as it runs is the OS layer's")
def test_a_path_built_at_run_time_is_seen_by_the_text_rule(tmp_path: Path) -> None:
    built = "python3 -c \"import os; open(os.sep.join(['', 'dev', 'tty' + 'ACM0']))\""
    assert _shell(tmp_path, built) != "allow"


@pytest.mark.xfail(strict=True, reason="an upload a program starts itself is the OS layer's")
def test_an_upload_a_program_starts_itself_is_seen_by_the_text_rule(tmp_path: Path) -> None:
    started = (
        "python3 - <<'EOF'\nimport subprocess\n"
        "subprocess.run(['pio', 'run', '-t', 'up' + 'load'])\nEOF"
    )
    assert _shell(tmp_path, started) != "allow"


# ---- the file tools ---------------------------------------------------------------------

FILE_TOOLS = [
    ("Read", "file_path"),
    ("Write", "file_path"),
    ("Edit", "file_path"),
    ("NotebookEdit", "notebook_path"),
]
DEVICE_PATHS = [
    "/dev/cu.usbmodem14101",
    "/dev/tty.usbserial-A1",
    "/dev/ttyACM0",
    "/dev/ttyUSB3",
    "/DEV/TTYACM0",
    "//dev/ttyACM0",
    "/dev/../dev/ttyACM0",
    "/tmp/../dev/cu.usbmodem1",
]


@pytest.mark.parametrize(("tool", "key"), FILE_TOOLS)
@pytest.mark.parametrize("path", DEVICE_PATHS)
def test_a_file_tool_on_a_serial_device_is_refused(
    tmp_path: Path, tool: str, key: str, path: str
) -> None:
    assert _tool(tmp_path, tool, {key: path}) == H.DEVICE.format(device=path)


@pytest.mark.parametrize(("tool", "key"), FILE_TOOLS)
def test_a_relative_path_is_judged_from_the_call_s_directory(
    tmp_path: Path, tool: str, key: str
) -> None:
    assert _tool(tmp_path, tool, {key: "ttyACM0"}, cwd="/dev") != "allow"
    assert _tool(tmp_path, tool, {key: "../../dev/ttyACM0"}, cwd="/usr/lib") != "allow"
    assert _tool(tmp_path, tool, {key: "ttyACM0"}) == "allow"


@pytest.mark.parametrize(("tool", "key"), FILE_TOOLS)
def test_a_link_to_a_serial_device_is_refused_as_the_device(
    tmp_path: Path, tool: str, key: str
) -> None:
    link = tmp_path / "port"
    os.symlink("/dev/ttyACM0", link)
    assert _tool(tmp_path, tool, {key: str(link)}) == H.DEVICE.format(device=str(link))


@pytest.mark.parametrize(("tool", "key"), FILE_TOOLS)
@pytest.mark.parametrize("path", ["/dev/null", "src/dev/tty.c", "dev/cu.h", "notes/ttyUSB0.md"])
def test_a_file_tool_on_anything_else_passes(
    tmp_path: Path, tool: str, key: str, path: str
) -> None:
    assert _tool(tmp_path, tool, {key: path}) == "allow"


def test_what_a_file_tool_writes_is_not_judged_only_where(tmp_path: Path) -> None:
    content = "upload_port = /dev/ttyACM0\n; pio run -t upload\n"
    assert _tool(tmp_path, "Write", {"file_path": "notes.md", "content": content}) == "allow"


# ---- a tool server's arguments ----------------------------------------------------------

SERVER_TOOL = "mcp__platformio__build_project"
REFUSED_ARGUMENTS: list[tuple[dict[str, Any], str]] = [
    ({"projectDir": "/w/modules/firmware", "target": "upload"}, H.UPLOAD),
    ({"projectDir": "/w/modules/firmware", "Target": "UPLOAD"}, H.UPLOAD),
    ({"projectDir": "/w/modules/firmware", "targets": ["size", "uploadfs"]}, H.UPLOAD),
    ({"build_targets": {"first": "erase"}}, H.UPLOAD),
    ({"args": ["run", "-t", "upload"]}, H.UPLOAD),
    ({"args": ["run", "--target=program"]}, H.UPLOAD),
    ({"options": {"extra": [["-t", "upload"]]}}, H.UPLOAD),
    ({"command": "pio run -t upload"}, H.UPLOAD),
    ({"flags": "--environment balboa --target upload"}, H.UPLOAD),
    ({"command": "avrdude -p m32u4"}, H.UPLOAD),
    (
        {"argv": ["esptool.py", "write_flash", "0", "x.bin"]},
        H.NOT_BUILD.format(program="esptool.py"),
    ),
    ({"command": "pio device monitor"}, H.UPLOAD),
    ({"command": "pio debug"}, H.NOT_BUILD.format(program="pio")),
    ({"argv": ["pio", "test"]}, H.NOT_BUILD.format(program="pio")),
    ({"command": "openocd -f board.cfg"}, H.UPLOAD),
    ({"device": "/dev/hidraw2"}, H.DEVICE.format(device="/dev/hidraw2")),
    ({"port": "/dev/ttyACM0"}, H.DEVICE.format(device="/dev/ttyACM0")),
    ({"upload_port": "/dev/cu.usbmodem1"}, H.DEVICE.format(device="/dev/cu.usbmodem1")),
    ({"a": {"b": [{"c": "see /dev/tty.usbserial"}]}}, H.DEVICE.format(device="/dev/tty.usbserial")),
    ({"/dev/ttyUSB0": True}, H.DEVICE.format(device="/dev/ttyUSB0")),
    ({"model_path": "/DEV/../dev/ttyUSB0"}, H.DEVICE.format(device="/DEV/../dev/ttyUSB0")),
]
ALLOWED_ARGUMENTS: list[dict[str, Any]] = [
    {"projectDir": "/w/modules/firmware", "environment": "balboa"},
    {"projectDir": "/w/modules/firmware", "target": "size"},
    {"projectDir": "/w/modules/upload"},
    {"note": "upload"},
    {"transfer_function": {"numerator": [4, 4], "denominator": [1, 2, 1, 0]}},
    {"xml": "<mujoco><worldbody><body pos='0 0 1'/></worldbody></mujoco>", "steps": 500},
    {"model_path": "/w/modules/control/dev/tty.xml"},
    {"args": ["run", "-t", "size"]},
    {},
]


@pytest.mark.parametrize(("arguments", "reason"), REFUSED_ARGUMENTS, ids=repr)
def test_a_server_tool_asked_for_an_upload_or_a_device_is_refused(
    tmp_path: Path, arguments: dict[str, Any], reason: str
) -> None:
    assert _tool(tmp_path, SERVER_TOOL, arguments) == reason


@pytest.mark.parametrize("arguments", ALLOWED_ARGUMENTS, ids=repr)
def test_a_server_tool_asked_for_a_build_or_a_computation_passes(
    tmp_path: Path, arguments: dict[str, Any]
) -> None:
    assert _tool(tmp_path, SERVER_TOOL, arguments) == "allow"


def test_arguments_nested_past_the_bound_are_refused_and_at_it_are_read(tmp_path: Path) -> None:
    def nested(depth: int, inner: object) -> dict[str, Any]:
        value: object = inner
        for _ in range(depth):
            value = {"k": value}
        assert isinstance(value, dict)
        return value

    at_the_bound = nested(H.MAX_DEPTH, "balboa")
    past_it = nested(H.MAX_DEPTH + 1, "balboa")
    assert _tool(tmp_path, SERVER_TOOL, at_the_bound) == "allow"
    reason = _tool(tmp_path, SERVER_TOOL, past_it)
    assert reason == H.UNREADABLE.format(detail=f"nested more than {H.MAX_DEPTH} deep")
    # At the bound the innermost string is still read.
    assert _tool(tmp_path, SERVER_TOOL, nested(H.MAX_DEPTH, "/dev/ttyACM0")) == H.DEVICE.format(
        device="/dev/ttyACM0"
    )


def test_only_a_server_s_tool_has_its_arguments_read_as_text(tmp_path: Path) -> None:
    # A task list entry that mentions a port is a note, not a call that opens one.
    noted = {"todos": [{"content": "document /dev/ttyACM0 and pio run -t upload"}]}
    assert _tool(tmp_path, "TodoWrite", noted) == "allow"
    assert _tool(tmp_path, "mcp__anything__at_all", noted) != "allow"


# ---- wired, and one table for both layers -----------------------------------------------


def test_the_rule_runs_with_every_other_hook_and_its_refusal_is_recorded(tmp_path: Path) -> None:
    _, _, config = write_config(tmp_path)
    assert "hardware" in REGISTRY
    hook_input = HookInput.model_validate(bash("pio run -t upload", cwd=config.worktree))
    decision = dispatch([REGISTRY["tools"], REGISTRY["hardware"]], hook_input, config)
    assert not decision.allow and decision.reason == H.UPLOAD
    log = (Path(config.state_dir) / LOG_NAME).read_text()
    assert '"hook": "hardware"' in log and "Uploading or flashing" in log


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("darwin", ["/dev/cu.*", "/dev/tty.*"]),
        ("linux", ["/dev/bus/usb", "/dev/hidraw*", "/dev/ttyACM*", "/dev/ttyUSB*"]),
    ],
)
def test_the_os_layer_denies_the_platform_s_board_devices_both_ways(
    tmp_path: Path, platform: str, expected: list[str]
) -> None:
    _, _, config = write_config(tmp_path)
    home, temp = tmp_path / "home", tmp_path / "t"
    home.mkdir()
    temp.mkdir()
    policy = sandbox_policy(config, home=str(home), temp_dir=str(temp), platform=platform)
    filesystem = policy.settings["sandbox"]["filesystem"]
    assert list(board_devices(platform)) == expected
    assert board_devices("linux2") == board_devices("linux")
    assert board_devices("win32") == ()
    for kind in ("denyRead", "denyWrite"):
        assert [p for p in filesystem[kind] if p.startswith("/dev/")] == expected
    assert not [p for p in filesystem["allowRead"] + filesystem["allowWrite"] if "/dev/" in p]


def test_every_device_the_os_layer_denies_is_one_the_hooks_refuse_by_name(tmp_path: Path) -> None:
    patterns = [p for platform in ("darwin", "linux") for p in board_devices(platform)]
    assert len(patterns) == 6
    for pattern in patterns:
        device = pattern.replace("*", "board1")
        assert H.serial_device_in(f"cat {device}") == device
        assert H.serial_device_in(pattern) == pattern
        assert _tool(tmp_path, "Read", {"file_path": device}) == H.DEVICE.format(device=device)
