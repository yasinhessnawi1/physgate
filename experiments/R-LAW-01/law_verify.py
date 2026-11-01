"""R-LAW-01, CRITERIA.md §2.5 and §5.5: every coder's and adjudicator's form, verified by script.

Usage (from the repository root, with the project environment):

    uv run python -I experiments/R-LAW-01/law_verify.py valid <kind> <packet.md> <key> <out.json>
    uv run python -I experiments/R-LAW-01/law_verify.py codes <work> <step> <who> <packets> <out>
    uv run python -I experiments/R-LAW-01/law_verify.py ledger <ledger> <step> <packet> <try>
        <model asked> <out.json> <exit> <valid 0|1> <stand-in 0|1> <cause, or "">
    uv run python -I experiments/R-LAW-01/law_verify.py spent <ledger>

(``<kind>`` is coder, adjudicator or reality; ``<out>`` the step's sessions directory.)

- ``valid``: the session driver's validity test for one try (exit 0 valid, 1 not, 3 refused):
  refused outright if the packet does not carry the full parts sheet at its digest (§2.5); valid
  if every finding id of the packet has a form with every field its code requires.
- ``codes``: for every packet of one step (``slice-r1``, ``slice-r2``, ``measured``, ``audit``)
  and one coder (``c1``, ``c2``, ``adj``, ``audit``): refuses any session whose packet lacks the
  sheet; per line, takes the first try's form if valid, else the retry's, else none; applies
  §5.5 (the relation in a restricted syntax tree, the inputs rebuilt from the node data with pint,
  values, units, dimension, comparator class, pairing, the miss against the tolerance, the
  fallbacks) and appends the result to ``<work>/codes.jsonl``. Prints counts of sessions, forms
  and failure kinds, never a code distribution.
- ``ledger``: the session driver's ledger line for one call, counted from its output here (tokens
  of every kind :data:`TOKEN_KINDS` names, and the models its ``modelUsage`` names) and appended
  in one write, so that drivers appending at once never tear each other's lines. An output that
  reports no usage is charged from the ledger as it stands (:func:`charged`) and marked
  ``tokens_estimated``.
- ``spent``: the ledger's token total (exit 0), or a refusal (exit 1) if any line is not a whole
  row whose token count is a non-negative integer; the 60 M guard reads nothing else (§12).
"""

from __future__ import annotations

import ast
import datetime
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import law_extract as X  # noqa: E402

CODES = ("G", "L", "L-if-data", "D", "N")
FALLBACKS = ("L-if-data", "D", "N")
D_KINDS = ("simulation", "table", "source", "record", "numeric")
N_KINDS = ("judgement", "wording", "process", "traceability")
TOLERANCES = {"rounding": ("==",), "inequality": ("<=", ">=", "<", ">"), "relative": ("==",)}
RELATIVE_MAX = 25.0
ROUNDING = 0.005
LIMIT_TOKENS = {"max", "min", "rated", "limit", "capacity", "peak", "rating"}
CONSTANTS = ("pi", "g_n")
SHEET_MARK = "\n## The parts sheet\n\n"
UNIT_ALIASES = {"°C": "degC", "℃": "degC", "°F": "degF", "%": "percent"}


class Invalid(Exception):
    """A form or session output that does not have what its code requires."""


# ---------------------------------------------------------------- the parts sheet (§2.5)


def sheet_ok(packet_text: str, digest: str = X.PARTS_SHEET_SHA256) -> bool:
    """Whether the packet carries the full parts sheet, verbatim, at its digest, as its end."""
    if packet_text.count(SHEET_MARK) != 1:
        return False
    return X.sha256_bytes(packet_text.split(SHEET_MARK, 1)[1].encode()) == digest


# ---------------------------------------------------------------- reading a session


def structured(path: Path) -> dict[str, Any] | None:
    """The result message's structured output, or None."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    msgs = data if isinstance(data, list) else [data]
    results = [m for m in msgs if isinstance(m, dict) and m.get("type") == "result"]
    if not results:
        return None
    so = results[-1].get("structured_output")
    return so if isinstance(so, dict) else None


def result_message(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001 - an output that cannot be read still gets its ledger line
        return {}
    msgs = data if isinstance(data, list) else [data]
    results = [m for m in msgs if isinstance(m, dict) and m.get("type") == "result"]
    return results[-1] if results else {}


#: The token kinds the ledger counts, of every try and every failed call (README reading 6).
TOKEN_KINDS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def tokens_of(path: Path) -> int:
    u = result_message(path).get("usage") or {}
    return sum(int(u.get(k) or 0) for k in TOKEN_KINDS)


def model_of(path: Path) -> list[str]:
    return sorted((result_message(path).get("modelUsage") or {}).keys())


# ---------------------------------------------------------------- the ledger (§12)


class LedgerUnreadable(Exception):
    """A ledger whose total cannot be read: a torn line, or a row without its token count."""


#: CRITERIA §12's tokens per session: the charge's unit while no completed try has reported usage.
SESSION_TOKENS = 50_000
#: Failed calls that are refusals: charged nothing when no model turn completed before them.
REFUSED_BEFORE_WORK = ("usage_limit", "rate_limit", "credential_refused")


def reports_usage(path: Path) -> bool:
    """Whether the output has a result that names the models it used (``modelUsage``)."""
    return bool(result_message(path).get("modelUsage"))


def turns_of(path: Path) -> int:
    """The result's ``num_turns``; 1 with no result, or none that is a whole number of turns."""
    n = result_message(path).get("num_turns")
    return n if type(n) is int and n > 0 else 1


def charge_unit(ledger: Path) -> int:
    """The largest count a completed try reported, among the ledger's rows now (an estimate's
    charge is no report, and a failed call is no try); §12's 50,000 while there is none."""
    try:
        rows = ledger_rows(ledger)
    except LedgerUnreadable:
        return SESSION_TOKENS  # the guard stops on this ledger whatever is charged here
    done = [
        r["tokens"] for r in rows if not r.get("infrastructure") and not r.get("tokens_estimated")
    ]
    return max(done) if done else SESSION_TOKENS


def charged(out: Path, cause: str | None, ledger: Path) -> tuple[int, bool]:
    """The tokens a call is charged, and whether they are an estimate (README reading 12).

    An output that reports no usage (no result, or a result whose ``modelUsage`` is empty, as the
    binary's structured-output exhaustion reports it) is charged ceil(turns / 2), at least 1,
    times :func:`charge_unit`, unless it is a refusal (a usage limit, a rate limit, a refused
    credential) before any model turn completed: no result, or ``num_turns`` at most 1. A charge
    never counts less than the output reports.
    """
    reported = tokens_of(out)
    if reports_usage(out):
        return reported, False
    refusal = bool(cause) and str(cause).split(" ", 1)[0] in REFUSED_BEFORE_WORK
    if refusal and (not result_message(out) or turns_of(out) <= 1):
        return reported, False
    return max(reported, max(1, math.ceil(turns_of(out) / 2)) * charge_unit(ledger)), True


def ledger_row(
    step: str,
    packet: str,
    tr: int,
    model_asked: str,
    out: Path,
    code: int,
    valid: bool,
    standin: bool,
    cause: str | None,
    ledger: Path,
) -> dict[str, Any]:
    """One call's ledger line: the session driver writes exactly this, counted here, with the
    ledger as it stands when the line is written."""
    tokens, estimated = charged(out, cause, ledger)
    row = {
        "step": step,
        "packet": packet,
        "try": int(tr),
        "model_asked": model_asked,
        "models_used": model_of(out),
        "tokens": tokens,
        "exit": int(code),
        "valid": valid,
        "standin": standin,
        "infrastructure": cause or None,
        "utc": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if estimated:
        row["tokens_estimated"] = True
    if cause:  # a failed call's kept output: the evidence the owner reads (README reading 17)
        row["output"] = Path(out).name
    return row


def append_row(ledger: Path, row: dict[str, Any]) -> None:
    """Append one whole line in one write, so drivers appending at once never interleave."""
    data = (json.dumps(row, sort_keys=True) + "\n").encode()
    fd = os.open(ledger, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        written = os.write(fd, data)
    finally:
        os.close(fd)
    if written != len(data):
        raise OSError(f"a short write to {ledger}: {written} of {len(data)} bytes")


def ledger_rows(ledger: Path) -> list[dict[str, Any]]:
    """Every row of the ledger, or :class:`LedgerUnreadable` if any line is not a whole row whose
    token count is a non-negative integer. A ledger not yet written has no rows."""
    if not Path(ledger).exists():
        return []
    try:
        text = Path(ledger).read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerUnreadable(f"the ledger cannot be read: {exc}") from exc
    rows = []
    for n, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except ValueError as exc:
            raise LedgerUnreadable(f"ledger line {n} is not a whole row") from exc
        t = r.get("tokens") if isinstance(r, dict) else None
        if type(t) is not int or t < 0:
            raise LedgerUnreadable(f"ledger line {n} has no token count that is a whole number")
        rows.append(r)
    return rows


def ledger_total(ledger: Path) -> int:
    """The ledger's token total over every try and failed call (the 60 M guard reads this)."""
    return sum(r["tokens"] for r in ledger_rows(ledger))


# ---------------------------------------------------------------- the form's fields


def _need(form: dict[str, Any], *names: str) -> None:
    for n in names:
        if n not in form or form[n] is None:
            raise Invalid(f"missing {n}")


def check_fields(form: dict[str, Any], adjudicator: bool = False) -> None:
    """Raise :class:`Invalid` unless the form has every field its code requires (§5.5)."""
    _need(form, "id", "defect", "code", "multiple_defects", "reason")
    code = form["code"]
    if code not in CODES:
        raise Invalid("code")
    if not isinstance(form["multiple_defects"], bool):
        raise Invalid("multiple_defects")
    if form["multiple_defects"]:
        _need(form, "further")
        fur = form["further"]
        if not isinstance(fur, list) or len(fur) > 2:
            raise Invalid("further")
        for f in fur:
            if not isinstance(f, dict) or f.get("code") not in CODES or not f.get("defect"):
                raise Invalid("further")
    if code in ("G", "L"):
        _need(
            form,
            "gate_relation",
            "relation",
            "law",
            "kind",
            "inputs",
            "tolerance",
            "evaluation",
            "family",
            "fallback_code",
        )
        if form["tolerance"] not in TOLERANCES:
            raise Invalid("tolerance")
        if form["tolerance"] == "relative":
            _need(form, "tolerance_percent")
            if not isinstance(form["tolerance_percent"], int | float):
                raise Invalid("tolerance_percent")
        if form["fallback_code"] not in FALLBACKS:
            raise Invalid("fallback_code")
    if code == "L-if-data":
        _need(form, "relation", "law", "kind", "inputs", "missing", "family")
        if not isinstance(form["missing"], list):
            raise Invalid("missing")
    if code in ("G", "L", "L-if-data"):
        if form["kind"] not in ("law", "limit"):
            raise Invalid("kind")
        if form["family"] not in (*range(1, 8), "none"):
            raise Invalid("family")
        if not isinstance(form["inputs"], list):
            raise Invalid("inputs")
        for i in form["inputs"]:
            if not isinstance(i, dict):
                raise Invalid("input")
            for n in ("symbol", "node", "value", "unit"):
                if n not in i:
                    raise Invalid("input field")
            if ("quantity" in i) == ("requirement" in i):
                raise Invalid("input quantity or requirement")
    if code == "D":
        _need(form, "d_kind")
        if form["d_kind"] not in D_KINDS:
            raise Invalid("d_kind")
    if code == "N":
        _need(form, "n_kind")
        if form["n_kind"] not in N_KINDS:
            raise Invalid("n_kind")
    if adjudicator:
        _need(form, "chosen")
        if form["chosen"] not in ("A", "B", "other"):
            raise Invalid("chosen")


REALITY = {
    "verdict": ("true_flaw", "not_a_flaw", "undecidable"),
    "origin": ("introduced", "already_in_base", "both", "n/a"),
}


def valid_forms(out: Path, fids: list[str], kind: str) -> dict[str, dict[str, Any]]:
    """The valid forms of one try, by finding id."""
    so = structured(out)
    found: dict[str, dict[str, Any]] = {}
    if so is None or not isinstance(so.get("findings"), list):
        return found
    for f in so["findings"]:
        if not isinstance(f, dict) or f.get("id") not in fids or f["id"] in found:
            continue
        try:
            if kind == "reality":
                for k, allowed in REALITY.items():
                    if f.get(k) not in allowed:
                        raise Invalid(k)
                if not isinstance(f.get("reason"), str):
                    raise Invalid("reason")
            else:
                check_fields(f, adjudicator=kind == "adjudicator")
        except Invalid:
            continue
        found[f["id"]] = f
    return found


# ---------------------------------------------------------------- the relation (§5.5)


class Failure(Exception):
    """A form whose relation does not hold up; ``kind`` is counted per coder."""

    def __init__(self, kind: str) -> None:
        super().__init__(kind)
        self.kind = kind


_UREG: Any = None


def ureg() -> Any:  # noqa: ANN401 - pint's registry
    global _UREG
    if _UREG is None:
        import pint

        _UREG = pint.UnitRegistry()
    return _UREG


def parse_unit(unit: str) -> Any:  # noqa: ANN401
    """A unit, held to the project's bounded spelling first (a few written symbols aliased)."""
    from physgate.unit_spelling import UNIT_SPELLING

    u = UNIT_ALIASES.get(unit.strip(), unit.strip())
    if u != "dimensionless" and not UNIT_SPELLING.fullmatch(u):
        raise Failure("unit_unparsed")
    try:
        return ureg().Unit(u)
    except Exception as exc:  # noqa: BLE001 - pint raises several kinds
        raise Failure("unit_unparsed") from exc


def si(value: float, unit: str) -> Any:  # noqa: ANN401
    """A value in SI base units: absolute temperatures to kelvin, ``delta_`` as differences."""
    q = ureg().Quantity(float(value), parse_unit(unit))
    try:
        return q.to_base_units()
    except Exception as exc:  # noqa: BLE001
        raise Failure("unit_unparsed") from exc


_ALLOWED_BIN = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
_CMP = {ast.Eq: "==", ast.LtE: "<=", ast.GtE: ">=", ast.Lt: "<", ast.Gt: ">"}


def parse_relation(text: str) -> tuple[ast.expr, str, ast.expr]:
    """Two sides and one comparison, every node of an allowed kind; else ``unparsed``."""
    try:
        tree = ast.parse(text.strip(), mode="eval")
    except SyntaxError as exc:
        raise Failure("unparsed") from exc
    body = tree.body
    if not isinstance(body, ast.Compare) or len(body.ops) != 1 or len(body.comparators) != 1:
        raise Failure("unparsed")
    op = _CMP.get(type(body.ops[0]))
    if op is None:
        raise Failure("unparsed")
    for side in (body.left, body.comparators[0]):
        for n in ast.walk(side):
            ok = isinstance(
                n,
                (
                    ast.BinOp,
                    ast.UnaryOp,
                    ast.Name,
                    ast.Constant,
                    ast.Call,
                    ast.Load,
                    *_ALLOWED_BIN,
                    ast.USub,
                    ast.UAdd,
                ),
            )
            if not ok:
                raise Failure("unparsed")
            if isinstance(n, ast.BinOp) and not isinstance(n.op, _ALLOWED_BIN):
                raise Failure("unparsed")
            if isinstance(n, ast.UnaryOp) and not isinstance(n.op, ast.USub | ast.UAdd):
                raise Failure("unparsed")
            if isinstance(n, ast.Constant) and (
                isinstance(n.value, bool) or not isinstance(n.value, int | float)
            ):
                raise Failure("unparsed")
            if isinstance(n, ast.Call) and not (
                isinstance(n.func, ast.Name)
                and n.func.id == "sqrt"
                and len(n.args) == 1
                and not n.keywords
            ):
                raise Failure("unparsed")
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Pow):
                for m in ast.walk(n.right):
                    if isinstance(m, ast.Name):
                        raise Failure("unparsed")
    return body.left, op, body.comparators[0]


def names_in(node: ast.expr) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name) and not _is_func(node, n)}


def _is_func(root: ast.expr, name: ast.Name) -> bool:
    return any(isinstance(c, ast.Call) and c.func is name for c in ast.walk(root))


def literals_in(node: ast.expr) -> list[float]:
    return [float(n.value) for n in ast.walk(node) if isinstance(n, ast.Constant)]  # type: ignore[arg-type]


def evaluate(node: ast.expr, env: dict[str, Any]) -> Any:  # noqa: ANN401
    if isinstance(node, ast.Constant):
        return float(node.value)  # type: ignore[arg-type]
    if isinstance(node, ast.Name):
        return env[node.id]
    if isinstance(node, ast.UnaryOp):
        v = evaluate(node.operand, env)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.Call):
        return evaluate(node.args[0], env) ** 0.5
    assert isinstance(node, ast.BinOp)
    a = evaluate(node.left, env)
    b = evaluate(node.right, env)
    if isinstance(node.op, ast.Add):
        return a + b
    if isinstance(node.op, ast.Sub):
        return a - b
    if isinstance(node.op, ast.Mult):
        return a * b
    if isinstance(node.op, ast.Div):
        return a / b
    return a ** float(b)


def terms(node: ast.expr) -> list[ast.expr]:
    """A side's additive terms, split at its top-level + and -."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add | ast.Sub):
        return terms(node.left) + terms(node.right)
    return [node]


def magnitude(v: Any) -> float:  # noqa: ANN401
    if hasattr(v, "to_base_units"):
        return float(v.to_base_units().magnitude)
    return float(v)


def dims(v: Any) -> Any:  # noqa: ANN401
    if hasattr(v, "dimensionality"):
        return v.to_base_units().dimensionality
    return ureg().Quantity(1.0).dimensionality


NUMBER = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")
# What may stand right before and right after a unit written in a requirement: a space, an
# opening or closing mark, the number itself before it, punctuation after it. Anything else
# makes it part of a longer word or unit ("h" in "heater", "W" in "Wh", "m" in "m/s").
UNIT_BEFORE = "\\s\\d(\\[{\"'“‘"
UNIT_AFTER = "\\s.,;:)\\]}\"'”’"


def unit_token_in(unit: str, text: str) -> bool:
    """Whether ``unit`` is written in ``text`` as a whole unit token."""
    return bool(re.search(rf"(?<![^{UNIT_BEFORE}]){re.escape(unit)}(?![^{UNIT_AFTER}])", text))


def input_quantity(i: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> Any:  # noqa: ANN401
    """The input's quantity, built from the node data; ``on_no_node`` if the address is absent."""
    node = nodes.get(i["node"])
    if node is None:
        raise Failure("on_no_node")
    if "requirement" in i:
        reqs = node.get("requirements") or []
        idx = i["requirement"]
        if not isinstance(idx, int) or isinstance(idx, bool) or not 0 <= idx < len(reqs):
            raise Failure("on_no_node")
        text = reqs[idx]
        unit = str(i["unit"])
        try:
            value = float(i["value"])
        except (TypeError, ValueError) as exc:
            raise Failure("value_differs") from exc
        if not any(float(t) == value for t in NUMBER.findall(text)):
            raise Failure("value_differs")
        if not unit or not unit_token_in(unit, text):
            raise Failure("unit_differs")
        return si(value, unit)
    q = (node.get("quantities") or {}).get(i["quantity"])
    if q is None or q.get("value") is None:
        raise Failure("on_no_node")
    try:
        same = float(i["value"]) == float(q["value"])
    except (TypeError, ValueError):
        same = False
    if not same:
        raise Failure("value_differs")
    if str(i["unit"]) != str(q.get("unit")):
        raise Failure("unit_differs")
    return si(q["value"], q["unit"])


def joined(a: str, b: str, nodes: dict[str, dict[str, Any]]) -> bool:
    """One node, or two joined by one direct ``constrains`` edge, either direction."""
    if a == b:
        return True
    return b in (nodes.get(a, {}).get("constrains") or []) or a in (
        nodes.get(b, {}).get("constrains") or []
    )


def verify_relation(form: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """§5.5 for one G or L form: the facts of a relation that holds up, or :class:`Failure`.

    A relation over no node value is not a law over this design (``no_input``), and an input the
    relation never reads is not one of its inputs (``unused_input``): both fall back.
    """
    inputs = form["inputs"]
    if not inputs:
        raise Failure("no_input")
    env: dict[str, Any] = {"pi": math.pi, "g_n": ureg().Quantity(9.80665, "m/s**2")}
    by_symbol: dict[str, dict[str, Any]] = {}
    for i in inputs:
        sym = i["symbol"]
        if not isinstance(sym, str) or not sym.isidentifier() or sym in (*CONSTANTS, "sqrt"):
            raise Failure("undefined_symbol")
        if sym in by_symbol:
            raise Failure("undefined_symbol")
        by_symbol[sym] = i
    built = {}
    for sym, i in by_symbol.items():
        built[sym] = input_quantity(i, nodes)
    left, op, right = parse_relation(str(form["relation"]))
    used = names_in(left) | names_in(right)
    if used - set(by_symbol) - set(CONSTANTS):
        raise Failure("undefined_symbol")
    if set(by_symbol) - used:
        raise Failure("unused_input")
    env.update(built)
    try:
        lv, rv = evaluate(left, env), evaluate(right, env)
        if dims(lv) != dims(rv):
            raise Failure("dimension")
        lm, rm = magnitude(lv), magnitude(rv)
        tm = [abs(magnitude(evaluate(t, env))) for t in [*terms(left), *terms(right)]]
    except Failure:
        raise
    except Exception as exc:  # noqa: BLE001 - pint and arithmetic errors alike
        raise Failure("dimension") from exc
    if not all(math.isfinite(x) for x in (lm, rm, *tm)):
        raise Failure("dimension")
    tol = form["tolerance"]
    if op not in TOLERANCES[tol]:
        raise Failure("comparator_class")
    allowance: float | None = None
    if tol == "rounding":
        allowance = ROUNDING * sum(tm)
        violated = abs(lm - rm) > allowance
    elif tol == "relative":
        pct = float(form["tolerance_percent"])
        if pct > RELATIVE_MAX or pct < 0:
            raise Failure("relative_above_25")
        allowance = pct / 100 * max(abs(lm), abs(rm))
        violated = abs(lm - rm) > allowance
    else:
        holds = {"<=": lm <= rm, ">=": lm >= rm, "<": lm < rm, ">": lm > rm}[op]
        violated = not holds
    lits = literals_in(left) + literals_in(right)
    if form["kind"] == "limit":
        ok = (
            isinstance(left, ast.Name)
            and isinstance(right, ast.Name)
            and left.id in by_symbol
            and right.id in by_symbol
            and left.id != right.id
            and op in ("<=", ">=")
            and not lits
        )
        if not ok or not isinstance(left, ast.Name) or not isinstance(right, ast.Name):
            raise Failure("pairing")
        a, b = by_symbol[left.id], by_symbol[right.id]

        def rating(i: dict[str, Any]) -> bool:
            if "requirement" in i:
                return True
            return bool(LIMIT_TOKENS & set(str(i["quantity"]).split("_")))

        if not (rating(a) or rating(b)) or not joined(a["node"], b["node"], nodes):
            raise Failure("pairing")
    if not violated:
        raise Failure("within_tolerance")
    left_inputs = names_in(left) & set(by_symbol)
    right_inputs = names_in(right) & set(by_symbol)
    return {
        "miss": abs(lm - rm),
        "allowance": allowance,
        "literals": lits,
        "one_input_each_side": len(left_inputs) == 1 and len(right_inputs) == 1,
        "non_integer_literal": any(float(x) != int(x) for x in lits),
    }


def verify_form(form: dict[str, Any], nodes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """The code after §5.5 and why: G and L recomputed; L-if-data's listed absences checked."""
    code = form["code"]
    out: dict[str, Any] = {"code_raw": code, "code": code, "failure": None, "inconsistent": False}
    if code in ("G", "L"):
        try:
            out["relation_facts"] = verify_relation(form, nodes)
        except Failure as f:
            out["failure"] = f.kind
            out["code"] = "L-if-data" if f.kind == "on_no_node" else form["fallback_code"]
    elif code == "L-if-data":
        for m in form.get("missing") or []:
            n = m.get("node") if isinstance(m, dict) else None
            q = m.get("quantity") if isinstance(m, dict) else None
            if n and q and q in ((nodes.get(n) or {}).get("quantities") or {}):
                out["inconsistent"] = True
    return out


# ---------------------------------------------------------------- one step's codes


def session_forms(
    packets: Path, sessions: Path, pid: str, kind: str, digest: str = X.PARTS_SHEET_SHA256
) -> tuple[dict[str, dict[str, Any] | None], dict[str, str]]:
    """Per finding id: the first try's valid form, else the retry's, else None; and which try."""
    key = json.loads((packets / "key.json").read_text())[pid]
    fids = list(key["findings"])
    text = (packets / f"{pid}.md").read_text()
    if not sheet_ok(text, digest):
        raise X.Refused(f"packet {pid} does not carry the full parts sheet at its digest")
    t1 = valid_forms(sessions / f"{pid}.try1.json", fids, kind)
    t2 = valid_forms(sessions / f"{pid}.try2.json", fids, kind)
    out: dict[str, dict[str, Any] | None] = {}
    used: dict[str, str] = {}
    for f in fids:
        if f in t1:
            out[f], used[f] = t1[f], "try1"
        elif f in t2:
            out[f], used[f] = t2[f], "try2"
        else:
            out[f], used[f] = None, "none"
    return out, used


def standin_marked(sessions: Path, pid: str) -> bool:
    return any((sessions / f"{pid}.try{t}.standin").exists() for t in (1, 2))


def codes_for(
    step: str,
    who: str,
    packets: Path,
    sessions: Path,
    sets: dict[str, X.SetData],
    digest: str = X.PARTS_SHEET_SHA256,
) -> list[dict[str, Any]]:
    keys = json.loads((packets / "key.json").read_text())
    kind = "adjudicator" if who == "adj" else "coder"
    rows = []
    for pid in sorted(keys):
        k = keys[pid]
        nodes = sets[k["set"]].version(k["pair"], k["side"])
        forms, used = session_forms(packets, sessions, pid, kind, digest)
        stand = standin_marked(sessions, pid)
        for fid, line_id in k["findings"].items():
            form = forms[fid]
            row: dict[str, Any] = {
                "step": step,
                "who": who,
                "packet": pid,
                "fid": fid,
                "line_id": line_id,
                "try": used[fid],
                "standin": stand,
                "form": form,
            }
            if form is None:
                row.update({"code_raw": None, "code": None, "failure": "no_form"})
            else:
                row.update(verify_form(form, nodes))
            if who == "adj":
                row["labels"] = k.get("labels", {}).get(fid)
            rows.append(row)
    return rows


def passed(row: dict[str, Any]) -> bool:
    return row.get("form") is not None and row.get("failure") is None


def deciding_forms(
    codes: list[dict[str, Any]], step: str = "measured"
) -> dict[str, dict[str, Any] | None]:
    """§5.6: the adjudicator's form where adjudicated; where the coders agreed, coder 1's form if
    it passed §5.5, else coder 2's. Each returned form carries its verification."""
    by: dict[str, dict[str, dict[str, Any]]] = {}
    for r in codes:
        if r["step"] == step and r["who"] in ("c1", "c2", "adj"):
            by.setdefault(r["line_id"], {})[r["who"]] = r
    out: dict[str, dict[str, Any] | None] = {}
    for lid, w in by.items():
        c1, c2, adj = w.get("c1"), w.get("c2"), w.get("adj")
        if c1 is None or c2 is None or c1["form"] is None or c2["form"] is None:
            out[lid] = None
        elif c1["code"] == c2["code"]:
            pick = c1 if passed(c1) else c2
            out[lid] = {**pick["form"], "_verified": pick}
        elif adj is not None and adj["form"] is not None:
            out[lid] = {**adj["form"], "_verified": adj}
        else:
            out[lid] = None
    return out


def main(argv: list[str]) -> int:
    if argv[:1] == ["ledger"] and len(argv) == 11:
        led, step, packet, tr, model, out, code, valid, standin, cause = argv[1:]
        row = ledger_row(
            step,
            packet,
            int(tr),
            model,
            Path(out),
            int(code),
            valid == "1",
            standin == "1",
            cause,
            Path(led),
        )
        append_row(Path(led), row)
        return 0
    if argv[:1] == ["spent"] and len(argv) == 2:
        try:
            total = ledger_total(Path(argv[1]))
        except LedgerUnreadable as exc:
            print(json.dumps({"refused": str(exc)}))
            return 1
        print(total)
        return 0
    if argv[:1] == ["valid"] and len(argv) in (5, 6):
        kind, packet, key_path, out = argv[1], Path(argv[2]), Path(argv[3]), Path(argv[4])
        # A sixth argument names another sheet digest: the driver passes one for a stand-in only.
        digest = argv[5] if len(argv) == 6 else X.PARTS_SHEET_SHA256
        if not sheet_ok(packet.read_text(), digest):
            print(json.dumps({"refused": "the packet lacks the full parts sheet"}))
            return 3
        pid = packet.stem
        fids = list(json.loads(key_path.read_text())[pid]["findings"])
        found = valid_forms(out, fids, kind)
        return 0 if len(found) == len(fids) else 1
    if argv[:1] == ["codes"] and len(argv) == 6:
        work, step, who, packets, sessions = (
            Path(argv[1]),
            argv[2],
            argv[3],
            Path(argv[4]),
            Path(argv[5]),
        )
        try:
            sets = {n: X.load_set(X.FROZEN, n) for n in X.SETS}
            rows = codes_for(step, who, packets, sessions, sets)
        except X.Refused as exc:
            print(json.dumps({"refused": str(exc)}))
            return 1
        prior = X.read_jsonl(work / "codes.jsonl") if (work / "codes.jsonl").exists() else []
        if any(r["step"] == step and r["who"] == who for r in prior):
            print(json.dumps({"refused": f"codes for {step}/{who} exist; never rewritten"}))
            return 1
        X.write_jsonl(work / "codes.jsonl", prior + rows)
        from collections import Counter

        print(
            json.dumps(
                {
                    "step": step,
                    "who": who,
                    "forms": len(rows),
                    "without_form": sum(1 for r in rows if r["form"] is None),
                    "retries_used": sum(1 for r in rows if r["try"] == "try2"),
                    "failures": dict(Counter(r["failure"] for r in rows if r["failure"])),
                    "inconsistent_l_if_data": sum(1 for r in rows if r.get("inconsistent")),
                },
                sort_keys=True,
            )
        )
        return 0
    print(__doc__.split("\n\n")[1], file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
