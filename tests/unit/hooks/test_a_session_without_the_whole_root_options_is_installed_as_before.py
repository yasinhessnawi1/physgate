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
    ("role", False): "f8f71a2a34af0ad12177dd325170a1f3e72710e4039d3ba96103f489d0f84251",
    ("reviewer", False): "3b2eb0d2326b0a7f56e8e81909b6e9595cdb5c470715b15280a68981475c448b",
    ("orchestrator", False): "800ac5b48e5a17c7f826c29f0eb139f1afbe42a65b556df75df7c21d7ebd4a1d",
    ("baseline", False): "69c7151686244ca906d90bcfb742c39a3fe4f478aa9f0a1f71eee56389ed4307",
    # Inside the layer the configuration now says so (``"os_layer": true``), so that a command's
    # read of the harness checkout is left to the layer there and refused where it is absent.
    # That key is the only change from the digests taken before the options.
    ("role", True): "d59f4e7ae7bcca2a7c0fcb2d18aa751857e3f568a3d6306a724853b4196151eb",
    ("reviewer", True): "87cda4c5a1f00139c62616cf73093bd31aede175173e3abc5e863b884ff020a1",
    ("orchestrator", True): "079ef308e0296f25884a74816781c3102e5dd69a6be36bc7420f88ca32fdaa1f",
    ("baseline", True): "9c59fe55db2d04be298af79f078814e4c5809376dd6ea4d7ff367e1fd6b2a798",
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
