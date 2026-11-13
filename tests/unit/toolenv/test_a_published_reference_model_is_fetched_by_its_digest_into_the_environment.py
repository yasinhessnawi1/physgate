"""A published model a design is measured against is an input of the environment, by digest.

A role measures a dimension the maker does not print (where the motors sit, how far apart two
gears turn) from the maker's own published CAD model. That file is pinned in ``pins.json`` by
file name, address and sha256 before it is fetched; provisioning fetches it once, refuses bytes
that differ from the pin, keeps only matching bytes in its cache, and copies the file into the
environment's ``reference/`` folder, where it is read-only and in the manifest like every other
file. A refusal names the file and both digests, the pinned one and the one found, so whoever
reads it can tell a changed file from a broken download. The script's judgements are tested
here on their own; a real fetch is the integration test's.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

TOOLENV = Path(__file__).resolve().parents[3] / "toolenv"
BALBOA = "balboa-balancing-robot-kit.step"
BALBOA_URL = f"https://www.pololu.com/file/0J1309/{BALBOA}"
BALBOA_SHA256 = "9208f9d329b3955eb317685ea1291f30b9ce10dbd82388ea1d5f1bad9b6726e1"


def _provision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("toolenv_provision", TOOLENV / "provision.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _raised(call: Callable[[], object]) -> BaseException | None:
    """What ``call`` raised, of any kind, so that a wrong error fails an assertion too."""
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - every kind is wanted here
        return exc
    return None


def _model(body: bytes = b"a model as published", **changed: object) -> dict[str, object]:
    model: dict[str, object] = {
        "file": "part.step",
        "url": "https://example.org/files/part.step",
        "sha256": hashlib.sha256(body).hexdigest(),
        "describes": "a stand-in model",
    }
    return model | changed


def _models(provision: ModuleType, pins: dict[str, object]) -> object:
    read = getattr(provision, "reference_models", None)
    assert read is not None, "provisioning reads no reference models from the pins"
    return read(pins)


def _fetch_into(provision: ModuleType) -> Callable[..., object]:
    fetched = getattr(provision, "_reference_models", None)
    assert fetched is not None, "provisioning fetches no reference models"
    assert callable(fetched)
    return fetched  # type: ignore[no-any-return]


# ---- the pin ----------------------------------------------------------------------------------


def test_the_balboa_model_is_pinned_by_file_address_and_digest() -> None:
    pins = json.loads((TOOLENV / "pins.json").read_text(encoding="utf-8"))
    models = pins.get("reference_models")
    assert isinstance(models, list), sorted(pins)
    balboa = [m for m in models if isinstance(m, dict) and m.get("file") == BALBOA]
    assert len(balboa) == 1, models
    assert balboa[0]["url"] == BALBOA_URL
    assert balboa[0]["sha256"] == BALBOA_SHA256
    assert balboa[0]["describes"].strip()


def test_the_pins_file_is_read_with_its_reference_models() -> None:
    provision = _provision()
    found = _models(provision, provision.load_pins())
    assert isinstance(found, list)
    assert [m["file"] for m in found] == [BALBOA]
    assert found[0]["sha256"] == BALBOA_SHA256


def test_pins_with_no_reference_models_fetch_none() -> None:
    assert _models(_provision(), {"python": "3.12.9"}) == []


@pytest.mark.parametrize("missing", ["file", "url", "sha256", "describes"])
def test_a_model_without_one_of_its_fields_is_refused(missing: str) -> None:
    provision = _provision()
    model = _model()
    del model[missing]
    found = _raised(lambda: _models(provision, {"reference_models": [model]}))
    assert isinstance(found, provision.ProvisionError), repr(found)


@pytest.mark.parametrize(
    "changed",
    [
        {"file": "../part.step", "url": "https://example.org/files/../part.step"},
        {"file": "sub/part.step", "url": "https://example.org/files/sub/part.step"},
        {"file": ".step", "url": "https://example.org/files/.step"},
        {"url": "http://example.org/files/part.step"},
        {"url": "https://example.org/files/other.step"},
        {"url": "file:///etc/part.step"},
        {"sha256": "0" * 63},
        {"sha256": "A" * 64},
        {"describes": "  "},
    ],
)
def test_a_model_pin_that_is_not_a_plain_name_an_https_address_and_a_digest_is_refused(
    changed: dict[str, object],
) -> None:
    provision = _provision()
    found = _raised(lambda: _models(provision, {"reference_models": [_model() | changed]}))
    assert isinstance(found, provision.ProvisionError), repr(found)


@pytest.mark.parametrize("pinned", [_model(), "part.step", ["part.step"], [[_model()]]])
def test_reference_models_that_are_not_a_list_of_pins_are_refused(pinned: object) -> None:
    provision = _provision()
    found = _raised(lambda: _models(provision, {"reference_models": pinned}))
    assert isinstance(found, provision.ProvisionError), repr(found)


def test_a_model_pin_with_a_field_of_its_own_is_refused() -> None:
    provision = _provision()
    model = _model() | {"licence": "unstated"}
    found = _raised(lambda: _models(provision, {"reference_models": [model]}))
    assert isinstance(found, provision.ProvisionError), repr(found)


def test_two_pins_of_one_file_name_are_refused() -> None:
    provision = _provision()
    two = [_model(), _model(b"other bytes")]
    found = _raised(lambda: _models(provision, {"reference_models": two}))
    assert isinstance(found, provision.ProvisionError), repr(found)


# ---- the fetch --------------------------------------------------------------------------------


def _fetcher(body: bytes, asked: list[str]) -> Callable[[str, Path, Path], Path]:
    def fetch(url: str, into: Path, work: Path) -> Path:
        asked.append(url)
        into.mkdir(parents=True)
        target = into / url.rsplit("/", 1)[-1]
        target.write_bytes(body)
        return target

    return fetch


def test_a_model_that_matches_its_pin_is_kept_and_placed_in_the_reference_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provision = _provision()
    body = b"a model as published"
    model = _model(body)
    asked: list[str] = []
    monkeypatch.setattr(provision, "fetch", _fetcher(body, asked))
    dest = tmp_path / "env"
    dest.mkdir()
    cache = tmp_path / "cache"
    found = _fetch_into(provision)(dest, {"reference_models": [model]}, cache, tmp_path)
    assert asked == [model["url"]]
    assert isinstance(found, list) and [m["sha256"] for m in found] == [model["sha256"]]
    placed = dest / "reference" / "part.step"
    assert placed.read_bytes() == body and not placed.is_symlink()
    assert placed.stat().st_nlink == 1
    assert (cache / "reference" / "part.step").read_bytes() == body
    assert sorted(p.name for p in dest.iterdir()) == ["reference"]


def test_a_model_already_kept_is_not_fetched_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provision = _provision()
    body = b"a model as published"
    kept = tmp_path / "cache" / "reference" / "part.step"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(body)
    asked: list[str] = []
    monkeypatch.setattr(provision, "fetch", _fetcher(body, asked))
    dest = tmp_path / "env"
    dest.mkdir()
    _fetch_into(provision)(dest, {"reference_models": [_model(body)]}, tmp_path / "cache", tmp_path)
    assert asked == []
    assert (dest / "reference" / "part.step").read_bytes() == body


def test_a_fetched_model_whose_bytes_differ_names_the_file_and_both_digests_and_is_not_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provision = _provision()
    model = _model(b"a model as published")
    served = b"what a changed page serves"
    monkeypatch.setattr(provision, "fetch", _fetcher(served, []))
    dest = tmp_path / "env"
    dest.mkdir()
    cache = tmp_path / "cache"
    found = _raised(
        lambda: _fetch_into(provision)(dest, {"reference_models": [model]}, cache, tmp_path)
    )
    assert isinstance(found, provision.ProvisionError), repr(found)
    message = str(found)
    assert "part.step" in message, message
    assert str(model["sha256"]) in message, message
    assert hashlib.sha256(served).hexdigest() in message, message
    assert not (cache / "reference" / "part.step").exists()
    assert not (dest / "reference" / "part.step").exists()


def test_a_kept_model_whose_bytes_changed_names_the_file_and_both_digests_and_is_not_placed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provision = _provision()
    model = _model(b"a model as published")
    changed = b"other bytes under the pinned name"
    kept = tmp_path / "cache" / "reference" / "part.step"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(changed)
    monkeypatch.setattr(provision, "fetch", _fetcher(changed, []))
    dest = tmp_path / "env"
    dest.mkdir()
    found = _raised(
        lambda: _fetch_into(provision)(
            dest, {"reference_models": [model]}, tmp_path / "cache", tmp_path
        )
    )
    assert isinstance(found, provision.ProvisionError), repr(found)
    message = str(found)
    assert "part.step" in message and str(model["sha256"]) in message, message
    assert hashlib.sha256(changed).hexdigest() in message, message
    assert not (dest / "reference" / "part.step").exists()


@pytest.mark.parametrize("failure", ["not served", "timed out"])
def test_a_model_that_cannot_be_fetched_is_named_with_its_address_and_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    provision = _provision()
    model = _model()
    asked: list[list[str]] = []

    def run(argv: list[str], env: dict[str, str], **more: object) -> str:
        asked.append(list(argv))
        if failure == "timed out":
            raise subprocess.TimeoutExpired(argv, provision.STEP_TIMEOUT_S)
        raise provision.ProvisionError("curl -fsSL --proto failed:\ncurl: (22) error: 404")

    monkeypatch.setattr(provision, "run", run)
    dest = tmp_path / "env"
    dest.mkdir()
    cache = tmp_path / "cache"
    found = _raised(
        lambda: _fetch_into(provision)(dest, {"reference_models": [model]}, cache, tmp_path)
    )
    assert len(asked) == 1 and asked[0][-1] == model["url"], asked
    assert isinstance(found, provision.ProvisionError), repr(found)
    message = str(found)
    for part in ("part.step", str(model["sha256"]), str(model["url"])):
        assert part in message, message
    assert not (cache / "reference" / "part.step").exists()


def test_pins_with_no_reference_models_make_no_folder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provision = _provision()
    asked: list[str] = []
    monkeypatch.setattr(provision, "fetch", _fetcher(b"", asked))
    dest = tmp_path / "env"
    dest.mkdir()
    assert _fetch_into(provision)(dest, {}, tmp_path / "cache", tmp_path) == []
    assert asked == [] and list(dest.iterdir()) == []


def test_the_build_fetches_the_models_and_records_them() -> None:
    # The build step is long and fetches the world; what it does with the models is read here
    # from its own text: it calls the fetch and records what came back.
    source = (TOOLENV / "provision.py").read_text(encoding="utf-8")
    build = source[source.index("def _build(") :]
    build = build[: build.index("\ndef ")]
    assert "_reference_models(dest, pins, cache, work)" in build
    assert '"reference_models": reference' in build
