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
  sandbox, and put back by the sentinel. zsh reads a compiled ``<name>.zwc`` beside a startup
  file in its place when it is the newer, so each of those is a name too;
- **no shell of the binary reads one there.** The session's environment points ``ZDOTDIR`` at
  an empty directory among the session's own files, which no session writes
  (:data:`ZDOTDIR_NAME`), so zsh looks for its startup files there and finds none; and the
  environment never carries ``BASH_ENV`` or ``ENV``, which name a file bash or sh would read;
- **every name a shell reads is a directory of the harness's.** ``ZDOTDIR`` does not move the
  snapshot step's own ``source ~/.zshrc``, bash has no ``ZDOTDIR`` at all, and the snapshot
  step runs at the session's first command, not at its start (measured: a ``.zshrc`` the
  Write tool made before the first command ran outside the sandbox on macOS, a
  ``.bash_profile`` and a ``.bashrc`` on Linux). So the home holds an empty directory at
  every name of :data:`HELD`, made at the install: a file tool cannot write a file where a
  directory is, whatever the hooks do, and a sandboxed command cannot touch it. zsh reads a
  directory as nothing, without a word. bash and sh say ``is a directory`` on their standard
  error when a login or interactive shell starts or ends (``bash -l``, ``sh -l``, ``bash -i``)
  and go on: the command's output and exit status are what they were (held by a test);
- **no session starts on a home that holds one.** A home holding any startup file is
  refused at the install and again at the spawn, which holds the directories' places first.

A session's own commands run inside the sandbox, and nothing they export reaches the binary's
environment or any shell it starts for a later command (held by a row through the real binary).
The shell hook also refuses a command whose words set ``BASH_ENV``, or ``ENV`` for a command
that is itself a shell (``shell_paths``): a rule on the words, which an indirect form passes,
and not what bounds them.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping

#: zsh's startup files.
ZSH: tuple[str, ...] = (".zshenv", ".zprofile", ".zshrc", ".zlogin", ".zlogout")
#: What zsh reads in place of each when it lies beside it and is the newer: its compiled form.
ZSH_COMPILED: tuple[str, ...] = tuple(f"{name}.zwc" for name in ZSH)
#: bash's startup files, and the one it shares with sh.
BASH: tuple[str, ...] = (".bashrc", ".bash_profile", ".bash_login", ".profile", ".bash_logout")
#: readline's, which an interactive shell reads.
READLINE: tuple[str, ...] = (".inputrc",)

#: Every startup file a shell reads from the home (or from ``ZDOTDIR``).
NAMES: tuple[str, ...] = (*ZSH, *ZSH_COMPILED, *BASH, *READLINE)

#: The variables that name a file a shell reads as it starts, wherever the file lies.
ENV_FILES: tuple[str, ...] = ("BASH_ENV", "ENV")

#: The variable that tells zsh where its startup files are.
ZDOTDIR = "ZDOTDIR"

#: The empty directory, inside the session's settings directory, that ``ZDOTDIR`` names.
ZDOTDIR_NAME = "zdotdir"


#: The names the home holds as an empty directory of the harness's own: every file a shell
#: runs as it starts or ends. zsh's would be out of play with ``ZDOTDIR`` alone, but for
#: ``.zshrc``; held all the same, so the home is safe whatever the environment says.
HELD: tuple[str, ...] = (*ZSH, *ZSH_COMPILED, *BASH)


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


def own_home_refusal(home: str) -> str | None:
    """Why ``home`` is no session's: it is the home of the user this process runs as."""
    if os.path.realpath(home) == os.path.realpath(os.path.expanduser("~")):
        return f"{home} is the home of the user who runs the harness, and no session's own"
    return None


def environment_refusal(env: Mapping[str, str]) -> str | None:
    """Why a session is not spawned with ``env``, whatever its home holds; ``None`` otherwise.

    Everything that can be judged before anything is made in the home the environment names.
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
    return own_home_refusal(home) or zdotdir_refusal(where, home)


def held_or_refused(env: Mapping[str, str]) -> str | None:
    """Hold the startup files' places in the session's home, or say why it is not spawned.

    Held at the spawn itself, on the environment the binary gets, whoever built it. The
    environment is judged first, and nothing is made in the home of one that is refused; then
    the places are held, where the home was made after the install; then the home is judged.
    """
    refused = environment_refusal(env)
    if refused is not None:
        return refused
    hold(env["HOME"])
    return home_refusal(env["HOME"])
