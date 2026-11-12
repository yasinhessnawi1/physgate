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
from physgate.oslayer.policy import sandbox_policy, serial_devices

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
    "pio device monitor",
    "pio device monitor -b 115200",
    "pio remote device monitor",
    "avrdude -p atmega32u4 -c avr109 -U flash:w:firmware.hex",
    "avrdude -v",
    "esptool write_flash 0x1000 firmware.bin",
    "esptool.py --chip esp32 write_flash 0x1000 firmware.bin",
    "esptool.py erase_flash",
    "esptool write-flash 0x1000 firmware.bin",
    "esptool erase-flash",
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
    "bash <<'EOF'\nesptool.py erase_flash\nEOF",
    "python3 -m platformio run -t upload",
    "python -m esptool write_flash 0 firmware.bin",
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
    "esptool.py chip_id",
    "esptool version",
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
]

NOT_DEVICES = [
    "cat /dev/null",
    "echo x > /dev/null",
    "tty < /dev/tty",
    "head -c 8 /dev/urandom",
    "ls /dev/fd",
    "cat /dev/stdin",
    "ls /dev/n*",
    "gcc -c src/dev/tty.c",
    "cat ./dev/cu.h",
    "cat ~/dev/tty.notes",
    "cat $HOME/dev/tty.notes",
    "ls dev/",
    "cd ./dev && ls",
    "cd dev",
    "cat docs/ttyUSB-notes.md",
    "echo ttyACM0",
]

ENTERS = [
    "cd /dev && cat cu.usbmodem1",
    "cd /dev/ && ls",
    "pushd /dev",
    "cd /tmp/../dev",
    "cd ../../../dev",
    "cd /DEV",
]


def _config(tmp: Path, profile: str = "role") -> Any:  # noqa: ANN401 - the session's model
    return write_config(tmp, profile=profile)[2]


def _shell(tmp: Path, command: str, profile: str = "role") -> str:
    config = _config(tmp, profile)
    hook_input = HookInput.model_validate(bash(command, cwd=config.worktree))
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


@pytest.mark.parametrize("command", UNREAD, ids=UNREAD)
def test_a_word_only_running_decides_is_refused_in_a_command_that_can_upload(
    tmp_path: Path, command: str
) -> None:
    assert _shell(tmp_path, command) == H.DYNAMIC


@pytest.mark.parametrize(("command", "device"), DEVICES, ids=[c for c, _ in DEVICES])
def test_a_command_that_names_a_serial_device_is_refused(
    tmp_path: Path, command: str, device: str
) -> None:
    assert _shell(tmp_path, command) == H.SERIAL.format(device=device)


@pytest.mark.parametrize("command", NOT_DEVICES, ids=NOT_DEVICES)
def test_another_device_and_a_file_named_like_one_pass(tmp_path: Path, command: str) -> None:
    assert _shell(tmp_path, command) == "allow"


@pytest.mark.parametrize("command", ENTERS, ids=ENTERS)
def test_moving_into_the_devices_directory_is_refused(tmp_path: Path, command: str) -> None:
    reason = _shell(tmp_path, command)
    assert reason.startswith("Opening a serial device is refused")
    assert "the devices' directory" in reason


@pytest.mark.parametrize("profile", ["role", "baseline", "orchestrator", "reviewer"])
def test_every_profile_is_refused(tmp_path: Path, profile: str) -> None:
    assert _shell(tmp_path, "pio run -t upload", profile) == H.UPLOAD
    assert _shell(tmp_path, "cat /dev/ttyACM0", profile) == H.SERIAL.format(device="/dev/ttyACM0")


def test_an_upload_refusal_wins_over_nothing_and_a_device_is_named_first(tmp_path: Path) -> None:
    # Both faults at once: the device is what the reason names, so a session is told the
    # thing no rewording of the command would get past.
    reason = _shell(tmp_path, "pio run -t upload --upload-port /dev/ttyACM0")
    assert reason == H.SERIAL.format(device="/dev/ttyACM0")


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
    assert _tool(tmp_path, tool, {key: path}) == H.SERIAL.format(device=path)


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
    assert _tool(tmp_path, tool, {key: str(link)}) == H.SERIAL.format(device=str(link))


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
    ({"argv": ["esptool.py", "write_flash", "0", "x.bin"]}, H.UPLOAD),
    ({"command": "pio device monitor"}, H.UPLOAD),
    ({"port": "/dev/ttyACM0"}, H.SERIAL.format(device="/dev/ttyACM0")),
    ({"upload_port": "/dev/cu.usbmodem1"}, H.SERIAL.format(device="/dev/cu.usbmodem1")),
    ({"a": {"b": [{"c": "see /dev/tty.usbserial"}]}}, H.SERIAL.format(device="/dev/tty.usbserial")),
    ({"/dev/ttyUSB0": True}, H.SERIAL.format(device="/dev/ttyUSB0")),
    ({"model_path": "/DEV/../dev/ttyUSB0"}, H.SERIAL.format(device="/DEV/../dev/ttyUSB0")),
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
    assert _tool(tmp_path, SERVER_TOOL, nested(H.MAX_DEPTH, "/dev/ttyACM0")) == H.SERIAL.format(
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
        ("linux", ["/dev/ttyACM*", "/dev/ttyUSB*"]),
    ],
)
def test_the_os_layer_denies_the_platform_s_serial_devices_both_ways(
    tmp_path: Path, platform: str, expected: list[str]
) -> None:
    _, _, config = write_config(tmp_path)
    home, temp = tmp_path / "home", tmp_path / "t"
    home.mkdir()
    temp.mkdir()
    policy = sandbox_policy(config, home=str(home), temp_dir=str(temp), platform=platform)
    filesystem = policy.settings["sandbox"]["filesystem"]
    assert list(serial_devices(platform)) == expected
    for kind in ("denyRead", "denyWrite"):
        assert [p for p in filesystem[kind] if p.startswith("/dev/")] == expected
    assert not [p for p in filesystem["allowRead"] + filesystem["allowWrite"] if "/dev/" in p]


def test_every_device_the_os_layer_denies_is_one_the_hooks_refuse_by_name(tmp_path: Path) -> None:
    patterns = [p for platform in ("darwin", "linux") for p in serial_devices(platform)]
    assert len(patterns) == 4
    for pattern in patterns:
        device = pattern.replace("*", "board1")
        assert H.serial_device_in(f"cat {device}") == device
        assert H.serial_device_in(pattern) == pattern
        assert _tool(tmp_path, "Read", {"file_path": device}) == H.SERIAL.format(device=device)
