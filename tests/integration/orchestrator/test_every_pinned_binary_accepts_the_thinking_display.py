"""Every pinned binary accepts the thinking-display option and sends what it names.

The option is one the binary accepts without listing it in its help, so it is
pinned with the binary: this test runs each pinned binary with it against the
scripted endpoint and fails the moment one stops accepting it, or stops sending
the display it names. A value outside the option's choices is refused, which
shows the binary parses the option rather than ignoring it.

The binaries are named by ``PHYSGATE_PINNED_BINS`` (separated like ``PATH``), or
else ``PHYSGATE_CLAUDE_BIN``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from scripted_endpoint import DUMMY_KEY, Script, serving, text

from physgate.orchestrator.invocation import PINNED_VERSIONS

BINARIES = [
    b
    for b in (
        os.environ.get("PHYSGATE_PINNED_BINS") or os.environ.get("PHYSGATE_CLAUDE_BIN") or ""
    ).split(os.pathsep)
    if b
]

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not BINARIES, reason="no pinned Claude Code binary named on this machine"),
]


def _run(binary: str, tmp_path: Path, url: str, display: str) -> subprocess.CompletedProcess[str]:
    home = tmp_path / display / "home"
    home.mkdir(parents=True)
    env = {
        "HOME": str(home),
        "PATH": "/usr/bin:/bin",
        "TERM": "dumb",
        "CLAUDE_CONFIG_DIR": str(tmp_path / display / "config"),
        "CLAUDE_CODE_MAX_RETRIES": "0",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_TELEMETRY": "1",
        "ANTHROPIC_BASE_URL": url,
        "ANTHROPIC_API_KEY": DUMMY_KEY,
    }
    argv = [binary, "-p", "ok", "--setting-sources", "", "--tools", "", "--max-turns", "1"]
    argv += ["--model", "claude-sonnet-5", "--output-format", "json"]
    argv += ["--thinking-display", display]
    return subprocess.run(
        argv,
        env=env,
        cwd=home,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


@pytest.mark.parametrize("binary", BINARIES)
def test_the_binary_sends_the_display_it_is_given(binary: str, tmp_path: Path) -> None:
    version = subprocess.run(
        [binary, "--version"], capture_output=True, text=True, check=True
    ).stdout.split()[0]
    assert version in PINNED_VERSIONS, version
    with serving(Script(main=[text("ok")])) as (api, url):
        done = _run(binary, tmp_path, url, "summarized")
        sent = [r.thinking for r in api.requests]
    assert done.returncode == 0, done.stderr[-400:]
    assert sent and all((t or {}).get("display") == "summarized" for t in sent), sent


@pytest.mark.parametrize("binary", BINARIES)
def test_a_display_outside_the_choices_is_refused(binary: str, tmp_path: Path) -> None:
    with serving(Script(main=[text("ok")])) as (api, url):
        done = _run(binary, tmp_path, url, "loudly")
        sent = list(api.requests)
    assert done.returncode != 0 and sent == []
