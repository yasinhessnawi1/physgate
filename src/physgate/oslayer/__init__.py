"""The OS layer: the operating system's own bound on what a session's shell commands reach.

Claude Code can run each shell command inside the platform's sandbox: Seatbelt on
macOS, bubblewrap on Linux, nothing on native Windows. Where it can, a session
runs with it on and with the protected paths denied; where it cannot, the run
says so, with the reason. Whether it then goes on is the run's to say (its
``os_layer_absent`` parameter, checked by the orchestrator); nothing here refuses.
"""
