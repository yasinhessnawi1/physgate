"""The built app is loaded once at start and served from memory, or refused.

A missing, unstamped or stale build refuses the start, and so does anything in the build the
server would not send.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ui_rig import context_over, fake_ui, serving

from physgate.ui import assets
from physgate.ui.exceptions import StartupRefusedError


def test_a_stamped_build_loads_its_page_and_its_assets(tmp_path: Path) -> None:
    built = assets.load(fake_ui(tmp_path))
    assert built.index.startswith(b"<!doctype html>")
    assert set(built.files) == {"app.js", "app.css"}
    assert built.files["app.js"][1] == "text/javascript; charset=utf-8"


def test_no_build_refuses_the_start_and_names_the_build_command(tmp_path: Path) -> None:
    ui = fake_ui(tmp_path)
    (ui / "dist" / "index.html").unlink()
    with pytest.raises(StartupRefusedError, match="not built.*build-ui.sh"):
        assets.load(ui)


def test_a_build_with_no_stamp_refuses_the_start(tmp_path: Path) -> None:
    ui = fake_ui(tmp_path)
    (ui / "dist" / assets.STAMP).unlink()
    with pytest.raises(StartupRefusedError, match="no stamp"):
        assets.load(ui)


@pytest.mark.parametrize(
    "change",
    [
        lambda ui: (ui / "src" / "main.ts").write_text("export const x = 2;\n"),
        lambda ui: (ui / "src" / "added.ts").write_text("export {};\n"),
        lambda ui: (ui / "src" / "main.ts").rename(ui / "src" / "moved.ts"),
        lambda ui: (ui / "index.html").write_text("<!doctype html>\n"),
        lambda ui: (ui / "tsconfig.json").write_text("{}\n"),
    ],
)
def test_a_build_older_than_its_sources_refuses_the_start(tmp_path: Path, change: object) -> None:
    ui = fake_ui(tmp_path)
    change(ui)  # type: ignore[operator]
    with pytest.raises(StartupRefusedError, match="stale"):
        assets.load(ui)


def test_restamping_after_a_rebuild_is_accepted(tmp_path: Path) -> None:
    ui = fake_ui(tmp_path)
    (ui / "src" / "main.ts").write_text("export const x = 2;\n")
    assets.write_stamp(ui)
    assert assets.load(ui).files


def test_a_forged_stamp_is_refused(tmp_path: Path) -> None:
    ui = fake_ui(tmp_path)
    (ui / "dist" / assets.STAMP).write_text(json.dumps({"sources_sha256": "0" * 64}))
    with pytest.raises(StartupRefusedError, match="stale"):
        assets.load(ui)


def test_a_link_in_the_build_refuses_the_start(tmp_path: Path) -> None:
    ui = fake_ui(tmp_path)
    (tmp_path / "elsewhere.js").write_text("x\n")
    (ui / "dist" / "assets" / "linked.js").symlink_to(tmp_path / "elsewhere.js")
    with pytest.raises(StartupRefusedError, match="link"):
        assets.load(ui)


def test_a_file_of_a_type_the_server_does_not_send_refuses_the_start(tmp_path: Path) -> None:
    ui = fake_ui(tmp_path)
    (ui / "dist" / "assets" / "notes.txt").write_text("x\n")
    with pytest.raises(StartupRefusedError, match="type"):
        assets.load(ui)


def test_the_stamp_command_writes_what_the_loader_checks(tmp_path: Path) -> None:
    ui = fake_ui(tmp_path)
    (ui / "src" / "main.ts").write_text("export const x = 3;\n")
    assert assets.main(["stamp", str(ui)]) == 0
    assert assets.load(ui).files


def test_a_file_changed_on_disk_after_start_is_not_what_is_served(tmp_path: Path) -> None:
    """Served from memory: the request never reaches the file."""
    ui = fake_ui(tmp_path)
    root = tmp_path / "runs"
    root.mkdir()
    with serving(context_over(root, ui_root=ui)) as live:
        (ui / "dist" / "assets" / "app.js").write_text("changed after start\n")
        status, headers, body = live.request("GET", "/assets/app.js")
    assert status == 200
    assert body == b"console.log(1);\n"
    assert headers["content-type"] == "text/javascript; charset=utf-8"
