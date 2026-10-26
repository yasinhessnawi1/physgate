"""Tests of code_changes.py (§3.3): a fixture repository, a test per resolution rule and per stop.

Run explicitly, from the repository root: ``uv run pytest -q experiments/R-PG-03``.

The fixture repository is built here, a small ``src/physgate`` of its own; the last tests read the
real repository's git objects at the trees §3.3 measured, and nothing else.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import code_changes as cc  # noqa: E402

REPO = HERE.parent.parent

#: The fixture's package: the seeds, and a module of each kind the rules name.
BASE_FILES = {
    "src/physgate/__init__.py": "",
    "src/physgate/cli.py": "from physgate.orchestrator import cli as o\n",
    "src/physgate/orchestrator/__init__.py": "",
    "src/physgate/orchestrator/cli.py": "import physgate.state.store\n",
    "src/physgate/state/__init__.py": "",
    "src/physgate/state/store.py": "X = 1\n",
    "src/physgate/hooks/__init__.py": "",
    "src/physgate/hooks/__main__.py": "from physgate.hooks import registry\n",
    "src/physgate/hooks/registry.py": "def f():\n    from physgate.hooks.handlers import a\n",
    "src/physgate/hooks/handlers/__init__.py": "",
    "src/physgate/hooks/handlers/a.py": "Y = 2\n",
    "src/physgate/evaluation/__init__.py": "",
    "src/physgate/evaluation/inject/__init__.py": "",
    "src/physgate/evaluation/inject/runner.py": "from physgate.gate.units import parse\n",
    "src/physgate/gate/__init__.py": "",
    "src/physgate/gate/units.py": "def parse():\n    return 1\n",
    "src/physgate/gate/trampoline.sh": "#!/bin/sh\n",
    "src/physgate/orphan.py": "Z = 3\n",
    "pyproject.toml": "[project]\nname = 'x'\n",
}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


def make_repo(tmp: Path, files: dict[str, str]) -> Path:
    repo = tmp / "repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "master")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    write(repo, files)
    commit(repo, "the start")
    return repo


def write(repo: Path, files: dict[str, str]) -> None:
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def commit(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def walk_with(tmp: Path, extra: dict[str, str]) -> cc.Walk:
    repo = make_repo(tmp, {**BASE_FILES, **extra})
    return cc.walk(cc.Tree.at(repo, "HEAD"))


# ---- the resolution rules ----------------------------------------------------------------------


def test_the_seeds_are_the_inject_package_the_console_script_and_the_hook_process(
    tmp_path: Path,
) -> None:
    w = walk_with(tmp_path, {})
    assert "src/physgate/evaluation/inject/runner.py" in w.reached
    assert "src/physgate/cli.py" in w.reached
    assert "src/physgate/hooks/__main__.py" in w.reached
    assert w.unreached == ["src/physgate/orphan.py"]


def test_import_p_m_resolves_to_the_module_file(tmp_path: Path) -> None:
    w = walk_with(tmp_path, {})
    assert "src/physgate/state/store.py" in w.reached


def test_from_p_m_import_x_resolves_to_p_m(tmp_path: Path) -> None:
    w = walk_with(tmp_path, {})
    assert "src/physgate/gate/units.py" in w.reached


def test_from_p_import_m_reaches_the_submodule(tmp_path: Path) -> None:
    w = walk_with(tmp_path, {})
    assert "src/physgate/hooks/registry.py" in w.reached
    assert "src/physgate/orchestrator/cli.py" in w.reached


def test_a_package_import_resolves_to_its_init(tmp_path: Path) -> None:
    w = walk_with(
        tmp_path,
        {
            "src/physgate/state/store.py": "import physgate.series\n",
            "src/physgate/series/__init__.py": "",
        },
    )
    assert "src/physgate/series/__init__.py" in w.reached


def test_every_parent_package_s_init_counts(tmp_path: Path) -> None:
    w = walk_with(tmp_path, {})
    for init in (
        "src/physgate/__init__.py",
        "src/physgate/hooks/handlers/__init__.py",
        "src/physgate/evaluation/__init__.py",
    ):
        assert init in w.reached


def test_an_import_inside_a_function_or_under_type_checking_is_followed(tmp_path: Path) -> None:
    w = walk_with(
        tmp_path,
        {
            "src/physgate/state/store.py": (
                "from typing import TYPE_CHECKING\n"
                "if TYPE_CHECKING:\n    from physgate.typed import T\n"
            ),
            "src/physgate/typed.py": "T = int\n",
        },
    )
    assert "src/physgate/hooks/handlers/a.py" in w.reached  # inside a function
    assert "src/physgate/typed.py" in w.reached


def test_a_relative_import_resolves_against_the_importing_package(tmp_path: Path) -> None:
    w = walk_with(
        tmp_path,
        {
            "src/physgate/gate/units.py": "from . import extra\nfrom ..state import other\n",
            "src/physgate/gate/extra.py": "",
            "src/physgate/state/other.py": "",
        },
    )
    assert "src/physgate/gate/extra.py" in w.reached
    assert "src/physgate/state/other.py" in w.reached


def test_an_import_call_with_a_literal_physgate_name_is_followed(tmp_path: Path) -> None:
    w = walk_with(
        tmp_path,
        {
            "src/physgate/state/store.py": (
                "import importlib\nm = importlib.import_module('physgate.lit')\n"
            ),
            "src/physgate/lit.py": "",
        },
    )
    assert "src/physgate/lit.py" in w.reached and not w.stops


def test_find_spec_is_not_a_dynamic_import(tmp_path: Path) -> None:
    w = walk_with(
        tmp_path,
        {"src/physgate/state/store.py": "import importlib.util as u\nu.find_spec(name)\n"},
    )
    assert not w.stops


# ---- the stops ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        "import importlib\nimportlib.import_module(name)\n",
        "from importlib import import_module as im\nim(name)\n",
        "import importlib as il\nil.__import__(name)\n",
        "__import__(name)\n",
        "import runpy\nrunpy.run_module(name)\n",
        "from runpy import run_path\nrun_path(where)\n",
        "f = __import__\nf(name)\n",
    ],
    ids=[
        "import_module",
        "an-alias",
        "importlib.__import__",
        "__import__",
        "run_module",
        "run_path",
        "an-assigned-name",
    ],
)
def test_an_import_call_whose_module_is_not_a_literal_stops(tmp_path: Path, code: str) -> None:
    w = walk_with(tmp_path, {"src/physgate/state/store.py": code})
    assert w.stops and "not a literal" in w.stops[0]


@pytest.mark.parametrize("call", ["exec(code)", "eval(code)", "compile(code, 'f', 'exec')"])
def test_a_built_in_exec_eval_or_compile_of_code_that_is_not_a_literal_stops(
    tmp_path: Path, call: str
) -> None:
    w = walk_with(tmp_path, {"src/physgate/state/store.py": call + "\n"})
    assert w.stops and "of code" in w.stops[0]


def test_a_literal_exec_and_a_module_s_own_compile_do_not_stop(tmp_path: Path) -> None:
    w = walk_with(
        tmp_path,
        {
            "src/physgate/state/store.py": (
                "import re\nexec('x = 1')\nre.compile(p)\nfrom re import compile\ncompile(p)\n"
            )
        },
    )
    assert not w.stops


@pytest.mark.parametrize(
    "code",
    [
        "import importlib.util\nimportlib.util.spec_from_file_location('m', p)\n",
        "from importlib import util\nutil.spec_from_file_location('m', p)\n",
        "loader.exec_module(module)\n",
    ],
    ids=["spec_from_file_location", "through-util", "exec_module"],
)
def test_a_module_loaded_by_its_file_path_stops(tmp_path: Path, code: str) -> None:
    w = walk_with(tmp_path, {"src/physgate/state/store.py": code})
    assert w.stops


@pytest.mark.parametrize(
    "code",
    [
        "import importlib.metadata\nimportlib.metadata.entry_points()\n",
        "from importlib.metadata import entry_points\nentry_points(group='g')\n",
    ],
)
def test_entry_points_stop(tmp_path: Path, code: str) -> None:
    w = walk_with(tmp_path, {"src/physgate/state/store.py": code})
    assert w.stops and "plug-in" in w.stops[0]


@pytest.mark.parametrize(
    "code",
    [
        "ARGS = ['python', '-I', '-m', 'physgate.orphan']\n",
        "CMD = 'python -m physgate.orphan --x'\n",
        "run(python, '-m', 'physgate.orphan')\n",
    ],
    ids=["a-list", "one-string", "call-arguments"],
)
def test_a_launch_by_m_of_a_module_the_walk_does_not_reach_stops(tmp_path: Path, code: str) -> None:
    w = walk_with(tmp_path, {"src/physgate/state/store.py": code})
    assert w.stops and "-m of physgate.orphan" in w.stops[0]


def test_a_launch_by_m_of_a_reached_module_or_package_with_a_reached_main_does_not_stop(
    tmp_path: Path,
) -> None:
    w = walk_with(
        tmp_path,
        {
            "src/physgate/state/store.py": (
                "A = ['-I', '-m', 'physgate.hooks']\nB = 'python -m physgate.gate.units.'\n"
                "C = ['git', 'commit', '-m', message]\n"
            )
        },
    )
    assert not w.stops


def test_a_launch_by_m_of_a_package_whose_main_is_not_reached_stops(tmp_path: Path) -> None:
    w = walk_with(
        tmp_path, {"src/physgate/state/store.py": "A = ['-m', 'physgate.orchestrator']\n"}
    )
    assert w.stops


def test_a_stop_in_a_file_that_is_not_loaded_does_not_stop(tmp_path: Path) -> None:
    w = walk_with(tmp_path, {"src/physgate/orphan.py": "exec(code)\n"})
    assert not w.stops


def test_a_file_that_does_not_parse_stops(tmp_path: Path) -> None:
    with pytest.raises(cc.StopError):
        walk_with(tmp_path, {"src/physgate/state/store.py": "def (:\n"})


# ---- the list ----------------------------------------------------------------------------------


def test_the_list_marks_every_path_and_names_each_commit_s_pr(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, BASE_FILES)
    old = git(repo, "rev-parse", "HEAD")
    write(repo, {"src/physgate/state/store.py": "X = 2\n"})
    commit(repo, "fix(state): a squashed change (#7)")
    git(repo, "checkout", "-q", "-b", "side")
    write(
        repo,
        {"src/physgate/orphan.py": "Z = 4\n", "src/physgate/gate/trampoline.sh": "#!/bin/sh\n#\n"},
    )
    side = commit(repo, "feat: a change on a branch")
    write(repo, {"README.md": "not a listed path\n"})
    commit(repo, "docs: outside the paths")
    git(repo, "checkout", "-q", "master")
    git(repo, "merge", "-q", "--no-ff", "side", "-m", "Merge pull request #9 from someone/side")
    new = git(repo, "rev-parse", "HEAD")
    o, n = cc.walk(cc.Tree.at(repo, old)), cc.walk(cc.Tree.at(repo, new))
    found = cc.one_range(repo, old, new, o, n)
    by_sha = {c["sha"]: c for c in found["commits"]}
    assert len(found["commits"]) == 2  # the docs commit touched no listed path
    squashed = next(c for c in found["commits"] if c["sha"] != side)
    assert squashed["pr"] == "7"
    assert by_sha[side]["pr"] == "9"
    marks = {p["path"]: p["mark"] for c in found["commits"] for p in c["paths"]}
    assert marks == {
        "src/physgate/state/store.py": "loaded",
        "src/physgate/orphan.py": "not loaded",
        "src/physgate/gate/trampoline.sh": "may be read",
    }
    assert found["diff_stat"][-1].strip().startswith("3 files changed")


def test_the_cli_exits_3_on_a_stop_and_never_writes_over_a_list(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, {**BASE_FILES, "src/physgate/state/store.py": "exec(code)\n"})
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            str(HERE / "code_changes.py"),
            "--repo",
            str(repo),
            "--walk",
            "HEAD",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 3 and "stopped" in json.loads(done.stdout)
    out = tmp_path / "list.json"
    out.write_text("{}")
    done = subprocess.run(
        [
            sys.executable,
            "-I",
            str(HERE / "code_changes.py"),
            "--repo",
            str(repo),
            "--r",
            "HEAD",
            "--out",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 1 and "never written over" in done.stdout


# ---- the real repository, at §3.3's measured trees ----------------------------------------------


def _has(rev: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(REPO), "cat-file", "-e", f"{rev}^{{commit}}"], check=False
        ).returncode
        == 0
    )


@pytest.mark.skipif(not _has("fc28f32"), reason="the measured trees are not in this clone")
def test_the_walk_reproduces_the_counts_measured_before_the_freeze() -> None:
    at = cc.walk(cc.Tree.at(REPO, "fc28f32"))
    assert (len(at.tree.python), len(at.tree.others)) == (175, 11)
    assert len(at.reached) == 173 and not at.stops
    assert [cc.module_of(p) for p in at.unreached] == [
        "physgate.bypass_corpus",
        "physgate.knowledge.ceiling",
    ]
    for old in ("0936f1f", "eae78c0", "8c51f48"):
        w = cc.walk(cc.Tree.at(REPO, old))
        assert (len(w.reached), len(w.tree.python)) == (169, 171) and not w.stops
    alone = cc.walk(cc.Tree.at(REPO, "fc28f32"), inject_only=True)
    assert len(alone.reached) == 136
