"""Through the real binary: a session's temporary files are its own; the shared ones are refused.

Claude Code writes a background command's output under its temporary directory, which is the one
every session of the user on the machine shares (``/tmp/claude-<uid>``) unless
``CLAUDE_CODE_TMPDIR`` names another. A role session is installed with a directory of its own, so:

- the binary, given the session's environment, writes a background command's output there and
  not in the shared directory; the session's shell reads it, and its file tools are refused there
  as in every temporary directory, since a path judged before a tool opens it could be swapped for
  a link in between;
- another session's own temporary directory is refused to its shell, and, where the OS layer
  runs, to a command that builds the path at run time;
- a stand-in task output this test plants in the real shared directory is refused to the
  session's file tool and its shell, by either spelling of the directory, and, where the OS layer
  runs, to a command that builds the path at run time, which only that layer can see.

The stand-in is the test's own file, in a directory of its own made for it and removed by name
afterwards; nothing else of the shared directory is read or listed.
"""

from __future__ import annotations

import contextlib
import os
import re
import secrets
import shutil
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_messages_api import DUMMY_KEY, Script, serving, text, tool
from hook_session import claude_binary
from os_layer_rig import SEARCH_PATH, Layout, layer_here, make_layout, python, run_session

from physgate.oslayer.probe import claude_temp_dirs
from physgate.oslayer.session_temp import make_session_temp

pytestmark = pytest.mark.integration

OWN_MARKER = "OWN-TASK-OUTPUT-5d18"
SHARED_MARKER = "SHARED-STAND-IN-9c42"
SIBLING_MARKER = "SIBLING-STAND-IN-2e67"
WRITTEN_TO = re.compile(r"Output is being written to: (\S+\.output)")


@pytest.fixture
def layout(tmp_path: Path) -> Iterator[Layout]:
    with make_layout(tmp_path) as made:
        yield made


@pytest.fixture
def planted() -> Iterator[Path]:
    """The test's own stand-in task output, in a directory of its own in the real shared one."""
    shared = Path(claude_temp_dirs()[0])
    made_shared = not shared.exists()
    if made_shared:
        shared.mkdir(mode=0o700)
    mine = shared / f"physgate-stand-in-{secrets.token_hex(6)}"
    out = mine / "tasks" / "b0standin.output"
    out.parent.mkdir(parents=True)
    out.write_text(SHARED_MARKER + "\n")
    try:
        yield out
    finally:
        shutil.rmtree(mine, ignore_errors=True)
        if made_shared:
            with contextlib.suppress(OSError):
                shared.rmdir()


def _background_output(layout: Layout) -> Path:
    """Where the binary, given the session's own temporary directory, writes a background output.

    Run without the hook settings, since the hooks refuse a session's backgrounding: this is the
    binary's own placement of the file, which the hooked session then reads.
    """
    binary = claude_binary()
    (layout.root / "background-config").mkdir()
    steps = [tool("Bash", command=f"echo {OWN_MARKER}", description="bg", run_in_background=True)]
    with serving(Script(main=[*steps, text("end")])) as (api, url):
        env = {
            "HOME": str(layout.sdir / "home"),
            "PATH": f"{Path(binary).parent}:{SEARCH_PATH}",
            "TERM": "dumb",
            "ANTHROPIC_BASE_URL": url,
            "ANTHROPIC_API_KEY": DUMMY_KEY,
            "CLAUDE_CONFIG_DIR": str(layout.root / "background-config"),
            "CLAUDE_CODE_TMPDIR": str(layout.temp.resolve()),
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_MAX_RETRIES": "0",
        }
        subprocess.run(
            [binary, "-p", "go", "--setting-sources", "", "--output-format", "stream-json"]
            + [
                "--verbose",
                "--model",
                "claude-sonnet-4-5",
                "--permission-mode",
                "bypassPermissions",
            ],
            cwd=layout.worktree,
            env=env,
            capture_output=True,
            text=True,
            check=False,
            timeout=300,
        )
    told = [r.last_user for r in api.requests if r.thread == "main" and r.tool_results == 1]
    found = WRITTEN_TO.search(told[0] if told else "")
    assert found is not None, told
    out = Path(found.group(1))
    deadline = time.monotonic() + 20
    while not (out.exists() and OWN_MARKER in out.read_text()) and time.monotonic() < deadline:
        time.sleep(0.1)
    return out


@pytest.fixture
def sibling() -> Iterator[Path]:
    """Another session's own temporary directory, with a task output of its own planted in it."""
    other = make_session_temp()
    out = other / "tasks" / "b0sibling.output"
    out.parent.mkdir()
    out.write_text(SIBLING_MARKER + "\n")
    try:
        yield out
    finally:
        shutil.rmtree(other, ignore_errors=True)


@pytest.mark.parametrize("layer", [False, True], ids=["text-hooks-only", "with-the-os-layer"])
def test_a_session_s_shell_reads_its_own_task_output_and_nothing_of_another_session_s(
    layout: Layout, planted: Path, sibling: Path, layer: bool
) -> None:
    if layer and not layer_here():
        pytest.skip("the OS layer cannot run here")
    own = _background_output(layout)
    own_top = layout.temp.resolve() / f"claude-{os.getuid()}"
    assert own.is_relative_to(own_top), own
    assert OWN_MARKER in own.read_text()
    shared = Path(claude_temp_dirs()[0])
    resolved = Path(os.path.realpath(planted))
    template = (
        "import os\np = os.path.join(*{parts!r})\ntry:\n    print(open(p).read())\n"
        "except OSError as e:\n    print('denied:', e.strerror)\n"
    )
    built = template.format(parts=["/", *planted.relative_to("/").parts])
    built_sibling = template.format(parts=["/", *sibling.resolve().relative_to("/").parts])
    steps = [
        tool("Read", file_path=str(own)),
        tool("Bash", command=f"cat {own}", description="own"),
        tool("Read", file_path=str(planted)),
        tool("Read", file_path=str(resolved)),
        tool("Bash", command=f"cat {planted}", description="shared"),
        tool("Bash", command=f"ls {shared}", description="list"),
        tool("Bash", command=python(built), description="built"),
        tool("Bash", command=f"cat {sibling}", description="sibling"),
        tool("Bash", command=python(built_sibling), description="built-sibling"),
        tool(
            "Bash",
            command=python("import os; print('CCT=' + os.environ.get('CLAUDE_CODE_TMPDIR', '-'))"),
            description="env",
        ),
    ]
    run = run_session(layout, steps, layer=layer)
    told = run["told"]
    assert isinstance(told, list) and len(told) == len(steps)
    own_read, own_cat, read, read_resolved, cat, listed, built_read, sib, built_sib, env = told
    # Its own output reaches it through its shell alone: the file tools are refused there.
    assert OWN_MARKER in own_cat
    assert OWN_MARKER not in own_read and "protected" in own_read, own_read
    for refused in (read, read_resolved, cat, listed, sib):
        assert SHARED_MARKER not in refused and "protected" in refused, refused
    assert planted.name not in listed
    # The binary was pointed at the session's own directory, with the layer or without it.
    assert f"CCT={layout.temp.resolve()}" in env, env
    if layer:
        # The residual the text hooks cannot see: only the OS layer refuses it.
        assert SHARED_MARKER not in built_read and "denied:" in built_read, built_read
        assert SIBLING_MARKER not in built_sib and "denied:" in built_sib, built_sib
    else:
        # Without the layer it reads: the probe reaches the file, so the refusals above mean it.
        assert SHARED_MARKER in built_read, built_read
        assert SIBLING_MARKER in built_sib, built_sib
