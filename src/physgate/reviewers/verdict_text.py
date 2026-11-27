"""A verdict refused only for its form, read as one when it is the verdict the schema holds.

The verdict is submitted as ``{"review": {...}}``. Real reviewers have sent ``review`` as a text
instead, every time in the same form: the verdict's own JSON object followed by one closing brace
too many (the wrapper's), which the binary refuses with "/review: must be object" and nothing
else. Told so in the prompt, in the contract and again after each refusal, some reviewers sent the
same text until the binary's cap on refused structured answers ended the session, and a verdict
that was right in substance was lost to its form: no verdict at all.

So when a session ends with no structured verdict, the harness reads the session's last try of the
verdict tool, and only that one, and only where the binary refused it for that reason alone: so it
was a try the reading hook let through, and the reviewer's latest word. Its text is parsed in the
one form measured (one JSON object, then at most that one closing brace; a duplicated key or a
number JSON does not have is refused), and the object is held to the very schema the session was
given, every clause of it, the indicators' evidence constants included: they are what make a
reviewer judge each marker the scan found. A text that does not parse or does not hold to the
schema is a refused verdict, the reason in words. One that holds goes on to every check a
structured verdict goes through, the reading and the harness's own check of the verdict included.
Nothing is accepted here that the binary's schema check would refuse.

:func:`schema_errors` knows the keywords the verdict contract uses (``contract.verdict_schema``)
and refuses a schema that uses any other: it fails closed, never open.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any

from physgate.lines import split_lines
from physgate.reviewers.contract import WRAPPER

#: The verdict tool, as the binary names it.
VERDICT_TOOL = "StructuredOutput"
#: The binary's whole refusal of a ``review`` sent as a text (measured on both pins): a try the
#: binary refused for anything else besides, or for anything else at all, is never read here.
FORM_REFUSAL = f"Output does not match required schema: /{WRAPPER}: must be object"
#: The keywords :func:`schema_errors` knows. A schema using any other is refused, never passed.
KNOWN_KEYWORDS = frozenset(
    {
        "type",
        "enum",
        "const",
        "required",
        "properties",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "minLength",
        "pattern",
        "minimum",
        "contains",
        "allOf",
        "anyOf",
        "not",
        "if",
        "then",
        "else",
    }
)
#: How many of a refused text's schema errors its reason names.
NAMED_ERRORS = 5
#: The longest text read, in characters: six times the longest verdict text measured (about
#: 42,000). A longer one is refused unread.
MAX_TEXT_CHARACTERS = 262_144
#: The deepest nesting of arrays and objects a verdict text may hold. The contract's own is six.
MAX_DEPTH = 32
#: The most characters a number in a verdict text may have; the contract's numbers are values
#: with units and counts, never this long. A longer one is refused, never converted.
MAX_NUMBER_CHARACTERS = 40


@dataclass(frozen=True)
class TextVerdict:
    """The session's last try, a text the binary refused for its form: the verdict, or why not."""

    #: ``{"review": {...}}``, the parsed object held to the schema; ``None`` when it is refused.
    answer: dict[str, Any] | None
    #: Why the text is no verdict, in words; ``None`` when it is one.
    refused: str | None


def last_text_verdict(stream: str, schema: dict[str, Any]) -> TextVerdict | None:
    """What the stream's last try of the verdict tool amounts to, if it was a text refused for form.

    ``None`` when the stream has no try, when its last tool call is not that try (the reviewer went
    on after it), when the try was not answered, or was refused for anything but the form alone
    (the reading hook's refusal, a schema refusal of an object), or was not a text: then nothing
    here applies and the session's end is read as it always was. Reading the text never raises:
    whatever goes wrong in it is a refused verdict, in words.
    """
    last = _last_try(stream)
    if last is None:
        return None
    given, answer = last
    if answer != FORM_REFUSAL or not isinstance(given, dict) or set(given) != {WRAPPER}:
        return None
    text = given[WRAPPER]
    if not isinstance(text, str):
        return None
    try:
        return _held(text, schema)
    except (ValueError, OverflowError, RecursionError, TypeError) as exc:
        return TextVerdict(
            answer=None,
            refused=f"the verdict was sent as text, and it could not be read: {type(exc).__name__}",
        )


def _held(text: str, schema: dict[str, Any]) -> TextVerdict:
    """``text`` parsed and held to ``schema``: the verdict, or why it is none."""
    parsed = parse_verdict_text(text)
    if isinstance(parsed, str):
        return TextVerdict(answer=None, refused=f"the verdict was sent as text, and {parsed}")
    answer_object = {WRAPPER: parsed}
    # The whole schema first: a clause this check cannot read is never passed, wherever it sits.
    errors = unreadable(schema) or schema_errors(answer_object, schema)
    if errors:
        named = "; ".join(errors[:NAMED_ERRORS])
        more = f" (and {len(errors) - NAMED_ERRORS} more)" if len(errors) > NAMED_ERRORS else ""
        return TextVerdict(
            answer=None,
            refused="the verdict was sent as text; read as an object, it breaks the verdict's "
            f"schema: {named}{more}",
        )
    return TextVerdict(answer=answer_object, refused=None)


def _last_try(stream: str) -> tuple[object, str] | None:
    """The last tool call, if it is a try of the verdict tool: its input, and its answer."""
    last_id: str | None = None
    last_name: object = None
    given: object = None
    answers: dict[str, str] = {}
    for line in split_lines(stream):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        content = (event.get("message") or {}).get("content")
        blocks = [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []
        if event.get("type") == "assistant":
            for block in blocks:
                if block.get("type") == "tool_use":
                    last_name = block.get("name")
                    last_id, given = block.get("id"), block.get("input")
        elif event.get("type") == "user":
            for block in blocks:
                if block.get("type") == "tool_result" and isinstance(block.get("tool_use_id"), str):
                    answers[block["tool_use_id"]] = _result_text(block.get("content"))
    if last_name != VERDICT_TOOL or not isinstance(last_id, str) or last_id not in answers:
        return None
    return given, answers[last_id].strip()


def _result_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)
        )
    return ""


class _NotJsonError(ValueError):
    """A part of the text JSON does not allow, though Python's reader would."""


def _no_constant(name: str) -> object:
    msg = f"it holds {name}, which is not a JSON number"
    raise _NotJsonError(msg)


def _no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, Any] = {}
    for key, value in pairs:
        if key in seen:
            msg = f"it gives the key {key!r} twice"
            raise _NotJsonError(msg)
        seen[key] = value
    return seen


def _integer(literal: str) -> int:
    if len(literal) > MAX_NUMBER_CHARACTERS:
        msg = f"it holds a number of more than {MAX_NUMBER_CHARACTERS} characters"
        raise _NotJsonError(msg)
    return int(literal)


def _real(literal: str) -> float:
    if len(literal) > MAX_NUMBER_CHARACTERS:
        msg = f"it holds a number of more than {MAX_NUMBER_CHARACTERS} characters"
        raise _NotJsonError(msg)
    value = float(literal)
    if not math.isfinite(value):
        msg = f"it holds {literal}, a number too large to hold"
        raise _NotJsonError(msg)
    return value


def _depth(value: object) -> int:
    """How deep ``value``'s arrays and objects nest, counted without recursion.

    An empty array or object is a level too: ``[[]]`` nests two deep, as ``[[1]]`` does.
    """
    deepest, stack = 0, [(value, 1)]
    while stack:
        item, level = stack.pop()
        if isinstance(item, dict | list):
            deepest = max(deepest, level)
            children = item.values() if isinstance(item, dict) else item
            stack.extend((child, level + 1) for child in children)
    return deepest


def parse_verdict_text(text: str) -> dict[str, Any] | str:
    """The verdict object ``text`` holds, or why it holds none, in words.

    The one form measured: a JSON object, then nothing but at most one closing brace (the
    wrapper's), with white space around. Nothing else is tolerated: no second value, no text
    around it, no duplicated key, no ``NaN`` or ``Infinity``, no number too long or too large to
    hold, no nesting deeper than :data:`MAX_DEPTH`, and no text longer than
    :data:`MAX_TEXT_CHARACTERS`.
    """
    if len(text) > MAX_TEXT_CHARACTERS:
        return f"that text is longer than the {MAX_TEXT_CHARACTERS} characters read"
    # JSON's own white space alone: Python's strip takes a no-break space, a line separator or a
    # vertical tab too, which no JSON reader would.
    stripped = text.strip(JSON_WHITE_SPACE)
    decoder = json.JSONDecoder(
        parse_constant=_no_constant,
        parse_int=_integer,
        parse_float=_real,
        object_pairs_hook=_no_duplicates,
    )
    try:
        value, end = decoder.raw_decode(stripped)
    except _NotJsonError as exc:
        return f"that text is not one JSON object: {exc}"
    except json.JSONDecodeError as exc:
        return f"that text is not one JSON object: {exc.msg} at character {exc.pos}"
    except RecursionError:
        return "that text is not one JSON object: it nests too deep to read"
    if not isinstance(value, dict):
        return "that text holds no JSON object"
    rest = stripped[end:].strip(JSON_WHITE_SPACE)
    if rest not in ("", "}"):
        return "that text holds more than one JSON object, or more after it"
    if _depth(value) > MAX_DEPTH:
        return f"that text nests deeper than {MAX_DEPTH} levels"
    return value


#: JSON's insignificant white space: space, tab, line feed, carriage return (RFC 8259).
JSON_WHITE_SPACE = " \t\n\r"
#: What ECMAScript's ``\s`` matches (its WhiteSpace and LineTerminator), which a schema's
#: ``pattern`` means: the client checks a verdict with that language's regular expressions. Python's
#: own ``\s`` leaves out U+FEFF and takes U+001C to U+001F and U+0085, which ECMAScript does not.
ECMASCRIPT_SPACE = "\t\n\x0b\x0c\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


def ecmascript_pattern(pattern: str) -> str:
    r"""``pattern`` with ``\s`` and ``\S`` spelt as ECMAScript reads them, for Python's ``re``.

    Inside a character class ``\s`` becomes its characters (``\S`` there is refused: a class of
    every character but those has no spelling inside another class); outside one, ``[...]`` and
    ``[^...]``. Every other escape is kept as written, and the pattern is compiled ASCII, as
    ECMAScript reads ``\d``, ``\w`` and ``\b`` without its ``u`` flag.

    Raises:
        ValueError: ``\S`` stands inside a character class.
    """
    out: list[str] = []
    in_class = False
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\" and index + 1 < len(pattern):
            escaped = pattern[index + 1]
            if escaped == "s":
                out.append(ECMASCRIPT_SPACE if in_class else f"[{ECMASCRIPT_SPACE}]")
            elif escaped == "S":
                if in_class:
                    msg = "the pattern holds \\S inside a character class"
                    raise ValueError(msg)
                out.append(f"[^{ECMASCRIPT_SPACE}]")
            else:
                out.append(char + escaped)
            index += 2
            continue
        if char == "[" and not in_class:
            in_class = True
        elif char == "]" and in_class:
            in_class = False
        out.append(char)
        index += 1
    return "".join(out)


def _pattern_errors(value: str, pattern: object, at: str) -> list[str]:
    """How ``value`` breaks ``pattern`` as ECMAScript reads it; a pattern not read is an error."""
    if not isinstance(pattern, str):
        return [f"{at}: the schema's pattern is not a string, a form this check does not know"]
    try:
        compiled = re.compile(ecmascript_pattern(pattern), re.ASCII)
    except (re.error, ValueError):
        return [f"{at}: the schema's pattern is in a form this check does not know"]
    if compiled.search(value) is None:
        return [f'{at}: must match pattern "{pattern}"']
    return []


def _is(value: object, kind: str) -> bool:
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "boolean":
        return isinstance(value, bool)
    if kind == "null":
        return value is None
    number = isinstance(value, int | float) and not isinstance(value, bool)
    if kind == "number":
        return number and math.isfinite(value)  # type: ignore[arg-type]
    if kind == "integer":
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            or (isinstance(value, float) and value.is_integer())
        )
    return False


def same(a: object, b: object) -> bool:
    """Whether two JSON values are equal as JSON Schema compares them; a boolean is no number."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


_ONE_SUBSCHEMA = ("items", "contains", "not", "if", "then", "else")
_SUBSCHEMA_LISTS = ("allOf", "anyOf")


def unreadable(schema: object, where: str = "") -> list[str]:
    """Each place ``schema`` uses a keyword, or a form, :func:`schema_errors` does not know."""
    at = where or "/"
    if not isinstance(schema, dict):
        return [f"{at}: the schema here is not an object, a form this check does not know"]
    found = [
        f"{at}: the schema uses {key}, which this check does not know"
        for key in sorted(set(schema) - KNOWN_KEYWORDS)
    ]
    if "additionalProperties" in schema and schema["additionalProperties"] is not False:
        found.append(
            f"{at}: the schema's additionalProperties is in a form this check does not know"
        )
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        found.append(f"{at}: the schema's properties are not an object")
        properties = {}
    for key, part in properties.items():
        found += unreadable(part, f"{where}/properties/{key}")
    for key in _ONE_SUBSCHEMA:
        if key in schema:
            found += unreadable(schema[key], f"{where}/{key}")
    for key in _SUBSCHEMA_LISTS:
        parts = schema.get(key, [])
        if not isinstance(parts, list):
            found.append(f"{at}: the schema's {key} is not a list")
            continue
        for index, part in enumerate(parts):
            found += unreadable(part, f"{where}/{key}/{index}")
    return found


def schema_errors(value: object, schema: object, where: str = "") -> list[str]:  # noqa: C901, PLR0912
    """Every way ``value`` breaks ``schema``, each with its place; empty if it holds to it.

    Knows :data:`KNOWN_KEYWORDS` and ``additionalProperties`` only as ``false``; a schema with any
    other keyword, or a keyword in a form it does not know, is an error itself, so a schema this
    check cannot read never passes a value.
    """
    at = where or "/"
    if not isinstance(schema, dict):
        return [f"{at}: the schema here is not an object, a form this check does not know"]
    unknown = sorted(set(schema) - KNOWN_KEYWORDS)
    if unknown:
        return [f"{at}: the schema uses {', '.join(unknown)}, which this check does not know"]
    if "additionalProperties" in schema and schema["additionalProperties"] is not False:
        return [f"{at}: the schema's additionalProperties is in a form this check does not know"]
    kinds = schema.get("type")
    if kinds is not None:
        wanted = kinds if isinstance(kinds, list) else [kinds]
        if not any(_is(value, k) for k in wanted):
            return [f"{at}: must be {' or '.join(str(k) for k in wanted)}"]
    found: list[str] = []
    if "enum" in schema and not any(same(value, v) for v in schema["enum"]):
        found.append(f"{at}: must be equal to one of the allowed values")
    if "const" in schema and not same(value, schema["const"]):
        found.append(f"{at}: must be equal to constant: {json.dumps(schema['const'])}")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            found.append(f"{at}: must NOT have fewer than {schema['minLength']} characters")
        if "pattern" in schema:
            found += _pattern_errors(value, schema["pattern"], at)
    if _is(value, "number") and "minimum" in schema and value < schema["minimum"]:
        found.append(f"{at}: must be >= {schema['minimum']}")
    if isinstance(value, dict):
        found += [
            f"{at}: must have required property '{key}'"
            for key in schema.get("required", [])
            if key not in value
        ]
        properties = schema.get("properties", {})
        for key, item in value.items():
            if key in properties:
                found += schema_errors(item, properties[key], f"{where}/{key}")
            elif schema.get("additionalProperties") is False:
                found.append(f"{at}: must NOT have additional properties ('{key}')")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            found.append(f"{at}: must NOT have fewer than {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            found.append(f"{at}: must NOT have more than {schema['maxItems']} items")
        if "items" in schema:
            for index, item in enumerate(value):
                found += schema_errors(item, schema["items"], f"{where}/{index}")
        if "contains" in schema and all(schema_errors(v, schema["contains"]) for v in value):
            found.append(f"{at}: must contain at least 1 valid item(s)")
    for part in schema.get("allOf", []):
        found += schema_errors(value, part, where)
    if "anyOf" in schema and all(schema_errors(value, part, where) for part in schema["anyOf"]):
        found.append(f"{at}: must match a schema in anyOf")
    if "not" in schema and not schema_errors(value, schema["not"], where):
        found.append(f"{at}: must NOT be valid")
    if "if" in schema:
        branch = "then" if not schema_errors(value, schema["if"], where) else "else"
        if branch in schema:
            found += schema_errors(value, schema[branch], where)
    return found
