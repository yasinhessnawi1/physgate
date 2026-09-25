"""The shell layer refuses the obvious ways a command reaches a protected path.

It is the first of two layers. The cases at the end of this file are the ones it
deliberately does not see, asserted as allowed here so that the boundary with
the sentinel is written down rather than assumed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hook_helpers import bash

from physgate.hooks import shell_paths as sp
from physgate.hooks.config import SessionConfig
from physgate.hooks.runtime import HookInput
from physgate.hooks.settings import GATE_REASON, STORE_REASON, InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation

FILES = {
    "worktree/src/physgate/gate/check.py": "CHECK = True\n",
    "worktree/src/physgate/electrical/driver.py": "x = 1\n",
    "worktree/experiments/R-OP-01/RESULT.md": "result\n",
    "worktree/experiments/R-NEW-01/CRITERIA.md": "criteria\n",
    "worktree/docs/.keep": "",
    "store/journal.jsonl": "",
    "outside/heldout/scenario_01.json": "{}\n",
    "outside/home/.claude/settings.json": "{}\n",
}


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    for rel, content in FILES.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    monkeypatch.setenv("HOME", str(tmp_path / "outside" / "home"))
    monkeypatch.setenv("STORE", str(tmp_path / "store"))
    return tmp_path


def _config(root: Path, profile: str = "role") -> SessionConfig:
    return build_config(
        InstallRequest(
            profile=profile,  # type: ignore[arg-type]
            role="electrical" if profile == "role" else None,
            worktree=str(root / "worktree"),
            own_branch=None,
            store_root=str(root / "store"),
            state_dir=str(root / "outside" / "state"),
            target_dir=str(root / "outside" / "session"),
            claude_config_dir=str(root / "outside" / "cfg"),
            user_home=str(root / "outside" / "home"),
            token_ceiling=1000,
            held_out=(str(root / "outside" / "heldout"),),
        ),
        installation(),
    )


def _decide(root: Path, command: str, profile: str = "role", **tool_input: object) -> str:
    event = bash(command, cwd=str(root / "worktree"))
    event["tool_input"].update(tool_input)
    decision = sp.pre_tool_use(HookInput.model_validate(event), _config(root, profile))
    return "allow" if decision.allow else decision.reason


REFUSED = [
    ("cat > src/physgate/gate/x.py <<'EOF'\nPASS = True\nEOF\n", GATE_REASON),
    ("echo x >> src/physgate/gate/check.py", GATE_REASON),
    ("echo x | tee src/physgate/gate/check.py", GATE_REASON),
    ("tee -a .env < /dev/null", "secrets"),
    ("cp /tmp/x src/physgate/gate/check.py", GATE_REASON),
    ("mv src/physgate/gate/check.py /tmp/", GATE_REASON),
    ("rm -rf src/physgate/gate", GATE_REASON),
    ("ln -s /tmp/evil.py src/physgate/gate/evil.py", GATE_REASON),
    ("sed -i '' 's/True/False/' src/physgate/gate/check.py", GATE_REASON),
    ("python3 -c \"open('src/physgate/gate/x.py','w').write('x')\"", GATE_REASON),
    ("git mv src/physgate/electrical/driver.py src/physgate/gate/driver.py", GATE_REASON),
    ("curl -o src/physgate/gate/x.py file:///etc/hosts", GATE_REASON),
    ("dd if=/dev/zero of=src/physgate/gate/x.py count=1", GATE_REASON),
    ("sort -osrc/physgate/gate/sorted.txt README.md", GATE_REASON),
    ("find src/physgate/gate -name '*.py' -delete", GATE_REASON),
    ("cd src/physgate && echo x > gate/y.py", GATE_REASON),
    ("cd src/physgate/gate && touch new.py", GATE_REASON),
    ("cd src/physgate/gate && make", GATE_REASON),
    ("echo x > src/physgate/g?te/new.py", GATE_REASON),
    ("echo x > src/physgate/GATE/new.py", GATE_REASON),
    ("echo '{}' > ~/.claude/settings.json", "later sessions read"),
    ('printf x >> "$STORE/journal.jsonl"', STORE_REASON),
    ("echo x > experiments/R-OP-01/RESULT.md", "published result"),
    ("sed -i s/a/b/ experiments/R-NEW-01/CRITERIA.md", "pre-registered criteria"),
    ("cat ../outside/heldout/scenario_01.json", "held-out"),
    ("grep secret < ../outside/heldout/scenario_01.json", "held-out"),
    ("sleep 1 &", sp.BACKGROUND),
    ("nohup python3 run.py", sp.BACKGROUND),
    ("setsid python3 run.py", sp.BACKGROUND),
    ("(echo x > a.txt &)", sp.BACKGROUND),
    ("sh -c 'echo x > a.txt & wait'", sp.BACKGROUND),
    ("claude -p hello", sp.NESTED_SESSION),
    ("claude --bare -p 'write the gate'", sp.NESTED_SESSION),
    ("/Users/someone/.local/share/claude/versions/2.1.272 -p x", sp.NESTED_SESSION),
    ("npx @anthropic-ai/claude-code -p x", sp.NESTED_SESSION),
    ("env A=1 exec claude --setting-sources user -p x", sp.NESTED_SESSION),
    ("echo 'unterminated", "could not be split"),
]

ALLOWED = [
    "cat src/physgate/gate/check.py",
    "grep -rn CHECK src/physgate/gate",
    "ls -la experiments/R-OP-01",
    "diff src/physgate/gate/check.py /tmp/other.py",
    "git diff -- src/physgate/gate",
    "git log -- .env",
    "find src/physgate/gate -name '*.py'",
    "head -5 experiments/R-OP-01/RESULT.md > /tmp/copy.md",
    "echo x > src/physgate/electrical/new.py",
    "cd src/physgate/electrical && echo x > y.py",
    "python3 -m pytest -q tests/",
    "echo 'use the gateway' > notes.txt",
    "git commit -m 'tidy the electrical driver'",
    "cat <<'EOF' > docs/notes.md\nNever write src/physgate/gate/check.py\nEOF\n",
    "ls 2>&1 | wc -l",
]


@pytest.mark.parametrize(("command", "reason"), REFUSED, ids=[c[:60] for c, _ in REFUSED])
def test_a_command_reaching_a_protected_path_is_refused(
    root: Path, command: str, reason: str
) -> None:
    told = _decide(root, command)
    assert told != "allow", "the command was allowed"
    assert reason in told


@pytest.mark.parametrize("command", ALLOWED, ids=[c[:60] for c in ALLOWED])
def test_an_ordinary_or_read_only_command_is_allowed(root: Path, command: str) -> None:
    assert _decide(root, command) == "allow"


def test_a_call_flagged_to_run_in_the_background_is_refused(root: Path) -> None:
    assert _decide(root, "python3 run.py", run_in_background=True) == sp.BACKGROUND


def test_the_held_out_tier_may_not_even_be_read_by_a_role(root: Path) -> None:
    assert "held-out" in _decide(root, "cat ../outside/heldout/scenario_01.json", "role")
    assert _decide(root, "cat ../outside/heldout/scenario_01.json", "orchestrator") == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "d=ga; echo x > src/physgate/${d}te/x.py",
        "echo x > $(printf src/physgate/ga)te/x.py",
        "python3 -c \"import os; open(os.path.join('src','physgate','ga'+'te','x.py'),'w')\"",
        "tar -xf payload.tar",
        "git apply payload.patch",
    ],
    ids=["variable", "substitution", "string-built-path", "archive", "patch"],
)
def test_what_this_layer_cannot_see_is_left_to_the_sentinel(root: Path, command: str) -> None:
    # Allowed here on purpose. Each reaches the gate only at run time, through
    # a value this layer cannot know before the command runs. The sentinel
    # compares the protected paths after the call, and the bypass suite proves
    # it catches exactly these forms.
    assert _decide(root, command) == "allow"


def test_a_writing_command_is_refused_when_the_call_starts_inside_the_gate(root: Path) -> None:
    # A later call can start in a directory an earlier call reached through a cd
    # this layer could not follow. The command names no path, but its own name
    # resolves inside the gate, as every word does against the working directory.
    event = bash("make", cwd=str(root / "worktree" / "src" / "physgate" / "gate"))
    decision = sp.pre_tool_use(HookInput.model_validate(event), _config(root))
    assert GATE_REASON in decision.reason
    reader = bash("ls -la", cwd=str(root / "worktree" / "src" / "physgate" / "gate"))
    assert sp.pre_tool_use(HookInput.model_validate(reader), _config(root)).allow


@pytest.mark.parametrize(
    "command",
    [
        "git diff --output=src/physgate/gate/check.py",
        "git log --output src/physgate/gate/log.txt -- README.md",
        "git show HEAD --output=.env",
        "git grep -O vim CHECK -- src/physgate/gate",
        "find src/physgate/gate -name '*.py' -fprint src/physgate/gate/list.txt",
        "find src/physgate/gate -fprint0 /tmp/x",
        "find src/physgate/gate -fprintf /tmp/x '%p'",
        "find src/physgate/gate -fls /tmp/x",
        "tree -o src/physgate/gate/tree.txt src/physgate",
        "less -o src/physgate/gate/log.txt README.md",
        "less --log-file=src/physgate/gate/log.txt README.md",
        "less -osrc/physgate/gate/log.txt README.md",
        "rg --pre ./payload.sh CHECK src/physgate/gate",
        "file -C -m src/physgate/gate/magic",
    ],
)
def test_a_reader_carrying_a_flag_that_writes_is_a_writer(root: Path, command: str) -> None:
    told = _decide(root, command)
    assert GATE_REASON in told or "secrets" in told


@pytest.mark.parametrize(
    "command",
    [
        "git diff --stat -- src/physgate/gate",
        "find src/physgate/gate -name '*.py' -print",
        "tree src/physgate/gate",
        "rg CHECK src/physgate/gate",
        "less src/physgate/gate/check.py",
        "file src/physgate/gate/check.py",
    ],
)
def test_the_same_readers_without_those_flags_still_only_read(root: Path, command: str) -> None:
    assert _decide(root, command) == "allow"


def test_a_commit_message_naming_a_protected_path_is_refused_with_the_route_around_it(
    root: Path,
) -> None:
    told = _decide(root, "git commit -m 'explain why src/physgate/gate/check.py is protected'")
    assert GATE_REASON in told
    assert "git commit -F <file>" in told
    assert "git commit -F" not in _decide(root, "cp /tmp/x src/physgate/gate/check.py")
    (root / "worktree" / "msg.txt").write_text("explain src/physgate/gate/check.py\n")
    assert _decide(root, "git commit -F msg.txt") == "allow"
