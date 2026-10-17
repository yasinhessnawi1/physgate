"""The OS layer: the operating system's own bound on what a session's shell commands reach.

Claude Code can run each shell command inside the platform's sandbox: Seatbelt on
macOS, bubblewrap on Linux, nothing on native Windows. Where it can, a session
runs with it on and with the protected paths denied; where it cannot, the run
says so, with the reason, and goes on. Refusing a run without it is a policy of
whoever needs one, and lives with them, not here.
"""
