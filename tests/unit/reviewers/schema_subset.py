"""A validator for the part of JSON Schema the verdict contract uses, for the unit tests.

The binary is what enforces the schema in a review; its validator is measured against
this one on the scripted endpoint (the integration tests replay the same cases). This
one lets the unit tests and the mutations exercise every clause quickly and without a
binary. It knows: type, enum, const, required, properties, additionalProperties (false),
items, minItems, maxItems, minLength, contains, allOf, anyOf, not, if and then.
"""

from __future__ import annotations

from typing import Any

_TYPES: dict[str, Any] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _is(value: object, kind: str) -> bool:
    if kind == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, _TYPES[kind])


def errors(value: object, schema: dict[str, Any], where: str = "") -> list[str]:  # noqa: C901, PLR0912
    """Every way ``value`` breaks ``schema``, each with its path; empty if it holds."""
    found: list[str] = []
    kinds = schema.get("type")
    if kinds is not None:
        wanted = kinds if isinstance(kinds, list) else [kinds]
        if not any(_is(value, k) for k in wanted):
            return [f"{where}: not {kinds}"]
    if "enum" in schema and value not in schema["enum"]:
        found.append(f"{where}: {value!r} not in enum")
    if "const" in schema and value != schema["const"]:
        found.append(f"{where}: {value!r} is not {schema['const']!r}")
    if isinstance(value, str) and len(value) < schema.get("minLength", 0):
        found.append(f"{where}: shorter than {schema['minLength']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                found.append(f"{where}: must have required property '{key}'")
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                found += errors(item, properties[key], f"{where}/{key}")
            elif schema.get("additionalProperties") is False:
                found.append(f"{where}: must NOT have additional properties ('{key}')")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            found.append(f"{where}: fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            found.append(f"{where}: more than {schema['maxItems']} items")
        if "items" in schema:
            for index, item in enumerate(value):
                found += errors(item, schema["items"], f"{where}/{index}")
        if "contains" in schema and not any(not errors(v, schema["contains"]) for v in value):
            found.append(f"{where}: must contain a matching item")
    for part in schema.get("allOf", []):
        found += errors(value, part, where)
    if "anyOf" in schema and all(errors(value, part, where) for part in schema["anyOf"]):
        found.append(f"{where}: matches none of anyOf")
    if "not" in schema and not errors(value, schema["not"], where):
        found.append(f"{where}: must not match")
    if "if" in schema and not errors(value, schema["if"], where) and "then" in schema:
        found += errors(value, schema["then"], where)
    return found
