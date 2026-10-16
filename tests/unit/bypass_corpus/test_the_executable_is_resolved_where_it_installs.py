"""Presence is the attempt's real executable, resolved, not the catalog name.

R-HK-01 asked ``shutil.which`` for the recorded name, which missed nine
installable binaries: ``redis`` runs ``redis-cli``, ``lua`` ships only as
``lua5.4``, and seven install off a login ``PATH``. R-HK-02 resolves each where
it actually installs.
"""

from __future__ import annotations

import os
from pathlib import Path

from physgate import bypass_corpus as bc


def test_a_bare_name_on_path_is_found() -> None:
    which = {"cat": "/usr/bin/cat"}.get
    assert bc.resolve_executable("cat", which=which) == "/usr/bin/cat"


def test_redis_is_resolved_through_its_runtime_name() -> None:
    which = {"redis-cli": "/usr/bin/redis-cli"}.get
    assert bc.resolve_executable("redis", which=which) == "/usr/bin/redis-cli"


def test_lua_is_resolved_through_the_versioned_name() -> None:
    which = {"lua5.4": "/usr/bin/lua5.4"}.get
    assert bc.resolve_executable("lua", which=which) == "/usr/bin/lua5.4"


def test_a_plugin_off_path_is_found_in_its_install_dir(tmp_path: Path) -> None:
    plugins = tmp_path / "nagios"
    plugins.mkdir()
    binary = plugins / "check_raid"
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    found = bc.resolve_executable(
        "check_raid", which=lambda _name: None, extra_dirs=(str(plugins),)
    )
    assert found == str(binary)


def test_a_non_executable_match_off_path_is_not_taken(tmp_path: Path) -> None:
    directory = tmp_path / "bin"
    directory.mkdir()
    (directory / "zsoelim").write_text("not executable\n")
    assert (
        bc.resolve_executable("zsoelim", which=lambda _name: None, extra_dirs=(str(directory),))
        is None
    )


def test_a_directory_named_like_the_binary_is_not_taken(tmp_path: Path) -> None:
    directory = tmp_path / "bin"
    directory.mkdir()
    (directory / "pg").mkdir()
    os.chmod(directory / "pg", 0o755)
    assert (
        bc.resolve_executable("pg", which=lambda _name: None, extra_dirs=(str(directory),)) is None
    )


def test_an_absent_binary_resolves_to_none() -> None:
    assert bc.resolve_executable("no-such-binary", which=lambda _name: None, extra_dirs=()) is None
