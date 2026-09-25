"""Everything the package exports is importable and is what it claims to be.

A re-export that names a symbol which no longer exists is the kind of thing that
only fails when something else needs it, which is usually much later.
"""

from __future__ import annotations

import physgate.state as state


def test_every_exported_name_exists() -> None:
    assert state.__all__, "the package exports nothing"
    missing = [name for name in state.__all__ if not hasattr(state, name)]
    assert missing == []


def test_the_export_list_has_no_duplicates() -> None:
    assert len(state.__all__) == len(set(state.__all__))


def test_the_readme_is_beside_the_package() -> None:
    """The package docstring points at it, so it has to be there."""
    from pathlib import Path

    readme = Path(state.__file__).resolve().parent / "README.md"
    assert readme.is_file()
    assert readme.read_text().strip(), "the readme is empty"


def test_the_readme_says_what_the_package_does_not_own() -> None:
    from pathlib import Path

    readme = (Path(state.__file__).resolve().parent / "README.md").read_text()
    assert "does not own" in readme
    assert "view as of open" in readme


#: Public in their own module and deliberately not re-exported, each with the
#: reason. The rule this test enforces is that a public symbol has a caller
#: outside its own module; these have callers inside the package and none
#: outside yet, and naming them here is how that is declared rather than
#: discovered.
DELIBERATELY_UNEXPORTED = {
    "store.payload_digest": (
        "the identity of a payload, used by the rollback rule on both paths. "
        "Nothing outside the package calls it yet; whichever of the orchestrator "
        "or the hook layer needs it will export it together with its caller."
    ),
}


def test_every_public_symbol_in_the_package_is_exported() -> None:
    """The no-dark-code rule, as a test rather than as a paragraph in a report.

    A public class or function that the package does not export has no caller
    outside its own module and no obvious way to acquire one. Writing this test
    found two: the store class itself, and the divergence check, neither of which
    was reachable through the package.
    """
    import importlib
    import inspect
    import pkgutil
    from pathlib import Path

    missing: list[str] = []
    package_dir = Path(state.__file__).resolve().parent
    for info in pkgutil.iter_modules([str(package_dir)]):
        module = importlib.import_module(f"physgate.state.{info.name}")
        for name, obj in vars(module).items():
            if name.startswith("_") or name in state.__all__:
                continue
            if not (inspect.isclass(obj) or inspect.isfunction(obj)):
                continue
            if getattr(obj, "__module__", "") != module.__name__:
                continue  # imported from elsewhere, not defined here
            qualified = f"{info.name}.{name}"
            if qualified in DELIBERATELY_UNEXPORTED:
                continue
            missing.append(qualified)

    assert missing == [], f"public but not exported: {missing}"


def test_every_declared_exception_to_the_export_rule_still_exists() -> None:
    """A declared exception for a symbol that has gone is a stale excuse."""
    import importlib

    for qualified, reason in DELIBERATELY_UNEXPORTED.items():
        module_name, _, symbol = qualified.partition(".")
        module = importlib.import_module(f"physgate.state.{module_name}")
        assert hasattr(module, symbol), qualified
        assert reason.strip(), qualified


def test_nothing_declared_unexported_is_also_exported() -> None:
    """Declaring an exception for something that is exported anyway is noise."""
    for qualified in DELIBERATELY_UNEXPORTED:
        assert qualified.split(".")[-1] not in state.__all__, qualified
