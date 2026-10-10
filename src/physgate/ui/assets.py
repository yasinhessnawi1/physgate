"""The built app: loaded into memory once at start, and refused if missing or stale.

The app is built from the ``ui`` directory of the source checkout into
``ui/dist``, which git ignores, so no minified bundle sits in a repository that
is read as evidence and nothing has to be built when the package is installed.
The cost is that a build can be absent or out of date. Both are refused rather
than served: the build writes a stamp holding the digest of everything it was
built from, and the server recomputes that digest from the sources at start and
refuses to start on any difference, naming the command that rebuilds it. A UI
that silently shows yesterday's code is the failure this exists to prevent.

The digest is computed here and nowhere else: the build script calls this
module to write the stamp, so the writer and the checker cannot disagree about
what was hashed.

Every file is read at start and served from memory, so a request never names a
file on disk. Only ``index.html`` and the flat ``assets`` directory are loaded,
only the media types listed, and a link anywhere in the build is refused.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from physgate.ui.exceptions import StartupRefusedError

#: Where the build goes, inside the ``ui`` directory, and its stamp inside that.
DIST = "dist"
STAMP = ".physgate-build.json"

#: What the build is made from, relative to the ``ui`` directory: these files when
#: present, every ``tsconfig*.json``, and every file beneath these directories.
SOURCE_FILES = ("index.html", "package.json", "pnpm-lock.yaml", "vite.config.ts")
SOURCE_DIRS = ("src", "public")

#: The media types the server sends, by extension. A built file of any other kind
#: refuses the start: it is either a build change someone should look at or a file
#: that has no business being served.
MEDIA_TYPES: Mapping[str, str] = {
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
}

BUILD_COMMAND = "scripts/build-ui.sh"


def _source_paths(ui_root: Path) -> list[Path]:
    found = [ui_root / name for name in SOURCE_FILES if (ui_root / name).is_file()]
    found += sorted(p for p in ui_root.glob("tsconfig*.json") if p.is_file())
    for directory in SOURCE_DIRS:
        base = ui_root / directory
        if base.is_dir():
            found += sorted(p for p in base.rglob("*") if p.is_file())
    return sorted(set(found))


def source_digest(ui_root: Path) -> str:
    """The digest of everything the app is built from: each path and its bytes' digest.

    Raises:
        StartupRefusedError: there are no sources at all.
    """
    paths = _source_paths(ui_root)
    if not paths:
        msg = "the UI has no sources to build from"
        raise StartupRefusedError(msg, ui=str(ui_root))
    digest = hashlib.sha256()
    for path in paths:
        relative = path.relative_to(ui_root).as_posix()
        digest.update(relative.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def write_stamp(ui_root: Path) -> Path:
    """Record in the build what it was built from. Called by the build script, after the build.

    Raises:
        StartupRefusedError: there is no build to stamp.
    """
    dist = ui_root / DIST
    if not (dist / "index.html").is_file():
        msg = "there is no build to stamp"
        raise StartupRefusedError(msg, dist=str(dist))
    stamp = dist / STAMP
    stamp.write_text(json.dumps({"sources_sha256": source_digest(ui_root)}, indent=1) + "\n")
    return stamp


#: The name of the ``<meta>`` element that carries the server's action token to its own page.
ACT_TOKEN_META = "physgate-act-token"

#: The name of the ``<meta>`` element that names the operator decisions are recorded under.
OPERATOR_META = "physgate-operator"


@dataclass(frozen=True)
class Assets:
    """The built app in memory: the page, and each asset file's bytes and media type."""

    index: bytes
    files: Mapping[str, tuple[bytes, str]]

    def with_server_meta(self, token: str, operator: str | None) -> Assets:
        """The same build, its page carrying the action token and the operator's name.

        The page reads the token from itself and sends it back with every action, so only a
        page this server served can act: another site's page cannot read this one. The
        operator's name, when one was named, is part of the line a decision writes, so the
        confirmation names it from here; with none, the page has no such element and acts on
        nothing. Both go before ``</head>``, or straight after the doctype of a page with no
        head written out.

        Raises:
            StartupRefusedError: the page has neither, so there is nowhere to put them.
        """
        meta = f'<meta name="{ACT_TOKEN_META}" content="{html.escape(token)}">'
        if operator is not None:
            meta += f'<meta name="{OPERATOR_META}" content="{html.escape(operator)}">'
        return self._with_head(meta.encode())

    def _with_head(self, meta: bytes) -> Assets:
        head = self.index.find(b"</head>")
        if head >= 0:
            return replace(self, index=self.index[:head] + meta + self.index[head:])
        doctype = b"<!doctype html>"
        if self.index[: len(doctype)].lower() == doctype:
            return replace(self, index=doctype + meta + self.index[len(doctype) :])
        msg = "the built page has no head and no doctype to carry the action token"
        raise StartupRefusedError(msg)


def _refuse(message: str, **context: str) -> StartupRefusedError:
    return StartupRefusedError(f"{message}; build it with {BUILD_COMMAND}", **context)


def load(ui_root: Path) -> Assets:
    """The build at ``ui_root/dist``, if it is there, complete and built from today's sources.

    Raises:
        StartupRefusedError: no build, no stamp, a stamp for other sources, a link,
            a nested directory, or a file of a type the server does not send.
    """
    dist = ui_root / DIST
    index_path = dist / "index.html"
    if not index_path.is_file() or index_path.is_symlink():
        raise _refuse("the UI is not built", dist=str(dist))
    try:
        recorded = json.loads((dist / STAMP).read_text())["sources_sha256"]
    except (FileNotFoundError, KeyError, TypeError, json.JSONDecodeError):
        raise _refuse("the UI build carries no stamp of what it was built from") from None
    current = source_digest(ui_root)
    if recorded != current:
        raise _refuse(
            "the UI build is stale: its sources changed since", built=recorded, now=current
        )
    files: dict[str, tuple[bytes, str]] = {}
    assets_dir = dist / "assets"
    if assets_dir.is_symlink():
        raise _refuse("the build's assets directory is a link")
    if assets_dir.is_dir():
        for entry in sorted(os.scandir(assets_dir), key=lambda e: e.name):
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                raise _refuse(
                    "the build holds a link or a directory among its assets", name=entry.name
                )
            media = MEDIA_TYPES.get(Path(entry.name).suffix)
            if media is None:
                raise _refuse(
                    "the build holds a file of a type the server does not send", name=entry.name
                )
            files[entry.name] = (Path(entry.path).read_bytes(), media)
    return Assets(index=index_path.read_bytes(), files=files)


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m physgate.ui.assets stamp <ui-dir>``: the build script's last step."""
    parser = argparse.ArgumentParser(prog="python -m physgate.ui.assets")
    parser.add_argument("action", choices=["stamp"])
    parser.add_argument("ui_root", type=Path)
    args = parser.parse_args(argv)
    try:
        print(write_stamp(args.ui_root.resolve()))
    except StartupRefusedError as exc:
        print(json.dumps({"error": str(exc), **exc.context}, sort_keys=True), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
