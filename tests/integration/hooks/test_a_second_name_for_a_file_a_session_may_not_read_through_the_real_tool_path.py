"""Through the real binary: a second name for a file a session may not read gives it nothing.

A hard link is the same file under another name. Made in the worktree to the harness's skill file
or a held-out scenario, it would hand a file tool that file under a name every root test passes,
since the inode test compares directories only. So, for each kind of root and each layer:

- Inside the OS layer (measured on Linux, bubblewrap, in CI): a command that builds both paths
  as it runs, so no hook reads them in its words, cannot make the link anywhere it writes (the
  worktree, its home, the shared temporary directory), and a Read of the new name finds nothing.
  The layer hides a read-denied place from the command, so there is no file there to link.
- Without the layer: a command that names a read-denied file for a link (``ln``, ``ln -f``,
  ``cp -l``, ``link``) is refused by the hooks before it runs. A command that builds its paths
  as it runs makes the link in the worktree, and a Read of it there is refused by the path hook,
  which refuses every read of a file in the worktree that has more than one name.

The known residuals without the layer are rows of their own, which assert what happens today and
name it: a command that decodes its path inside an interpreter reads the file itself, a command
that assembles its path from a substitution reads it too, and a link such a command makes
outside the worktree is read by a file tool. Inside the layer none of the three reaches the file.
Set ``PHYSGATE_OSLAYER_REPORT`` to a directory to keep what each command was told as JSON.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
from pathlib import Path
from typing import Any, cast

import pytest
from fake_messages_api import tool
from os_layer_rig import MARKER, Layout, layer_here, make_layout, python, run_session

from physgate.hooks.reasons import HARNESS_REASON, HELD_OUT_REASON

pytestmark = pytest.mark.integration

#: Where the stand-in harness's skill file lies, under the directory outside the run.
SKILL = "harness/knowledge/control/skill.md"
#: What the path hook says when it refuses a read of a file with a second name.
SECOND_NAME = "more than one name"
#: Where the command writes what it was told, in the worktree, which it may write.
OUTCOMES = "linked.json"


@pytest.fixture
def layer() -> None:
    if not layer_here():
        pytest.skip("the OS layer cannot run here")


def _sources(layout: Layout) -> dict[str, tuple[Path, str, str]]:
    """Each file a session may not read: its path, the marker it holds, the reason it is kept."""
    marker = f"harness-skill-{secrets.token_hex(8)}"
    skill = layout.outside / SKILL
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(f"# skill\n{marker}\n")
    return {
        "the harness's skill file": (skill, marker, HARNESS_REASON),
        "a held-out scenario": (layout.held / "stand.txt", MARKER, HELD_OUT_REASON),
    }


def _fields(layout: Layout) -> dict[str, Any]:
    return {"harness_root": str(layout.outside / "harness")}


def _destinations(layout: Layout) -> dict[str, Path]:
    """Every place a command of the session writes, where it could leave a link."""
    return {
        "the worktree": layout.worktree / "hl.md",
        "the session's home": layout.sdir / "home" / "hl.md",
        "the shared temporary directory": Path("/tmp") / f"pg-hl-{secrets.token_hex(6)}.md",
    }


def _encoded(path: Path) -> str:
    return base64.b64encode(str(path).encode()).decode()


def _link_unseen(source: Path, links: dict[str, Path]) -> dict[str, object]:
    """One command that links ``source`` to each place, every path decoded as it runs."""
    pairs = {what: _encoded(link) for what, link in links.items()}
    return tool(
        "Bash",
        command=python(
            "import base64, json, os\n"
            f"source = base64.b64decode({_encoded(source)!r}).decode()\n"
            f"links = {pairs!r}\n"
            "out = {}\n"
            "for what, enc in links.items():\n"
            "    try:\n"
            "        os.link(source, base64.b64decode(enc).decode())\n"
            "        out[what] = 'linked'\n"
            "    except OSError as exc:\n"
            "        out[what] = f'refused: {exc.strerror}'\n"
            f"open({OUTCOMES!r}, 'w').write(json.dumps(out, sort_keys=True))"
        ),
    )


def _told(seen: dict[str, object]) -> list[str]:
    """What the session was told after each of its steps."""
    return [str(said) for said in cast("list[object]", seen["told"])]


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def _report(name: str, shown: dict[str, Any]) -> None:
    where = os.environ.get("PHYSGATE_OSLAYER_REPORT")
    if where:
        Path(where).mkdir(parents=True, exist_ok=True)
        (Path(where) / f"{name}.json").write_text(json.dumps(shown, indent=2) + "\n")


ROOTS = ["the harness's skill file", "a held-out scenario"]


@pytest.mark.usefixtures("layer")
@pytest.mark.parametrize("what", ROOTS)
def test_inside_the_layer_a_command_cannot_link_a_file_it_may_not_read_anywhere_it_writes(
    tmp_path: Path, what: str
) -> None:
    with make_layout(tmp_path) as layout:
        source, marker, _ = _sources(layout)[what]
        links = _destinations(layout)
        steps = [_link_unseen(source, links)]
        steps += [tool("Read", file_path=str(link)) for link in links.values()]
        try:
            seen = run_session(layout, steps, layer=True, fields=_fields(layout))
            told = _told(seen)
            outcomes = json.loads((layout.worktree / OUTCOMES).read_text())
            on_host = {where: _same_file(link, source) for where, link in links.items()}
        finally:
            for link in links.values():
                link.unlink(missing_ok=True)
    _report(f"second_name_inside_the_layer_{ROOTS.index(what)}", {"told": outcomes})
    assert on_host == dict.fromkeys(links, False), (on_host, outcomes)
    assert all(marker not in said for said in told), f"a Read of a second name gave {what}"
    assert set(outcomes) == set(links), outcomes
    assert all(said != "linked" for said in outcomes.values()), outcomes


LINK_FORMS = {
    "ln": "ln {source} {link}",
    "ln -f": "ln -f {source} {link}",
    "cp -l": "cp -l {source} {link}",
    "link": "link {source} {link}",
}


@pytest.mark.parametrize("form", sorted(LINK_FORMS))
@pytest.mark.parametrize("what", ROOTS)
def test_without_the_layer_a_command_naming_a_file_it_may_not_read_for_a_link_is_refused(
    tmp_path: Path, what: str, form: str
) -> None:
    with make_layout(tmp_path) as layout:
        source, marker, reason = _sources(layout)[what]
        link = layout.worktree / "hl.md"
        command = LINK_FORMS[form].format(source=source, link=link)
        steps = [
            tool("Bash", command=command, description="link"),
            tool("Read", file_path=str(link)),
        ]
        seen = run_session(layout, steps, layer=False, fields=_fields(layout))
        told = _told(seen)
        made = link.exists()
    assert not made, f"{form} made a second name for {what}"
    assert reason in told[0], f"{form} naming {what} was not refused for it: {told[0][:300]!r}"
    assert all(marker not in said for said in told)


@pytest.mark.parametrize("what", ROOTS)
def test_without_the_layer_a_link_made_unseen_in_the_worktree_is_refused_to_a_read(
    tmp_path: Path, what: str
) -> None:
    with make_layout(tmp_path) as layout:
        source, marker, _ = _sources(layout)[what]
        link = layout.worktree / "hl.md"
        steps = [_link_unseen(source, {"the worktree": link}), tool("Read", file_path=str(link))]
        seen = run_session(layout, steps, layer=False, fields=_fields(layout))
        told = _told(seen)
        made = _same_file(link, source)
    # Measured, not wanted: without the layer nothing stops a command that builds its paths.
    assert made, "the command made no link, so the row shows nothing about the read"
    assert marker not in told[1], f"a Read of the worktree's second name gave {what}"
    assert SECOND_NAME in told[1], f"the Read was not refused for the second name: {told[1]!r}"


# -- known residuals, without the layer: each row asserts what happens today and names it ------


def test_known_residual_without_the_layer_a_path_decoded_in_an_interpreter_is_read(
    tmp_path: Path,
) -> None:
    with make_layout(tmp_path) as layout:
        source, marker, _ = _sources(layout)["the harness's skill file"]
        command = (
            'python3 -c "import base64; '
            f"print(open(base64.b64decode('{_encoded(source)}').decode()).read())\""
        )
        seen = run_session(
            layout, [tool("Bash", command=command, description="read")], layer=False,
            fields=_fields(layout),
        )  # fmt: skip
        told = _told(seen)
    # The known residual: no hook sees a path that exists only once the command runs.
    assert marker in told[0], "the residual is closed: move this row to the refused ones"


def test_known_residual_without_the_layer_a_path_assembled_from_a_substitution_is_read(
    tmp_path: Path,
) -> None:
    with make_layout(tmp_path) as layout:
        source, marker, _ = _sources(layout)["the harness's skill file"]
        whole = str(source)
        cut = whole.index("/harness/") + len("/har")
        command = f"cat $(printf '%s' {whole[:cut]}){whole[cut:]}"
        seen = run_session(
            layout, [tool("Bash", command=command, description="read")], layer=False,
            fields=_fields(layout),
        )  # fmt: skip
        told = _told(seen)
    assert marker in told[0], "the residual is closed: move this row to the refused ones"


def test_known_residual_without_the_layer_a_link_made_unseen_outside_the_worktree_is_read(
    tmp_path: Path,
) -> None:
    # The same class as the two above: the command that makes the link builds its paths as it
    # runs. The path hook refuses a second name in the worktree only, since a session reads
    # files with a second name outside it for reasons of their own.
    with make_layout(tmp_path) as layout:
        source, marker, _ = _sources(layout)["the harness's skill file"]
        # A place no rule names: beside the run, outside every root and the shared directories.
        (layout.outside / "elsewhere").mkdir()
        link = layout.outside / "elsewhere" / "hl.md"
        steps = [_link_unseen(source, {"elsewhere": link}), tool("Read", file_path=str(link))]
        try:
            seen = run_session(layout, steps, layer=False, fields=_fields(layout))
            told = _told(seen)
        finally:
            link.unlink(missing_ok=True)
    assert marker in told[1], "the residual is closed: move this row to the refused ones"


def test_without_the_layer_a_link_made_unseen_in_a_shared_temporary_directory_is_refused(
    tmp_path: Path,
) -> None:
    # Once the residual above: a shared temporary directory is refused to every read of a
    # session's file tools, whatever was put there and however.
    with make_layout(tmp_path) as layout:
        source, marker, _ = _sources(layout)["the harness's skill file"]
        link = _destinations(layout)["the shared temporary directory"]
        steps = [_link_unseen(source, {"elsewhere": link}), tool("Read", file_path=str(link))]
        try:
            seen = run_session(layout, steps, layer=False, fields=_fields(layout))
            told = _told(seen)
        finally:
            link.unlink(missing_ok=True)
    assert marker not in told[1] and "own temporary directory" in told[1], told[1]
