"""Serve the scripted endpoint for a dry run of the example brief: no model, nothing spent.

The real-run drivers' own scripting, keyed to this run's seed: the decomposition plans the two
modules; the control session does the fixture's work at the size the bounds allow for; the
firmware session writes its stand-in node; every review reads its packet and answers on the
role's promoted rubric, and the control subtask's first review rejects (or, with
``--control blocked``, is blocked), so the repair path runs. The launch script points the run
at the printed URL.

    python scripts/demo/dry_endpoint.py --seed 21

Prints one JSON line with the URL and the dummy key the run presents, serves until SIGTERM or
SIGINT, then prints what it saw.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration" / "orchestrator"))

import real_domain_roles as base  # noqa: E402
import real_paired_reviewers as paired  # noqa: E402
from scripted_endpoint import DUMMY_KEY, Script, serving  # noqa: E402

from physgate.orchestrator.decompose import mint_id  # noqa: E402


def main() -> None:
    """Serve until stopped."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True, help="the run's seed")
    parser.add_argument("--control", choices=["reject", "blocked"], default="reject")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    paired.use_fixture()
    # The drivers mint the subtask ids from their own seed; this run's are minted from its.
    base.SEED = args.seed
    base.CONTROL_ID = mint_id(args.seed, 0, "control")
    base.FIRMWARE_ID = mint_id(args.seed, 1, "firmware")
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    with serving(Script(main=[]), port=args.port) as (api, url):
        base.dry_script(api)
        paired.dry_control(api)
        paired.dry_reviews(api, args.control)
        print(
            json.dumps(
                {
                    "url": url,
                    "key": DUMMY_KEY,
                    "control_id": base.CONTROL_ID,
                    "firmware_id": base.FIRMWARE_ID,
                }
            ),
            flush=True,
        )
        while not stop.wait(0.5):
            pass
        print(
            json.dumps({"requests": len(api.requests), "failures": list(api.failures)}), flush=True
        )


if __name__ == "__main__":
    main()
