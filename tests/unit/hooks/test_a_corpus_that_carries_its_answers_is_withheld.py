"""An evaluation corpus that states its own answers: written by no session, read by no reviewer.

The injected-error corpus documents, for each artefact, the error it carries
and the check expected to catch it. The measurement it serves counts the
errors a reviewer approved; a reviewer that could read the corpus would be
reading the answer. So its directory is an answer key: every profile is refused
a write to it, through every file tool and the shell, and the reviewer profile
is refused a read too. The worktree's own ``corpora`` directory is always one;
a spawner may name more, such as the corpus a reviewer outside that worktree is
judged on.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from hook_helpers import bash, event

from physgate.hooks import paths
from physgate.hooks import shell_paths as sp
from physgate.hooks.config import HookInput, SessionConfig
from physgate.hooks.reasons import ANSWER_KEY_REASON
from physgate.hooks.settings import InstallRequest, build_config
from physgate.hooks.settings import current_installation as installation

ARTEFACT = "injected-errors/v1/artefacts/a01.json"


@pytest.fixture
def root(tmp_path: Path) -> Path:
    for corpus in (tmp_path / "worktree" / "corpora", tmp_path / "outside" / "corpus"):
        (corpus / ARTEFACT).parent.mkdir(parents=True)
        (corpus / ARTEFACT).write_text('{"class": "unit"}\n')
    (tmp_path / "worktree" / "notes.md").write_text("free\n")
    return tmp_path


def _config(root: Path, profile: str) -> SessionConfig:
    return build_config(
        InstallRequest(
            profile=profile,  # type: ignore[arg-type]
            role="electrical" if profile == "role" else None,
            worktree=str(root / "worktree"),
            own_branch=None,
            store_root=None,
            state_dir=str(root / "outside" / "state"),
            target_dir=str(root / "outside" / "session"),
            claude_config_dir=str(root / "outside" / "cfg"),
            user_home=str(root / "outside" / "home"),
            token_ceiling=1000,
            answer_keys=(str(root / "outside" / "corpus"),),
        ),
        installation(),
    )


def _tool(root: Path, tool: str, target: str, profile: str) -> str:
    key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    hook_input = HookInput.model_validate(
        event(tool_name=tool, cwd=str(root / "worktree"), tool_input={key: target})
    )
    decision = paths.pre_tool_use(hook_input, _config(root, profile))
    return "allow" if decision.allow else decision.reason


def _shell(root: Path, command: str, profile: str) -> str:
    decision = sp.pre_tool_use(
        HookInput.model_validate(bash(command, cwd=str(root / "worktree"))), _config(root, profile)
    )
    return "allow" if decision.allow else decision.reason


CORPORA = ["corpora/" + ARTEFACT, "../outside/corpus/" + ARTEFACT]
IDS = ["the worktree's corpora", "a corpus named by the spawner"]


@pytest.mark.parametrize("target", CORPORA, ids=IDS)
@pytest.mark.parametrize("profile", ["role", "reviewer", "orchestrator"])
@pytest.mark.parametrize("tool", ["Write", "Edit", "NotebookEdit"])
def test_no_profile_writes_a_corpus_through_a_file_tool(
    root: Path, target: str, profile: str, tool: str
) -> None:
    assert ANSWER_KEY_REASON in _tool(root, tool, target, profile)


@pytest.mark.parametrize("target", CORPORA, ids=IDS)
def test_a_reviewer_cannot_read_a_corpus(root: Path, target: str) -> None:
    assert ANSWER_KEY_REASON in _tool(root, "Read", target, "reviewer")


@pytest.mark.parametrize("target", CORPORA, ids=IDS)
@pytest.mark.parametrize("profile", ["role", "orchestrator"])
def test_the_other_profiles_may_read_it(root: Path, target: str, profile: str) -> None:
    assert _tool(root, "Read", target, profile) == "allow"


@pytest.mark.parametrize(
    "command",
    [
        "cat ../outside/corpus/" + ARTEFACT,
        "grep class corpora/injected-errors/v1/artefacts/*.json",
        "ls corpora",
        "cd ../outside && head -1 corpus/" + ARTEFACT,
    ],
    ids=["cat", "grep over a glob", "ls the directory", "after a cd"],
)
def test_a_reviewer_cannot_read_a_corpus_through_the_shell(root: Path, command: str) -> None:
    assert ANSWER_KEY_REASON in _shell(root, command, "reviewer")


@pytest.mark.parametrize(
    "command",
    [
        "cat > corpora/" + ARTEFACT + " <<'EOF'\n{}\nEOF\n",
        "echo '{}' > ../outside/corpus/" + ARTEFACT,
        "python3 -c \"open('corpora/" + ARTEFACT + "','w').write('{}')\"",
        "cp notes.md ../outside/corpus/" + ARTEFACT,
        "rm -rf corpora",
    ],
    ids=["heredoc", "redirect", "in-language write", "copy over", "remove"],
)
@pytest.mark.parametrize("profile", ["role", "reviewer"])
def test_no_session_writes_a_corpus_through_the_shell(
    root: Path, command: str, profile: str
) -> None:
    assert ANSWER_KEY_REASON in _shell(root, command, profile)


def test_a_role_may_read_a_corpus_through_the_shell(root: Path) -> None:
    assert _shell(root, "cat corpora/" + ARTEFACT, "role") == "allow"


def test_the_worktree_s_corpora_are_always_an_answer_key_and_are_put_back(root: Path) -> None:
    config = _config(root, "role")
    wanted = {str(root / "worktree" / "corpora"), str(root / "outside" / "corpus")}
    assert set(config.answer_keys) == wanted
    roots = {r.path: r for r in config.protected_roots}
    for path in wanted:
        assert roots[path].reason == ANSWER_KEY_REASON and roots[path].watch == "revert"


def test_other_files_are_untouched_by_the_rule(root: Path) -> None:
    assert _tool(root, "Write", "notes.md", "reviewer") == "allow"
    assert _tool(root, "Read", "notes.md", "reviewer") == "allow"


def test_the_shell_layer_knows_an_answer_key_by_name_even_without_its_protected_root(
    root: Path,
) -> None:
    """A bare word is checked only if it could name something protected.

    The generator also lists every answer key as a protected root, which alone
    would put its name on that list; the configuration is held to the answer
    keys themselves, so a key is never skipped because a root is missing.
    """
    full = _config(root, "reviewer")
    keys_only = full.model_copy(
        update={
            "protected_roots": tuple(
                r for r in full.protected_roots if r.path not in set(full.answer_keys)
            )
        }
    )
    decision = sp.pre_tool_use(
        HookInput.model_validate(bash("ls corpora", cwd=str(root / "worktree"))), keys_only
    )
    assert not decision.allow and ANSWER_KEY_REASON in decision.reason
