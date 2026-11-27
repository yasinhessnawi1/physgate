"""A stop signal ends a raw session on the real binary cleanly, and the round's next start goes on.

The scripted endpoint has the session run a long shell command; once the session's process facts
are written, the round's own process is sent SIGTERM under the baseline command's stop handler
(:func:`physgate.evaluation.baseline.cli.stopping`). The handler turns the signal into a stop
in the main thread: the raw arm ends its session with its process group and removes its
credential, and the round clears the place and names the stop on a ``signalled`` line. No
process of the session's group is left, no credential file is left in its place, and the next
start keeps the place as a killed session's and runs the entry again, spending nothing.

No model is called and no real credential is read: the endpoint is the scripted one, the key its
dummy, the store the unit rows' stand-in.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from scripted_endpoint import DUMMY_KEY, Script, serving, text, tool

BASELINE_TESTS = Path(__file__).resolve().parents[2] / "unit" / "evaluation" / "baseline"
if str(BASELINE_TESTS) not in sys.path:
    sys.path.insert(0, str(BASELINE_TESTS))

from baseline_fixtures import (  # noqa: E402
    CHECKOUT,
    PRICES,
    SCORED,
    StandInArm,
    harness_run,
    run_set,
    stand_in_store,
)

from physgate.evaluation.baseline.cli import stopping  # noqa: E402
from physgate.evaluation.baseline.runner import (  # noqa: E402
    LEDGER,
    Stopped,
    run_baseline,
    setup_from_run,
)
from physgate.evaluation.observe.cost import load_price_sheet  # noqa: E402
from physgate.evaluation.per_role.arms.raw import RawSetup  # noqa: E402
from physgate.evaluation.tiers.store import work_root  # noqa: E402
from physgate.evaluation.tiers.task import Role  # noqa: E402
from physgate.orchestrator.binaries import measure  # noqa: E402
from physgate.orchestrator.credentials import Credential  # noqa: E402
from physgate.orchestrator.decompose import binary_version  # noqa: E402
from physgate.orchestrator.install import prepare_install  # noqa: E402
from physgate.orchestrator.invocation import claude_binary, session_search_path  # noqa: E402
from physgate.orchestrator.run_config import RunConfig, endpoint_of, network_enforced  # noqa: E402
from physgate.oslayer.probe import judge_here  # noqa: E402

pytestmark = pytest.mark.integration

NO_CACHE_WRITES = {"cache_creation_input_tokens": 0}


def _signal_once_the_session_runs(works: Path, done: threading.Event) -> None:
    """Send this process SIGTERM once a session's process facts are in the work root."""
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline and not done.is_set():
        if list(works.glob("*/place/session/process.json")):
            time.sleep(2.0)  # the session's shell command is under way by then
            os.kill(os.getpid(), signal.SIGTERM)
            return
        time.sleep(0.1)


def _group_alive(pid: int) -> bool:
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_a_stop_signal_ends_a_real_raw_session_and_the_next_start_goes_on() -> None:
    named = os.environ.get("PHYSGATE_TEST_ROOT")
    root = (Path(named) if named else Path.home() / ".cache" / "pg-tests") / secrets.token_hex(6)
    root.mkdir(parents=True)
    try:
        install_bin = prepare_install(
            root / "install" / "hooks", Path(__file__).resolve().parents[3]
        )
        made = stand_in_store(root / "made")
        task = made.tasks["visible"][0]
        binary = claude_binary()
        version = binary_version(binary)
        layer = judge_here(claude_version=version, search_path=session_search_path(binary))
        steps = [
            {**step, "usage": NO_CACHE_WRITES}
            for step in (tool("Bash", command="sleep 300", description="x"), text("done"))
        ]
        out = root / "round"
        with serving(Script(main=steps)) as (_api, url):
            recorded: dict[str, Any] = {
                "claude_version": version,
                "os_layer": layer.model_dump(),
                "network_enforced": network_enforced("none", layer),
                "endpoint": endpoint_of(url),
                "auth": "api_key",
                "binary": measure(binary).model_dump(),
            }
            runs = run_set((harness_run(root / "runs", task, made, **recorded), 0))

            def setup_for(config: RunConfig, role: Role) -> RawSetup:
                return setup_from_run(
                    config,
                    role,
                    binary=binary,
                    credential=Credential("api_key", DUMMY_KEY),
                    install_bin=install_bin,
                    os_layer=layer,
                    role_python=None,
                    base_url=url,
                    harness=CHECKOUT,
                )

            def start(**how: Any) -> Any:  # noqa: ANN401
                return run_baseline(
                    store=made.store,
                    role="control",
                    version=made.version,
                    runs=runs,
                    out=out,
                    setup_for=setup_for,
                    score=lambda _t, _a: dict(SCORED),
                    prices=load_price_sheet(PRICES),
                    base_url=url,
                    sleep=lambda _s: None,
                    **how,
                )

            works = work_root(made.store, "control")
            done = threading.Event()
            sender = threading.Thread(target=_signal_once_the_session_runs, args=(works, done))
            sender.start()
            try:
                with pytest.raises(Stopped), stopping():
                    start()
            finally:
                done.set()
                sender.join()
            lines = [json.loads(x) for x in (out / LEDGER).read_text().splitlines()]
            assert [x["kind"] for x in lines] == ["round", "started", "signalled"]
            assert lines[-1]["signal"] == "SIGTERM" and lines[-1]["cleared"] is True
            (place,) = works.iterdir()
            session = place / "place" / "session"
            facts = json.loads((session / "process.json").read_text())
            assert not _group_alive(int(facts["pid"])), "the session's process group lives on"
            for left in ("state/key", "state/key-helper.sh", "config/.credentials.json"):
                assert not (session / left).exists(), f"{left} is left in the session's place"
            record = start(resume=True, arm=StandInArm())
        assert record.counts["visible"].trials == 1
        kinds = [json.loads(x)["kind"] for x in (out / LEDGER).read_text().splitlines()]
        assert kinds == ["round", "started", "signalled", "killed", "started", "moving", "recorded"]
        assert list(works.iterdir()) == []
    finally:
        shutil.rmtree(root, ignore_errors=True)
