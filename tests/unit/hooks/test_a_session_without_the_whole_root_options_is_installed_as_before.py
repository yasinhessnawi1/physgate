"""A session installed without the whole-root options is installed exactly as before them.

The options that withhold a root whole but for the session's own place in it (given together, a
protected trial's or a blind check's raw session) change code every kind of session shares: the
hook layer's rules, the configuration the installer builds and the OS layer's profile. A session
given neither is held here to what that code made for it before the options existed, for every
profile kind and both platforms' profiles: its configuration (the hook rules), its settings file
and its OS-layer settings, byte for byte, the paths of the rig written as one placeholder.

The digests were taken from the code as it stood before the options were added. A change that is
meant to alter a session's installation updates them, and says so.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from physgate.hooks.config import Installation, SessionConfig
from physgate.hooks.registry import REGISTRY
from physgate.hooks.settings import InstallRequest, build_config, config_bytes, render_settings
from physgate.oslayer import reaper_install
from physgate.oslayer.policy import sandbox_policy

#: Each profile kind, without the OS layer and with it, and the digest of what it was installed
#: with before the options.
BEFORE = {
    # The tool layer changed every profile's installation in three ways and no other: the
    # hardware hook joins the pre-tool hooks, the binary's search tool joins the denied tools,
    # and both platforms' OS-layer profiles deny a board's device nodes to reads and writes.
    ("role", False): "8ccf40333bc9f4997eebd716e844ece36bbcaed335f3871d01582af942e1cab0",
    ("reviewer", False): "528293ed5df81d0cfa2caae6ee93c1aef720547363c1d4d931ad00a33033bdd9",
    ("orchestrator", False): "f7e0e166765180f88e69aa16f6d935c4e0fc3491203f3f6eb256cab3da86f283",
    ("baseline", False): "87cdeea9100250047725118e68657b34be30678e26c4c70196e1582d4af28a52",
    # Inside the layer the configuration now says so (``"os_layer": true``), so that a command's
    # read of the harness checkout is left to the layer there and refused where it is absent.
    # That key is the only change from the digests taken before the options, beside the tool
    # layer's three.
    ("role", True): "2fe3e0d860a5f68ccccc768b91753de5731b286dd31d8f27485743cc4afa81fa",
    ("reviewer", True): "55cf8e9700589ad314013f69d2f48838d739f4ad3407bdb39c81df1985ff5085",
    ("orchestrator", True): "67eca92534d15416e50eea1225b46aec83da91801ac7ec301e40abc4a57498d8",
    ("baseline", True): "c2e4df8d02c479a185b6307f51552569a9c1183b09b80e975969b224e72ffc96",
}
PLACEHOLDER = "<rig>"


def _rig(tmp_path: Path) -> Path:
    root = tmp_path.resolve()
    for d in ("run/worktrees/s1", "run/sessions/s1/home", "tiers/v1", "review", "install/lib"):
        (root / d).mkdir(parents=True)
    (root / "tiers" / "v1" / "scenario.json").write_text("{}\n")
    (root / "run" / "run.json").write_text("{}\n")
    return root


def _installation(root: Path) -> Installation:
    return Installation(
        interpreter=str(root / "install" / "bin" / "python"),
        base_prefix=str(root / "install"),
        environment_root=str(root / "install"),
        package_dir=str(root / "install" / "lib"),
    )


def _request(root: Path, profile: str, layer: bool) -> InstallRequest:
    sessions = root / "run" / "sessions"
    fields: dict[str, object] = {
        "profile": profile,
        "role": "electrical" if profile == "role" else None,
        "worktree": str(root / "run" / "worktrees" / "s1"),
        "own_branch": None,
        "store_root": None,
        "state_dir": str(sessions / "s1" / "state"),
        "target_dir": str(sessions / "s1" / "session"),
        "claude_config_dir": str(sessions / "s1" / "config"),
        "user_home": str(sessions / "s1" / "home"),
        "token_ceiling": 1000,
        "held_out": (str(root / "tiers" / "v1"),),
        "extra_protected": (str(root / "run" / "run.json"),),
        "withheld": (str(root / "run" / "run.json"),),
        "shared_claude_temp": (str(root / "claude-temp"),),
        "session_temps": str(root / "temps"),
    }
    if layer:
        fields["os_layer_temp_dir"] = str(root / "temps" / "own")
        fields["spawns_with_canary"] = True
    else:
        fields["temp_dir"] = str(root / "temps" / "own")
    if profile in ("role", "baseline"):
        fields["sessions_root"] = str(sessions)
    if profile == "reviewer":
        fields["read_roots"] = (str(root / "review"),)
    return InstallRequest(**fields)  # type: ignore[arg-type]


def _installed(root: Path, profile: str, layer: bool) -> str:
    config: SessionConfig = build_config(_request(root, profile, layer), _installation(root))
    made = {
        # As the installer writes it: the fields only a compacting reviewer has are left out
        # when empty, so a session given neither option keeps its bytes.
        "config": json.loads(config_bytes(config)),
        "settings": render_settings(config, str(root / "config.json"), "0" * 64, REGISTRY),
        "os_layer": {
            platform: sandbox_policy(
                config,
                home=str(root / "run" / "sessions" / "s1" / "home"),
                temp_dir=str(root / "temps" / "own"),
                platform=platform,
            ).settings
            for platform in ("darwin", "linux")
        },
    }
    return json.dumps(made, sort_keys=True).replace(str(root), PLACEHOLDER)


@pytest.mark.parametrize(("profile", "layer"), sorted(BEFORE))
def test_a_session_given_neither_option_is_installed_byte_for_byte_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile: str, layer: bool
) -> None:
    # The survivor reaper is wanted on one platform only, and the series outbox's reason is worded
    # for the platform's mechanism: both held as on macOS, where the digests were taken, so the
    # row holds the same bytes on every host (each OS-layer profile is built for both platforms).
    monkeypatch.setattr(reaper_install, "wanted", lambda platform="": True)
    monkeypatch.setattr(sys, "platform", "darwin")
    made = _installed(_rig(tmp_path), profile, layer)
    assert PLACEHOLDER in made  # not vacuous: the rig's paths are what was installed
    assert hashlib.sha256(made.encode()).hexdigest() == BEFORE[profile, layer], made[:2000]
