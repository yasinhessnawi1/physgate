"""No shell started outside a session's sandbox reads a startup file the session controls.

Claude Code starts shells of its own outside the sandbox it runs a session's commands in.
Measured through the real binaries on macOS (12.11.2026), each a child of the binary itself and
none the harness's own wrapper:

- once at the session's start, ``zsh -c env`` and the login shell that writes the session's
  shell snapshot (``zsh -c -l``), which also sources ``$HOME/.zshrc`` by name;
- on 2.1.301, before every command, the shell that launches the sandbox
  (``zsh -c 'env ... sandbox-exec ...'``).

zsh reads ``.zshenv`` on every start and the rest of its family in a login shell, from
``$ZDOTDIR`` where that is set and from the home otherwise. The home is writable to the
session's commands, so a startup file there ran with none of the sandbox's bounds: it wrote
where no sandboxed process can and read what the sandbox denies.

Four things close it, each on its own:

- **no session writes one.** Every name in :data:`NAMES` in the session's home is a protected
  root: refused to the file tools and to a shell command that names it, write-denied by the
  sandbox, and put back by the sentinel;
- **no shell of the binary reads one there.** The session's environment points ``ZDOTDIR`` at
  an empty directory among the session's own files, which no session writes
  (:data:`ZDOTDIR_NAME`), so zsh looks for its startup files there and finds none; and the
  environment never carries ``BASH_ENV`` or ``ENV``, which name a file bash or sh would read;
- **the one file zsh is told to read by name is a directory of the harness's.** ``ZDOTDIR``
  does not move the snapshot step's own ``source ~/.zshrc``, and that step runs at the
  session's first command, not at its start (measured: a ``.zshrc`` the Write tool made
  before the first command ran outside the sandbox). So the home holds an empty directory
  of that name (:data:`HELD`), made at the install: a file tool cannot write a file where a
  directory is, a sandboxed command cannot touch it, and zsh sources a directory as nothing,
  without a word;
- **no session starts on a home that holds one.** A home holding any startup file is
  refused at the install and again at the spawn, which holds the directory's place first.

**What stays open** is bash where the binary itself runs it (Linux): bash has no ``ZDOTDIR``,
and its login shell reads ``.bash_profile``, ``.bash_login`` or ``.profile`` and ``.bashrc``
from the home. Measured through the real binary on Linux (12.11.2026), with the hooks that
judge a path and the sentinel taken out: a ``.bash_profile`` and a ``.bashrc`` the Write tool
made before the first command ran outside the sandbox. There the files are kept out by the
write refusals alone: the hooks' for the file tools, the sandbox's for commands, and the
sentinel after either. A directory in each one's place would close it as on macOS, at the
price of a complaint from every ``bash -l`` a session runs; it is not made.

A session's own commands may set these variables as they like: they run inside the sandbox,
and nothing they export reaches the binary's environment.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping

#: Every startup file a shell reads from the home (or from ``ZDOTDIR``): zsh's family,
#: bash's, the one sh and bash share, and readline's.
NAMES: tuple[str, ...] = (
    ".zshenv",
    ".zprofile",
    ".zshrc",
    ".zlogin",
    ".zlogout",
    ".bashrc",
    ".bash_profile",
    ".bash_login",
    ".profile",
    ".bash_logout",
    ".inputrc",
)

#: The variables that name a file a shell reads as it starts, wherever the file lies.
ENV_FILES: tuple[str, ...] = ("BASH_ENV", "ENV")

#: The variable that tells zsh where its startup files are.
ZDOTDIR = "ZDOTDIR"

#: The empty directory, inside the session's settings directory, that ``ZDOTDIR`` names.
ZDOTDIR_NAME = "zdotdir"


#: The names the home holds as an empty directory of the harness's own: what a shell of the
#: binary reads from the home by name, whatever ``ZDOTDIR`` says.
HELD: tuple[str, ...] = (".zshrc",)


def _empty_directory(path: str) -> bool:
    """Whether ``path`` is a real directory (no link) that holds nothing."""
    try:
        return stat.S_ISDIR(os.lstat(path).st_mode) and not os.listdir(path)
    except OSError:
        return False


def hold(home: str) -> None:
    """Make each of :data:`HELD` in ``home`` as an empty directory, where nothing is there yet.

    What is there already is left as it is, for :func:`home_refusal` to judge.
    """
    os.makedirs(home, exist_ok=True)
    for name in HELD:
        path = os.path.join(home, name)
        if not os.path.lexists(path):
            os.mkdir(path, 0o755)


def present(home: str) -> tuple[str, ...]:
    """The startup files ``home`` holds, whatever each is (a file, a link, a directory).

    A name of :data:`HELD` that is the harness's empty directory is not one.
    """
    return tuple(
        name
        for name in NAMES
        if os.path.lexists(os.path.join(home, name))
        and not (name in HELD and _empty_directory(os.path.join(home, name)))
    )


def home_refusal(home: str) -> str | None:
    """Why no session starts on ``home``: it holds a startup file; ``None`` when it holds none."""
    found = present(home)
    if not found:
        return None
    return (
        f"the session's home ({home}) already holds a shell startup file "
        f"({', '.join(found)}), which a shell outside the sandbox would run"
    )


def zdotdir_refusal(path: str, home: str) -> str | None:
    """Why ``path`` cannot be the session's ``ZDOTDIR``; ``None`` when it can.

    It must be a real directory (no link), hold nothing, and lie outside ``home``, where the
    session's commands write.
    """
    if not os.path.isabs(path):
        return f"{ZDOTDIR} ({path!r}) is not an absolute path"
    real_home = os.path.realpath(home)
    if os.path.realpath(path) == real_home or os.path.realpath(path).startswith(real_home + os.sep):
        return f"{ZDOTDIR} ({path}) lies in the session's home, which its commands write"
    try:
        mode = os.lstat(path).st_mode
    except OSError:
        return f"{ZDOTDIR} ({path}) is not there"
    if not stat.S_ISDIR(mode):
        return f"{ZDOTDIR} ({path}) is not a directory of its own"
    try:
        held = sorted(os.listdir(path))
    except OSError:
        return f"{ZDOTDIR} ({path}) cannot be listed"
    if held:
        return f"{ZDOTDIR} ({path}) is not empty: it holds {', '.join(held)}"
    return None


def spawn_refusal(env: Mapping[str, str]) -> str | None:
    """Why a session is not spawned with ``env``; ``None`` when no startup file can reach it.

    Held at the spawn itself, on the environment the binary gets, whoever built it.
    """
    named = [name for name in ENV_FILES if name in env]
    if named:
        return (
            f"the session's environment sets {', '.join(named)}, which names a file a shell "
            "reads as it starts"
        )
    home = env.get("HOME")
    if not home:
        return "the session's environment names no home, so its startup files cannot be checked"
    where = env.get(ZDOTDIR)
    if where is None:
        return (
            f"the session's environment sets no {ZDOTDIR}, so zsh would read its startup "
            "files from the home, which the session's commands write"
        )
    return zdotdir_refusal(where, home) or home_refusal(home)
