"""Claude Code as an engine: the one harness every session runs on today.

``engine`` implements the engine interface; ``stream`` reads the binary's captured stream;
``layers`` says which of the system's layers hold around each profile, on what evidence. The
binary's command lines and environment (``orchestrator.invocation``) and its credential files
(``orchestrator.credentials``) are this engine's own, reached by the rest of the system only
through it.
"""

from physgate.engines.claude_code.engine import HARNESS, ClaudeCodeEngine

__all__ = ["HARNESS", "ClaudeCodeEngine"]
