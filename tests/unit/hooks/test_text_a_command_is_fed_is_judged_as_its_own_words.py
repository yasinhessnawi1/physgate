"""Text a command reads on its input is judged as that command's own words.

A here-document's body and a here-string are invisible to a check that reads only a
command's arguments and redirections, and some programs open the paths their input names:
``sqlite3`` given ``.import <file>`` reads that file. So the text is scanned for the paths it
names, as written (nothing in it is expanded):

- for a command that only reads, as an argument of a reader is judged: only what may not
  even be named (the held-out tier, a corpus that carries its own answers, a reviewer's
  material) refuses, so ``cat > notes.md <<'EOF'`` may still mention a protected file;
- for any other command, as its arguments are: every protected path refuses.

What the shell itself runs from such text is parsed as commands: every substitution in a
body whose delimiter is unquoted, and the whole body when it is a shell's own script.

What no parse can see is a program that builds a path at run time from text it reads (a
script on ``python -``'s input that joins its parts). That is a recorded residual.

Every case uses inert markers: a held-out stand-in file and a temporary refuse-only root.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from hook_helpers import bash

from physgate.hooks import shell
from physgate.hooks import shell_paths as sp
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.reasons import HELD_OUT_REASON
from physgate.hooks.settings import InstallRequest, build_config, current_installation

ROOT = ".physgate/series"


def _request(tmp_path: Path, profile: str = "role") -> InstallRequest:
    base = Path(os.path.realpath(tmp_path))
    worktree = base / "wt"
    if not worktree.exists():
        (worktree / ROOT).mkdir(parents=True)
        (worktree / "modules" / "control").mkdir(parents=True)
        # A protected root without a leading dot, so that a literal `*` in a program's
        # input, if it were expanded, would name it.
        (worktree / "knowledge").mkdir()
        held = base / "outside" / "heldout"
        held.mkdir(parents=True)
        (held / "scenario_01.json").write_text('{"marker": "held-out stand-in"}\n')
    return InstallRequest(
        profile=profile,  # type: ignore[arg-type]
        role="control" if profile == "role" else None,
        worktree=str(worktree),
        own_branch="b" if profile == "role" else None,
        store_root=None,
        state_dir=str(base / "state"),
        target_dir=str(base / "target"),
        claude_config_dir=str(base / "config"),
        user_home=str(base / "home"),
        token_ceiling=40960,
        held_out=(str(base / "outside" / "heldout"),),
        extra_protected_refuse_only=(str(worktree / ROOT),) if profile == "role" else (),
        read_roots=(str(worktree),) if profile == "reviewer" else (),
    )


@pytest.fixture
def config(tmp_path: Path) -> SessionConfig:
    return build_config(_request(tmp_path), current_installation())


def _held(config: SessionConfig) -> str:
    return os.path.join(os.path.dirname(config.worktree), "outside", "heldout", "scenario_01.json")


def _decide(config: SessionConfig, command: str) -> str:
    hook_input = HookInput.model_validate(bash(command, cwd=config.worktree))
    decision = sp.pre_tool_use(hook_input, config)
    return "allow" if decision.allow else decision.reason


# --- the splitter keeps what a command is fed --------------------------------------------


def test_a_here_document_keeps_its_body() -> None:
    (cmd,) = shell.parse("sqlite3 x.db <<'EOF'\n.import /h/s.json t\n.quit\nEOF\n")
    assert cmd.redirects[0].body == ".import /h/s.json t\n.quit\n"


def test_a_tab_stripping_here_document_keeps_its_body_without_leading_tabs() -> None:
    (cmd,) = shell.parse("cat <<-EOF\n\t\tline\n\tEOF\n")
    assert cmd.redirects[0].body == "line\n"


def test_what_an_unquoted_body_runs_is_parsed_and_a_quoted_body_runs_nothing() -> None:
    unquoted = shell.parse("cat <<EOF\n$(touch a) `touch b` \\$(touch c) $((1+2))\nEOF\n")
    assert [c.argv for c in unquoted] == [("cat",), ("touch", "a"), ("touch", "b")]
    quoted = shell.parse("cat <<'EOF'\n$(touch a) `touch b`\nEOF\n")
    assert [c.argv for c in quoted] == [("cat",)]


def test_a_shell_s_own_script_on_its_input_is_parsed_and_a_script_file_s_input_is_not() -> None:
    fed = shell.parse("bash <<'EOF'\ncd x\ntouch y\nEOF\n")
    assert [c.argv for c in fed] == [("bash",), ("cd", "x"), ("touch", "y")]
    string = shell.parse('sh -s a b <<< "touch y"')
    assert [c.argv for c in string] == [("sh", "-s", "a", "b"), ("touch", "y")]
    data = shell.parse("bash script.sh <<'EOF'\ntouch y\nEOF\n")
    assert [c.argv for c in data] == [("bash", "script.sh")]


# --- the held-out tier, named in a command's input -----------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "sqlite3 x.db <<'EOF'\n.import {held} t\nEOF\n",
        "sqlite3 x.db <<< '.import {held} t'",
        "python3 - <<'EOF'\nprint(open('{held}').read())\nEOF\n",
        "cat <<'EOF'\n{held}\nEOF\n",
        "grep -f /dev/stdin data.txt <<< '{held}'",
    ],
    ids=["sqlite-heredoc", "sqlite-here-string", "python-stdin", "reader-heredoc", "reader-string"],
)
def test_input_that_names_the_held_out_tier_is_refused(config: SessionConfig, command: str) -> None:
    told = _decide(config, command.format(held=_held(config)))
    assert HELD_OUT_REASON in told
    assert "fed text" in told


def test_a_reviewer_s_input_is_not_held_to_its_read_allowance(tmp_path: Path) -> None:
    reviewer = build_config(_request(tmp_path, "reviewer"), current_installation())
    # A path outside the allowance, only mentioned in a reader's input, is not a read.
    assert _decide(reviewer, "cat <<'EOF'\nsee /usr/share/dict/words\nEOF\n") == "allow"
    told = _decide(reviewer, f"cat <<'EOF'\n{_held(reviewer)}\nEOF\n")
    assert HELD_OUT_REASON in told


# --- a refuse-only root, written through what a command is fed ------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "python3 - <<'EOF'\nopen('.physgate/series/step.json', 'w').write('{}')\nEOF\n",
        "sqlite3 x.db <<'EOF'\n.output .physgate/series/step.json\nEOF\n",
        "python3 - <<'EOF'\nfor f in glob('.physgate/series/*.json'): pass\nEOF\n",
        "python3 - <<< \"open('.physgate/series/step.json', 'w')\"",
        "cat <<EOF > notes.md\n$(touch .physgate/series/step.json)\nEOF\n",
        "cat <<EOF > notes.md\n`touch .physgate/series/step.json`\nEOF\n",
        "bash <<'EOF'\ncd .physgate\necho '{}' > series/step.json\nEOF\n",
        "sh -s <<< \"cd .physgate && echo '{}' > series/step.json\"",
    ],
    ids=[
        "python-heredoc",
        "sqlite-output",
        "literal-glob",
        "python-here-string",
        "unquoted-substitution",
        "unquoted-backtick",
        "shell-script-heredoc",
        "shell-script-string",
    ],
)
def test_input_that_writes_into_a_refuse_only_root_is_refused(
    config: SessionConfig, command: str
) -> None:
    assert _decide(config, command) != "allow"


@pytest.mark.parametrize(
    "command",
    [
        "cat <<'EOF' > modules/control/notes.md\nNever write .physgate/series/step.json\nEOF\n",
        "cat <<'EOF' > notes.md\n$(touch .physgate/series/step.json)\nEOF\n",
        "cat <<EOF > notes.md\n\\$(touch .physgate/series/step.json)\nEOF\n",
        "python3 - <<'EOF'\nprint(2 * 3, [x for x in 'ab'])\nEOF\n",
        "python3 - <<'EOF'\nimport os\nprint(os.path.join('modules', 'control'))\nEOF\n",
        "bash <<'EOF'\ncd modules/control && echo ok > out.txt\nEOF\n",
        "grep -c x modules/control/sim.py <<< 'unused'",
    ],
    ids=[
        "doc-mentions-root",
        "quoted-substitution",
        "escaped-substitution",
        "glob-characters",
        "ordinary-script",
        "ordinary-shell-script",
        "ordinary-here-string",
    ],
)
def test_ordinary_input_is_allowed(config: SessionConfig, command: str) -> None:
    assert _decide(config, command) == "allow"


# --- what stays out of reach ---------------------------------------------------------------


def test_a_path_a_program_builds_from_its_input_is_not_seen(config: SessionConfig) -> None:
    # Allowed on purpose: the path exists only when the program runs. No parse of the
    # input can know it; a recorded residual for every root no sentinel puts back.
    command = (
        "python3 - <<'EOF'\n"
        "open('.'.join(['', 'physgate']) + '/' + 'ser' + 'ies/step.json', 'w')\n"
        "EOF\n"
    )
    assert _decide(config, command) == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "cat > modules/control/a.js <<'EOF'\nconst s = `${a.b}`;\nEOF\n",
        "cat > modules/control/a.ts <<'EOF'\nconst n = `${items.length} in ${cfg.dir}`;\nEOF\n",
        "cat > modules/control/f.py <<'EOF'\nn = (~valid).sum()\nEOF\n",
        "python3 - <<'EOF'\nprint(~flags)\nEOF\n",
        "cat > modules/control/notes.md <<'EOF'\nresult is ~approx 3\nEOF\n",
        "tee modules/control/notes.md <<'EOF'\nresult is ~approx 3\nEOF\n",
        "cat > modules/control/run.sh <<'EOF'\nout=${name/sim/run}\nEOF\n",
        "cat > modules/control/u.sh <<EOF\nx=${a.b} ~approx ${name/sim/run}\nEOF\n",
        "python3 - <<< 'print(~flags, f\"${a.b}\")'",
    ],
    ids=[
        "js-template",
        "ts-template",
        "numpy-invert",
        "python-stdin-invert",
        "markdown-approx",
        "tee-approx",
        "shell-replace",
        "unquoted-body",
        "here-string",
    ],
)
def test_text_never_refuses_for_a_form_the_layer_does_not_evaluate(
    config: SessionConfig, command: str
) -> None:
    # The shell expands nothing in a quoted body, and in an unquoted one this layer
    # follows only the substitutions it runs: text is judged by the paths it names, as
    # written, and nothing else in it can refuse.
    assert _decide(config, command) == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "bash <<EOF\ncd .physgate\necho '{}' > series/step.json\nEOF\n",
        "sh -s <<'EOF'\ncd .physgate && echo '{}' > series/step.json\nEOF\n",
        "bash /dev/stdin <<EOF\ncd .physgate\necho '{}' > series/step.json\nEOF\n",
        "cat <<EOF > notes.md\n$(touch .physgate/series/step.json)\nEOF\n",
        "cat <<EOF > notes.md\n`touch .physgate/series/step.json`\nEOF\n",
        "d=.physgate; sqlite3 x.db <<EOF\n.output $d/series/step.json\nEOF\n",
        "d=.physgate; python3 - <<< \"open('$d/series/step.json', 'w')\"",
        "python3 - <<'EOF'\nopen('.physgate/series/step.json', 'w')\nEOF\n",
    ],
    ids=[
        "unquoted-shell-script",
        "quoted-shell-script",
        "stdin-shell-script",
        "unquoted-substitution",
        "unquoted-backtick",
        "unquoted-variable",
        "here-string-variable",
        "literal-path",
    ],
)
def test_what_the_shell_runs_or_expands_in_a_body_is_still_judged(
    config: SessionConfig, command: str
) -> None:
    assert _decide(config, command) != "allow"


def test_a_variable_in_a_body_the_shell_expands_is_followed_for_a_reader(
    config: SessionConfig,
) -> None:
    # The variable holds a directory above the tier, so only the expansion names it.
    outside = os.path.dirname(os.path.dirname(_held(config)))
    told = _decide(config, f"o={outside}; cat <<EOF\n$o/heldout/scenario_01.json\nEOF\n")
    assert HELD_OUT_REASON in told
    # In a quoted body the same text is the program's, as written.
    quoted = f"o={outside}; cat <<'EOF' > notes.md\n$o/heldout/scenario_01.json\nEOF\n"
    assert _decide(config, quoted) == "allow"
    # And without the variable, the assignment alone names nothing protected.
    assert _decide(config, "d=.physgate; sqlite3 x.db <<'EOF'\n.output $d/series/f\nEOF\n") == (
        "allow"
    )
