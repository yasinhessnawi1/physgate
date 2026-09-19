"""C5 line counting, per CRITERIA.md S7 C5. Shared scaffolding."""

from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ADAPTER_OPEN = re.compile(r"^\s*#\s*ADAPTER:([\w_]+)\s*$")
ADAPTER_CLOSE = re.compile(r"^\s*#\s*/ADAPTER\s*$")


def counts(path: Path) -> dict:
    """Total counted lines and the adapter-marked subset, by tag."""
    total = 0
    adapter = 0
    by_tag: dict[str, int] = {}
    tag = ""
    for line in path.read_text().splitlines():
        stripped = line.strip()
        opened = ADAPTER_OPEN.match(line)
        if opened:
            tag = opened.group(1)
            continue
        if ADAPTER_CLOSE.match(line):
            tag = ""
            continue
        if not stripped or stripped.startswith("#"):
            continue
        total += 1
        if tag:
            adapter += 1
            by_tag[tag] = by_tag.get(tag, 0) + 1
    return {"file": path.name, "counted_lines": total, "adapter_lines": adapter, "by_tag": by_tag}


if __name__ == "__main__":
    report = {
        "C5a_baseline": counts(HERE / "baseline_store.py"),
        "C5b_openpersona": counts(HERE / "openpersona_store.py"),
        "shared": [
            counts(HERE / n)
            for n in ("protocol.py", "generator.py", "harness.py", "stores.py",
                      "crash_child.py", "crash_verify.py", "run.py", "loc.py")
        ],
    }
    report["C5c_adapter_lines"] = report["C5b_openpersona"]["adapter_lines"]
    report["shared_total"] = sum(s["counted_lines"] for s in report["shared"])
    (HERE.parent / "metrics" / "c5_loc.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
