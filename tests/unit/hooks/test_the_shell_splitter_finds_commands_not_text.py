"""The splitter returns the commands a shell would run, and none of the text around them."""

from __future__ import annotations

import pytest

from physgate.hooks.shell import Redirect, ShellSyntaxError, parse, unwrap


def _argvs(command: str) -> list[tuple[str, ...]]:
    return [c.argv for c in parse(command)]


def test_separators_split_commands() -> None:
    assert _argvs("a 1; b 2 && c || d | e |& f\ng") == [
        ("a", "1"),
        ("b", "2"),
        ("c",),
        ("d",),
        ("e",),
        ("f",),
        ("g",),
    ]


def test_quotes_are_removed_and_keep_words_together() -> None:
    assert _argvs("""echo 'a b' "c d" e\\ f""") == [("echo", "a b", "c d", "e f")]


def test_a_heredoc_body_is_not_a_command_and_its_redirects_are_recorded() -> None:
    commands = parse("cat <<'EOF' > out.md\nrm -rf /\nEOF\nls")
    assert [c.argv for c in commands] == [("cat",), ("ls",)]
    assert commands[0].redirects == (Redirect("<<", "EOF"), Redirect(">", "out.md"))


def test_a_tab_stripped_heredoc_ends_at_an_indented_terminator() -> None:
    assert _argvs("cat <<-END\n\tbody\n\tEND\nnext") == [("cat",), ("next",)]


def test_redirections_with_descriptors_are_not_words() -> None:
    commands = parse("run 2>err.log >>out.log 2>&1 &>both <in")
    assert commands[0].argv == ("run",)
    assert [r.op for r in commands[0].redirects] == [">", ">>", ">&", "&>", "<"]
    assert [r.target for r in commands[0].redirects] == ["err.log", "out.log", "1", "both", "in"]


def test_substitutions_and_subshells_are_parsed_as_commands() -> None:
    assert _argvs("echo $(inner a) `tick b` <(proc c) && (sub d)") == [
        ("inner", "a"),
        ("tick", "b"),
        ("proc", "c"),
        ("echo", "$(inner a)", "`tick b`", "<(proc c)"),
        ("sub", "d"),
    ]


def test_the_string_given_to_a_shell_or_eval_is_parsed() -> None:
    assert ("inner", "x") in _argvs("bash -c 'inner x'")
    assert ("inner", "y") in _argvs('sh -ec "inner y"')
    assert ("inner", "z") in _argvs("eval inner z")


def test_a_comment_is_not_a_command() -> None:
    assert _argvs("ls # rm -rf /") == [("ls",)]


def test_variables_and_substitutions_are_marked_dynamic() -> None:
    (cmd,) = [c for c in parse('run "$HOME/x" plain $(date)') if c.argv[0] == "run"]
    assert cmd.dynamic == frozenset({1, 3})


def test_leading_assignments_are_separated_from_the_command() -> None:
    (cmd,) = parse("A=1 B=two run x")
    assert (cmd.assignments, cmd.argv) == (("A=1", "B=two"), ("run", "x"))


def test_a_trailing_ampersand_marks_the_command_as_backgrounded() -> None:
    commands = parse("slow & fast")
    assert [(c.argv, c.background) for c in commands] == [(("slow",), True), (("fast",), False)]


def test_wrappers_are_unwrapped_to_the_command_they_run() -> None:
    assert unwrap(("env", "-u", "X", "A=1", "nice", "-n", "5", "git", "log")) == ("git", "log")
    assert unwrap(("/usr/bin/env", "command", "exec", "git")) == ("git",)


@pytest.mark.parametrize(
    "command",
    ['echo "open', "echo 'open", "echo $(open", "echo `open", "cat <<EOF\nbody", "cat <<", "run >"],
)
def test_what_cannot_be_split_with_confidence_raises(command: str) -> None:
    with pytest.raises(ShellSyntaxError):
        parse(command)
