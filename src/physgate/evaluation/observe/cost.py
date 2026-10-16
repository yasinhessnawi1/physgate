"""A run's cost: its tokens at a dated sheet's prices, one line per run in a trend file.

ARCH-150 asks for the cost of every run, recorded and trended. The tokens come from
the run's own token account; the prices come from a **dated price sheet**, one JSON
file per date in ``prices/``, which names the page its prices were read from, when,
and the digest of the page as read, and the same for its exchange rate.

**A price change is a decision, not an edit.** A sheet is never edited; a new price
is a new dated sheet. The code holds each sheet's digest beside its date, so an
edited sheet does not load, and every cost line carries its sheet's date and digest,
so the trend's reader refuses a date that arrives with another digest.

**The cost line never mixes auth modes silently.** A run on the subscription is not
billed per token: its figure is what the tokens would cost at list price, and the
line says so in its ``basis``, which the line's own schema ties to the auth mode. A
run on an API key is priced at the sheet's list prices, which is what the tokens
were billed at unless the account has terms the sheet does not know.

A token is priced at the model that spent it: the decomposition model, the model of
the role a session worked for, or the model a reviewer reported. A model the sheet
does not price is refused, never priced at zero.

**A cache write is priced at the rate of the cache it went to.** The five-minute and
the one-hour cache are billed at different write rates, and the run's account does
not say which a write went to. The first sheet priced every write at the five-minute
rate, on the premise that the binary sets no time to live; on the subscription it
writes one-hour entries, so every such line was low. A sheet that prices per call
(``cache_write_ttl: per_call``) carries both rates, and each call's writes are split
by what its own result event recorded (``calls.read_call``). A call whose split was
not read is priced at the five-minute rate and named, so the line says where it is a
lower bound.

**Every call is held to the binary's own figure.** Where a call's result reports
``total_cost_usd``, the line keeps it beside the call's price, and the line's
reconciliation names every call whose two figures disagree, never averaging them away.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from physgate.evaluation.observe.calls import CacheWrites, RecordedCall, run_calls, stream_seals
from physgate.evaluation.observe.exceptions import ManifestError, PriceSheetError, TrendError
from physgate.evaluation.observe.manifest import Sha256, read_manifest, read_run_events
from physgate.evaluation.observe.ratio import RATIO_KIND, RatioLine
from physgate.orchestrator.accounting import TokenAccount
from physgate.orchestrator.common import (
    AuthMode,
    ModelString,
    NonEmptyStr,
    Timestamp,
    first_problem,
)
from physgate.orchestrator.events import (
    Event,
    LeftoverRead,
    ReviewRan,
    ReviewUnavailable,
    SessionEnded,
    SubtaskPlanned,
    TokensUsed,
)
from physgate.orchestrator.protocols import Usage
from physgate.orchestrator.run_config import RunConfig

PRICES = Path(__file__).resolve().parent / "prices"

#: Every sheet's digest, by its date: the sheet as it was read and recorded. A sheet
#: whose bytes differ from its digest here does not load.
KNOWN_SHEETS: dict[str, str] = {
    "2026-09-27": "887b0f8875a04c5a0f482836dbaf6b0d9a1bfe42c2b1887f9bb8c9f3ea2dec54",
    "2026-10-16": "7e41d3e899ecc07ca6f64cba2aa29aa17a6964ceba8e99c9cd7b3ab2024f1da6",
}

#: How far a call's price may lie from the binary's own figure and still agree with it: a
#: billionth of a dollar, the noise of the binary's floating-point sum and never a token.
RECONCILE_TOLERANCE_USD = Decimal("0.000000001")

IsoDate = Annotated[str, StringConstraints(pattern=r"^\d{4}-\d\d-\d\d$")]
Url = Annotated[str, StringConstraints(pattern=r"^https://\S+$")]
Price = Annotated[Decimal, Field(ge=0)]
_MTOK = Decimal(1_000_000)
_ZERO = Usage(
    input_tokens=0, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=0
)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class ModelPrice(_Frozen):
    """One model's list prices, in USD per million tokens, per token class.

    ``cache_write`` is the five-minute cache's write rate; ``cache_write_1h`` the
    one-hour cache's, on a sheet that prices each call's writes by the cache they went
    to, and absent from one that prices every write at the five-minute rate.
    """

    input: Price
    cache_write: Price
    cache_read: Price
    output: Price
    cache_write_1h: Price | None = None

    def usd(self, usage: Usage, writes: CacheWrites | None = None) -> Decimal:
        """What ``usage`` costs at these prices.

        With ``writes``, the call's cache writes by the cache they went to, each part is
        priced at its own rate; without, every write is priced at the five-minute rate.

        Raises:
            PriceSheetError: ``writes`` does not add up to the cache writes in ``usage``,
                or names one-hour writes these prices give no rate for.
        """
        written = usage.cache_creation_input_tokens * self.cache_write
        if writes is not None:
            if writes.total() != usage.cache_creation_input_tokens:
                msg = "a call's cache writes by time to live do not add up to what it wrote"
                raise PriceSheetError(
                    msg,
                    split=str(writes.total()),
                    written=str(usage.cache_creation_input_tokens),
                )
            if writes.one_hour and self.cache_write_1h is None:
                msg = "the sheet gives no one-hour cache-write rate for a call that paid it"
                raise PriceSheetError(msg)
            written = writes.five_minute * self.cache_write + writes.one_hour * (
                self.cache_write_1h or Decimal(0)
            )
        return (
            usage.input_tokens * self.input
            + written
            + usage.cache_read_input_tokens * self.cache_read
            + usage.output_tokens * self.output
        ) / _MTOK


class ExchangeRate(_Frozen):
    """The USD to NOK rate a sheet converts with, and where and when it was read."""

    usd_to_nok: Annotated[Decimal, Field(gt=0)]
    #: The date the rate is for, which may precede the sheet's (a weekend, a holiday).
    date: IsoDate
    series: NonEmptyStr
    source: Url
    retrieved: Timestamp


class PriceSheet(_Frozen):
    """The prices of one date, with the page they were read from."""

    date: IsoDate
    source: Url
    retrieved: Timestamp
    #: The digest of the page as it was read, kept with the evidence of the reading.
    page_sha256: Sha256
    note: NonEmptyStr
    #: How cache writes are priced. ``5m``: every write at ``cache_write``, the
    #: five-minute rate (the first sheet's premise, that the binary marks its breakpoints
    #: with no time to live; on the subscription it writes one-hour entries). ``per_call``:
    #: each call's writes at the rate of the cache its own result says they went to, so
    #: every model carries ``cache_write_1h`` as well.
    cache_write_ttl: Literal["5m", "per_call"]
    usd_per_mtok: dict[ModelString, ModelPrice]
    exchange: ExchangeRate

    @model_validator(mode="after")
    def _one_hour_rate_follows_the_ttl(self) -> PriceSheet:
        per_call = self.cache_write_ttl == "per_call"
        for model, price in self.usd_per_mtok.items():
            if (price.cache_write_1h is not None) != per_call:
                msg = (
                    f"{model}: a sheet that prices writes per call gives a one-hour rate for "
                    "every model, and a five-minute sheet gives none"
                )
                raise ValueError(msg)
        return self


class DatedSheet(_Frozen):
    """A price sheet as loaded, with the digest of its file."""

    sheet: PriceSheet
    sha256: Sha256


def load_price_sheet(
    date: str, *, directory: Path = PRICES, known: dict[str, str] | None = None
) -> DatedSheet:
    """The price sheet of ``date``, held to the digest recorded for it.

    Raises:
        PriceSheetError: no sheet is recorded for the date, its file is missing or
            not the one recorded, it is incomplete, or it names another date.
    """
    known = KNOWN_SHEETS if known is None else known
    if date not in known:
        msg = "no price sheet is recorded for this date"
        raise PriceSheetError(msg, date=date)
    path = directory / f"{date}.json"
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        msg = "the price sheet recorded for this date is missing"
        raise PriceSheetError(msg, date=date, path=str(path)) from None
    digest = hashlib.sha256(raw).hexdigest()
    if digest != known[date]:
        msg = "the price sheet is not the one recorded for its date: a new price is a new sheet"
        raise PriceSheetError(msg, date=date, recorded=known[date], found=digest)
    try:
        sheet = PriceSheet.model_validate_json(raw)
    except ValidationError as exc:
        msg = "the price sheet is incomplete"
        raise PriceSheetError(msg, date=date, reason=first_problem(exc)) from None
    if sheet.date != date:
        msg = "the price sheet names another date than its file"
        raise PriceSheetError(msg, date=date, named=sheet.date)
    return DatedSheet(sheet=sheet, sha256=digest)


class CostRow(_Frozen):
    """One model's tokens in a run and what they cost."""

    model: ModelString
    tokens: Usage
    usd: Decimal


class CallCost(_Frozen):
    """One call at the line's prices, beside what the binary itself said it cost."""

    #: The account's attribution of the call: ``decomposition:``, ``session:`` or
    #: ``reviewer:`` and its session id.
    attribution: NonEmptyStr
    model: ModelString
    tokens: Usage
    #: Its cache writes by the cache they went to, from its result; ``None`` where no
    #: result was read, and then every write is priced at the five-minute rate.
    cache_writes: CacheWrites | None
    usd: Decimal
    #: The binary's own figure for the call (``total_cost_usd``); ``None`` where no
    #: result reporting one was read.
    binary_usd: Decimal | None
    #: Whether the two figures agree within ``RECONCILE_TOLERANCE_USD``; ``None``
    #: where there is no binary figure to hold the call to.
    agrees: bool | None


class Reconciliation(_Frozen):
    """The line held to the binary's own figures, call by call. A disagreement is named."""

    #: The binary's figures, summed over every call that has one.
    binary_usd: Decimal
    #: The line's figures over the same calls.
    priced_usd: Decimal
    #: The calls whose two figures disagree.
    differs: tuple[NonEmptyStr, ...]
    #: The calls with no binary figure read: no result, or no review root named for it.
    unread: tuple[NonEmptyStr, ...]
    #: The calls with cache writes whose time to live was not read: priced at the
    #: five-minute rate, so the line is a lower bound for them.
    ttl_unread: tuple[NonEmptyStr, ...]


class CostLine(_Frozen):
    """One run's cost at one sheet's prices: a line of the trend file."""

    manifest_id: Sha256
    run_id: NonEmptyStr
    started: Timestamp
    auth: AuthMode
    endpoint: NonEmptyStr
    #: What the figure is: the list price of tokens billed on an API key, or, on the
    #: subscription, an estimate of what the tokens would cost at list price.
    basis: Literal["list_price", "list_price_estimate"]
    prices_date: IsoDate
    prices_sha256: Sha256
    usd_to_nok: Decimal
    usd_to_nok_date: IsoDate
    rows: tuple[CostRow, ...]
    usd: Decimal
    nok: Decimal
    #: Some of the run's usage was read from a stream with no result: the figure may
    #: be short of what was spent.
    partial: bool
    #: What reviewing spent, by subtask: every review of its attempts, verdict or not.
    #: A review left over from a killed orchestrator names no subtask, and is under
    #: ``(left over)``. Absent from lines written before reviews were real.
    review_tokens: dict[NonEmptyStr, Usage] = Field(default_factory=dict)
    #: Every call priced, with the binary's own figure beside it. Empty on a line priced
    #: without the calls' records, as every line before the per-call sheet was.
    calls: tuple[CallCost, ...] = ()
    #: The line held to the binary's figures; ``None`` where the records were not read.
    reconciliation: Reconciliation | None = None

    @model_validator(mode="after")
    def _basis_follows_auth(self) -> CostLine:
        wanted = "list_price_estimate" if self.auth == "subscription" else "list_price"
        if self.basis != wanted:
            msg = f"a run on {self.auth} is costed as {wanted}"
            raise ValueError(msg)
        return self


def _role_model(config: RunConfig, session_id: str) -> str:
    models = set(config.models.roles.values())
    if len(models) != 1:
        msg = "the log does not say which role a session worked for, and roles differ in model"
        raise ManifestError(msg, session_id=session_id)
    return models.pop()


def _model_of(attribution: str, config: RunConfig, events: list[Event]) -> str:
    kind, who = attribution.split(":", 1)
    if kind == "decomposition":
        return config.models.decomposition
    if kind == "reviewer":
        for e in events:
            if isinstance(e, ReviewRan) and e.result.session_id == who:
                return e.result.reviewer_model
            if isinstance(e, ReviewUnavailable) and e.session_id == who and e.reviewer_model:
                return e.reviewer_model
        # A review whose orchestrator died before it recorded anything: found at the
        # resume, it names no role, so it is priced at the one reviewer model if the
        # run pinned only one.
        if any(isinstance(e, LeftoverRead) and e.session_id == who for e in events):
            models = set(config.models.reviewers.values())
            if len(models) == 1:
                return models.pop()
            msg = "the log does not say which role a left-over review was for, and they differ"
            raise ManifestError(msg, attribution=attribution)
        msg = "a reviewer spent tokens the log records no review for"
        raise ManifestError(msg, attribution=attribution)
    if kind == "session":
        roles = {e.subtask_id: e.assigned_role for e in events if isinstance(e, SubtaskPlanned)}
        for e in events:
            if isinstance(e, SessionEnded) and e.session_id == who:
                return config.models.roles[roles[e.subtask_id]]
        return _role_model(config, who)
    msg = "tokens attributed to routing have no model to price them at"
    raise ManifestError(msg, attribution=attribution)


#: Where a review's tokens go when the log names no subtask for it.
LEFT_OVER = "(left over)"


def _reviewed_subtask(session_id: str, events: list[Event]) -> str:
    """The subtask a review session judged, as its review line or its unavailable line says."""
    for e in events:
        if isinstance(e, ReviewRan) and e.result.session_id == session_id:
            return e.subtask_id
        if isinstance(e, ReviewUnavailable) and e.session_id == session_id:
            return e.subtask_id
    return LEFT_OVER


def _plus(left: Usage, right: Usage) -> Usage:
    return Usage(**{f: getattr(left, f) + getattr(right, f) for f in Usage.model_fields})


def price_run(run_dir: Path, prices: DatedSheet, *, review_roots: Sequence[Path] = ()) -> CostLine:
    """The run's cost at ``prices``: every token the run's account holds, by model and call.

    Each call's result is read from its stream (the reviews' under ``review_roots``),
    for the time to live of its cache writes and the binary's own figure.

    Raises:
        ManifestError: the run's records do not make a manifest, a token's model cannot
            be told from them, a call's stream is not the one sealed when its session
            ended, or a call's result is another session's.
        PriceSheetError: a model the run used has no price on the sheet, or a call's
            cache writes by time to live do not add up.
    """
    manifest = read_manifest(run_dir)
    events = read_run_events(run_dir)
    attributions = TokenAccount.from_events(events).by_attribution()
    calls = run_calls(run_dir, attributions, review_roots, seals=stream_seals(events))
    return price_events(manifest.config, manifest.manifest_id, events, prices, calls=calls)


def _price(model: str, prices: DatedSheet) -> ModelPrice:
    price = prices.sheet.usd_per_mtok.get(model)
    if price is None:
        msg = "the price sheet has no price for a model the run used"
        raise PriceSheetError(msg, model=model, date=prices.sheet.date)
    return price


def _call_cost(
    attribution: str, model: str, usage: Usage, recorded: RecordedCall | None, prices: DatedSheet
) -> CallCost:
    """One call at ``prices``: its writes split as its result says, on a per-call sheet."""
    writes = recorded.cache_writes if recorded is not None else None
    split = writes if prices.sheet.cache_write_ttl == "per_call" else None
    usd = _price(model, prices).usd(usage, split)
    binary = recorded.binary_usd if recorded is not None else None
    return CallCost(
        attribution=attribution,
        model=model,
        tokens=usage,
        cache_writes=writes,
        usd=usd,
        binary_usd=binary,
        agrees=None if binary is None else abs(usd - binary) <= RECONCILE_TOLERANCE_USD,
    )


def reconcile(calls: Sequence[CallCost]) -> Reconciliation:
    """``calls`` held to the binary's own figures: what agrees, what differs, what was unread."""
    held = [c for c in calls if c.binary_usd is not None]
    return Reconciliation(
        binary_usd=sum((c.binary_usd or Decimal(0) for c in held), Decimal(0)),
        priced_usd=sum((c.usd for c in held), Decimal(0)),
        differs=tuple(c.attribution for c in held if c.agrees is False),
        unread=tuple(c.attribution for c in calls if c.binary_usd is None),
        ttl_unread=tuple(
            c.attribution
            for c in calls
            if c.cache_writes is None and c.tokens.cache_creation_input_tokens
        ),
    )


def price_events(
    config: RunConfig,
    manifest_id: str,
    events: list[Event],
    prices: DatedSheet,
    *,
    calls: Mapping[str, RecordedCall] | None = None,
) -> CostLine:
    """The cost of the tokens in ``events`` at ``prices``, from records already read.

    ``price_run`` reads them through the run's manifest, which also checks the
    commits it names in the run's repositories. This prices the same records without
    that step, for a reader that may start no process: the operator UI's server,
    which runs no git.

    ``calls`` is what each call's result recorded (``calls.run_calls``). Given, every
    call is priced on its own, its writes split by its result on a sheet that prices
    per call, and held to the binary's own figure; a call it does not hold is priced
    with every write at the five-minute rate and named as unread. Not given, the line
    has the form every line before the per-call sheet had, and on a sheet that prices
    per call every write is priced at the five-minute rate, a lower bound.

    Raises:
        ManifestError: a token's model cannot be told from the records.
        PriceSheetError: a model the run used has no price on the sheet, or a call's
            cache writes by time to live do not add up.
    """
    by_model: dict[str, Usage] = {}
    usd_by_model: dict[str, Decimal] = {}
    reviews: dict[str, Usage] = {}
    priced: list[CallCost] = []
    for attribution, usage in TokenAccount.from_events(events).by_attribution().items():
        model = _model_of(attribution, config, events)
        by_model[model] = _plus(by_model.get(model, _ZERO), usage)
        recorded = None if calls is None else calls.get(attribution)
        call = _call_cost(attribution, model, usage, recorded, prices)
        priced.append(call)
        usd_by_model[model] = usd_by_model.get(model, Decimal(0)) + call.usd
        if attribution.startswith("reviewer:"):
            subtask = _reviewed_subtask(attribution.split(":", 1)[1], events)
            reviews[subtask] = _plus(reviews.get(subtask, _ZERO), usage)
    rows = [
        CostRow(model=model, tokens=usage, usd=usd_by_model[model])
        for model, usage in sorted(by_model.items())
    ]
    usd = sum((r.usd for r in rows), Decimal(0))
    rate = prices.sheet.exchange
    return CostLine(
        manifest_id=manifest_id,
        run_id=config.run_id,
        started=events[0].ts,
        auth=config.auth,
        endpoint=config.endpoint,
        basis="list_price_estimate" if config.auth == "subscription" else "list_price",
        prices_date=prices.sheet.date,
        prices_sha256=prices.sha256,
        usd_to_nok=rate.usd_to_nok,
        usd_to_nok_date=rate.date,
        rows=tuple(rows),
        usd=usd,
        nok=usd * rate.usd_to_nok,
        partial=any(isinstance(e, TokensUsed) and e.partial for e in events),
        review_tokens=dict(sorted(reviews.items())),
        calls=() if calls is None else tuple(priced),
        reconciliation=None if calls is None else reconcile(priced),
    )


#: A line of the trend: a run's cost, or a paired-versus-generalist ratio.
TrendLine = CostLine | RatioLine


def _identity(line: TrendLine) -> tuple[str, ...]:
    """What makes two lines the same measurement, at the same sheet's prices."""
    if isinstance(line, CostLine):
        return ("cost", line.manifest_id, line.prices_date)
    ratio = line.ratio
    return ("ratio", ratio.paired.session_id, ratio.generalist.session_id, ratio.prices_date)


def _sheet(line: TrendLine) -> tuple[str, str]:
    if isinstance(line, CostLine):
        return line.prices_date, line.prices_sha256
    return line.ratio.prices_date, line.ratio.prices_sha256


def _admit(line: TrendLine, seen: list[TrendLine], known: dict[str, str], where: str) -> None:
    date, digest = _sheet(line)
    recorded = known.get(date)
    earlier = dict(_sheet(s) for s in seen).get(date)
    for wanted in (recorded, earlier):
        if wanted is not None and wanted != digest:
            msg = "a price sheet date arrives with another digest than it was recorded with"
            raise TrendError(msg, line=where, date=date, recorded=wanted)
    if any(_identity(s) == _identity(line) for s in seen):
        if isinstance(line, CostLine):
            msg = "the trend already holds this run at this sheet's prices"
            raise TrendError(msg, line=where, manifest_id=line.manifest_id)
        msg = "the trend already holds this ratio at this sheet's prices"
        raise TrendError(msg, line=where, generalist=line.ratio.generalist.session_id)


def _parse(raw: str) -> TrendLine:
    """One line, as the one model its shape names; anything else is refused."""
    if not raw.endswith("\n"):
        raise ValueError("the line has no end")
    shape = json.loads(raw)
    if isinstance(shape, dict) and shape.get("kind") == RATIO_KIND:
        return RatioLine.model_validate_json(raw)
    return CostLine.model_validate_json(raw)


def read_trend_lines(path: Path, *, known: dict[str, str] | None = None) -> tuple[TrendLine, ...]:
    """Every line of the trend file, each checked; the one reader of the format.

    A missing file is an empty trend.

    Raises:
        TrendError: a line is neither a cost line nor a ratio line its writer could have
            written, cites a sheet date with another digest than recorded, or repeats a
            run, or a ratio, at a sheet's prices.
    """
    known = KNOWN_SHEETS if known is None else known
    try:
        text = Path(path).read_text()
    except FileNotFoundError:
        return ()
    lines: list[TrendLine] = []
    for number, raw in enumerate(text.splitlines(keepends=True), 1):
        try:
            line = _parse(raw)
        except (ValidationError, ValueError) as exc:
            reason = first_problem(exc) if isinstance(exc, ValidationError) else str(exc)
            msg = "the trend holds a line its writer could not have written"
            raise TrendError(msg, line=str(number), reason=reason) from None
        _admit(line, lines, known, str(number))
        lines.append(line)
    return tuple(lines)


def read_trend(path: Path, *, known: dict[str, str] | None = None) -> tuple[CostLine, ...]:
    """The trend's cost lines, every line of the file checked (:func:`read_trend_lines`).

    Raises:
        TrendError: as :func:`read_trend_lines`.
    """
    return tuple(line for line in read_trend_lines(path, known=known) if isinstance(line, CostLine))


def _append(path: Path, line: TrendLine, known: dict[str, str] | None) -> None:
    known = KNOWN_SHEETS if known is None else known
    seen = list(read_trend_lines(path, known=known))
    _admit(line, seen, known, str(len(seen) + 1))
    with Path(path).open("ab") as out:
        out.write(line.model_dump_json().encode() + b"\n")
        out.flush()
        os.fsync(out.fileno())


def append_cost_line(path: Path, line: CostLine, *, known: dict[str, str] | None = None) -> None:
    """Append ``line`` to the trend at ``path``, after checking the whole file and it.

    Raises:
        TrendError: the file or the line would break a rule ``read_trend_lines`` holds.
    """
    _append(path, line, known)


def append_ratio_line(path: Path, line: RatioLine, *, known: dict[str, str] | None = None) -> None:
    """Append a ratio ``line`` to the trend at ``path``, after checking the whole file and it.

    Raises:
        TrendError: the file or the line would break a rule ``read_trend_lines`` holds.
    """
    _append(path, line, known)
