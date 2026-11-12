"""A server started under a fresh bytecode cache answers its first trace, not a 500.

Python imports its time parser (``_strptime``) on the first parse, not at start. The UI's guard
refuses every open outside the roots it serves once it is installed, and a bytecode cache kept
outside them (a fresh ``PYTHONPYCACHEPREFIX``) is such an open: the trace route, which parses the
run's times, then answered 500 on its first request, a fault that read as the server's own. So
the parser is imported when the server is made, before the guard is installed.

The row starts a server in a process of its own, under a cache directory nothing has written,
and asks for a run's trace before anything else; that process had not imported the parser.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from ui_rig import evaluation_rig, fake_ui

RUN = "run-trace"
TESTS = Path(__file__).resolve().parents[2]

#: The process the server runs in: nothing but the server's own modules, then one request.
SERVE = """
import json, sys
sys.path[:0] = [sys.argv[1]]
from ui_rig import context_over, serving
from pathlib import Path
before = "_strptime" in sys.modules
with serving(context_over(Path(sys.argv[2]), ui_root=Path(sys.argv[3]))) as live:
    status, _, body = live.request("GET", sys.argv[4])
print(json.dumps({"imported_before": before, "status": status, "body": body[:300].decode()}))
"""


def test_the_first_trace_under_a_fresh_cache_is_answered(tmp_path: Path) -> None:
    rig = evaluation_rig()
    runs = tmp_path / "runs"
    rig.fake_run(runs, RUN, rig.target_repo(tmp_path / RUN))
    ui = fake_ui(tmp_path / "checkout")
    cache = tmp_path / "fresh-pycache"
    cache.mkdir()
    env = {**os.environ, "PYTHONPYCACHEPREFIX": str(cache)}
    done = subprocess.run(
        [sys.executable, "-c", SERVE, str(TESTS), str(runs), str(ui), f"/api/runs/0/{RUN}/trace"],
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-2000:]
    answer = json.loads(done.stdout.strip().splitlines()[-1])
    # The control: the process had not parsed a time before the server was made.
    assert answer["imported_before"] is False
    assert answer["status"] == 200, answer["body"]
