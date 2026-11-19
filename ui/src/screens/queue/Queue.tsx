/**
 * One run's approval queue: the items waiting and those resolved on the left, the chosen item on
 * the right with everything a person needs to decide it, and the decision itself, the one write
 * this app makes. Every figure is read from the run's queue and event log through the server; the
 * decision is sent with what this page showed, and recorded by the queue's own function.
 */
import { useEffect, useRef, useState } from "react";

import {
  actToken,
  getJson,
  getLines,
  pageOperator,
  postAction,
  type ReadOptions,
  type Result,
} from "../../api/client";
import { runEvent } from "../../api/events";
import {
  decisionRequest,
  type ItemView,
  itemView,
  type PartsPosition,
  partsRequest,
  type Position,
  queueListing,
  type Resolved,
  resolved,
  type StatedPart,
  type Verb,
} from "../../api/queue";
import { Segmented } from "../../design/components/actions/Segmented";
import { Id } from "../../design/components/data/Id";
import {
  EmptyState,
  ErrorState,
  LoadingState,
  type Refusal,
} from "../../design/components/status/States";
import { StatusTag } from "../../design/components/status/StatusTag";
import type { ViewProps } from "../../shell/header";
import { hrefFor } from "../../shell/route";
import { foundAllStoppedWords, foundAllWords, PARTS_COPY, releasedWords } from "../../words/parts";
import { REFRESH_FAILED, SOURCE_WORDS } from "../../words/queue";
import { allItems } from "../common/queueItems";
import { subtaskNames } from "../common/rows";
import { RunSwitcher } from "../common/RunSwitcher";
import { phaseOfResult, runSource, useChosenRun } from "../common/runs";
import { useResult } from "../common/useResult";
import { Decide } from "./Decide";
import { FindRemaining } from "./FindRemaining";
import { chosenItem } from "./model";
import {
  componentOf,
  earlierDecision,
  everyPartDecided,
  nextOpenPart,
  partRound,
  planComponents,
  raisedBy,
  releasedChoices,
} from "./parts";
import { PartsDecide, PartsRefusal } from "./PartsDecide";
import { QueueItem } from "./QueueItem";
import { useHeldResult } from "./useHeld";

const AREA = "collaboration";
const SLUG = "approval-queue";

/**
 * How often the page reads the run's queue again while it is open, so an item the run adds (a
 * part the gate raised again) and the run's release appear without opening the page again.
 */
const READ_AGAIN_MS = 5_000;

/**
 * A read made on a tick is given up a second before the next tick is due: a server that stops
 * answering is then said to (the read fails, and the page keeps what it holds; a read the next
 * tick replaced would be dropped unsaid), and its reads never pile up behind one another, holding
 * the browser's few connections from the decision a person sends.
 */
const ON_TICK: ReadOptions = { timeoutMs: READ_AGAIN_MS - 1_000 };

/** A count that goes up every ``ms`` while the page is shown, and never while it is hidden. */
function useEvery(ms: number): number {
  const [n, setN] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => {
      if (document.visibilityState !== "hidden") setN((v) => v + 1);
    }, ms);
    return () => {
      clearInterval(timer);
    };
  }, [ms]);
  return n;
}

/** The part a person just recorded, said on the screen once its panel has moved on. */
interface JustRecorded {
  readonly label: string;
  readonly resolved: Resolved;
}

function ItemList({
  views,
  chosen,
  query,
  names,
  onPick,
}: {
  readonly views: readonly ItemView[];
  readonly chosen: ItemView | undefined;
  readonly query: URLSearchParams;
  readonly names: ReadonlyMap<string, string>;
  /** A person chose an item in the list: it is shown, whatever the page moved to by itself. */
  readonly onPick: () => void;
}) {
  const [show, setShow] = useState<"waiting" | "resolved">(
    chosen !== undefined && !chosen.open ? "resolved" : "waiting",
  );
  const waiting = views.filter((v) => v.open);
  const done = views.filter((v) => !v.open);
  // The list shows the tab that holds the item on screen whenever that item or its state changes,
  // as when it is decided; a person's own choice of tab stands until then.
  const onScreen = chosen === undefined ? "" : `${chosen.item.itemId}:${String(chosen.open)}`;
  const [followed, setFollowed] = useState(onScreen);
  if (onScreen !== followed) {
    setFollowed(onScreen);
    if (chosen !== undefined) setShow(chosen.open ? "waiting" : "resolved");
  }
  // An item that starts waiting while the page is open (a part the gate raised again) is shown.
  const ids = waiting.map((v) => v.item.itemId).join(",");
  const [seen, setSeen] = useState(ids);
  if (ids !== seen) {
    setSeen(ids);
    if (waiting.some((v) => !seen.split(",").includes(v.item.itemId))) setShow("waiting");
  }
  const listed = show === "waiting" ? waiting : done;
  return (
    <section className="pg-card pg-panel pg-queue-list" aria-label="Queue items">
      <header className="pg-panel-head">
        <h2 className="pg-panel-title">Items</h2>
        <Segmented
          label="Show items"
          value={show}
          onChange={setShow}
          options={[
            { value: "waiting", label: `Waiting · ${String(waiting.length)}` },
            { value: "resolved", label: `Resolved · ${String(done.length)}` },
          ]}
        />
      </header>
      {listed.length === 0 ? (
        <p className="pg-panel-empty">
          {show === "waiting" ? "Nothing is waiting in this run." : "Nothing is resolved yet."}
        </p>
      ) : (
        <nav aria-label="Queue items">
          <ul className="pg-list">
            {listed.map((view) => {
              const next = new URLSearchParams(query);
              next.set("item", view.item.itemId);
              // By id, not by object: the chosen item's view is read again when it is chosen, so
              // the one shown is a different object from the listed one for the same item.
              const on = view.item.itemId === chosen?.item.itemId;
              return (
                <li key={view.item.itemId}>
                  <a
                    className={
                      on ? "pg-queue-entry pg-queue-entry-on pg-hit" : "pg-queue-entry pg-hit"
                    }
                    aria-current={on ? "true" : undefined}
                    href={hrefFor(AREA, SLUG, next)}
                    onClick={onPick}
                  >
                    <span className="pg-queue-entry-head">
                      <span className="pg-panel-over">{SOURCE_WORDS[view.item.source].kind}</span>
                      <StatusTag status={view.open ? "waiting" : "resolved"} />
                    </span>
                    <span className="pg-queue-entry-title">
                      {names.get(view.item.subtaskId) ?? "The whole design"}
                    </span>
                    <Id value={view.item.itemId} copy={false} />
                  </a>
                </li>
              );
            })}
          </ul>
        </nav>
      )}
    </section>
  );
}

export default function Queue({ setHeader, query }: ViewProps) {
  const chosen = useChosenRun(query);
  const { runs, config, status, base, label } = chosen;
  // ``version`` goes up when a decision is written or refused, and everything is read again;
  // ``tick`` goes up while the page is open, and the listing is read again, held while it is.
  const [version, setVersion] = useState(0);
  const tick = useEvery(READ_AGAIN_MS);
  const scope = String(base);
  const listingRead = useHeldResult(
    base === null ? null : () => getJson(`${base}/queue`, queueListing, ON_TICK),
    scope,
    `${String(version)}#${String(tick)}`,
  );
  const listing = listingRead.result;
  const total =
    listing?.ok === true ? listing.value.open.length + listing.value.decided.length : null;
  // The items are read again only when the listing's items change, never on every tick; after
  // a read of them that failed, on every tick until one works.
  const [viewsFailed, setViewsFailed] = useState(false);
  const signature =
    listing?.ok === true
      ? [
          ...listing.value.open.map((o) => o.itemId),
          "|",
          ...listing.value.decided.map((d) => d.itemId),
        ].join(",")
      : null;
  const viewsRead = useHeldResult(
    base === null || total === null ? null : () => allItems(base, total),
    scope,
    `${String(signature)}#${String(version)}${viewsFailed ? `#${String(tick)}` : ""}`,
  );
  const views = viewsRead.result;
  // Adjusted while rendering, as React asks of state that follows what was read.
  if (viewsRead.failedAgain !== viewsFailed) setViewsFailed(viewsRead.failedAgain);
  // A list click or a new address names the item; after a decision the page moves on by itself.
  const asked = query.get("item");
  const [moved, setMoved] = useState<{ readonly asked: string | null; readonly to: string } | null>(
    null,
  );
  const wanted = moved !== null && moved.asked === asked ? moved.to : asked;
  const [advanceFrom, setAdvanceFrom] = useState<string | null>(null);
  const [focus, setFocus] = useState<"part" | "next" | null>(null);
  const [just, setJust] = useState<JustRecorded | null>(null);
  // What the last find of every remaining part came to: how many it recorded, of how many, and
  // the refusal that stopped it, if one did.
  const [foundAll, setFoundAll] = useState<{
    readonly recorded: number;
    readonly of: number;
    readonly refusal: Refusal | null;
  } | null>(null);
  const foundLine = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (foundAll !== null) foundLine.current?.focus();
  }, [foundAll]);
  // The server's last refusal of a part's choice, kept for when the part turns out to be
  // decided meanwhile and its panel gives way to the decided view.
  const [refusedOn, setRefusedOn] = useState<{
    readonly itemId: string;
    readonly refusal: Refusal;
  } | null>(null);
  // The chosen item's view is read again when it is chosen: the server stamps when it showed it,
  // and a decision's review time runs from that stamp, not from when the list was read. It is
  // never read again on a tick, so the stamp stands while the person decides.
  const picked = views?.ok === true ? chosenItem(views.value, wanted) : undefined;
  const fresh = useResult(
    base === null || picked === undefined || !picked.open
      ? null
      : () => getJson(`${base}/queue/items/${String(picked.position)}`, itemView),
    `${String(base)}/items/${String(picked?.position)}/shown#${String(version)}`,
  );
  // The run's log, read again on a tick only while a run that asked about its parts waits for
  // its release, so the release appears, or after a read of it failed; otherwise when a decision
  // is written or refused.
  const [awaitingRelease, setAwaitingRelease] = useState(false);
  const [eventsFailed, setEventsFailed] = useState(false);
  const eventsOnTick = awaitingRelease || eventsFailed;
  const eventsHeld = useHeldResult(
    base === null ? null : () => getLines(`${base}/events`, runEvent, eventsOnTick ? ON_TICK : {}),
    scope,
    eventsOnTick ? `${String(version)}#${String(tick)}` : String(version),
  );
  const eventsRead = eventsHeld.result;
  const events = { result: eventsRead };
  const awaiting =
    eventsRead?.ok === true &&
    planComponents(eventsRead.value) !== null &&
    releasedChoices(eventsRead.value) === null;
  if (awaiting !== awaitingRelease) setAwaitingRelease(awaiting);
  if (eventsHeld.failedAgain !== eventsFailed) setEventsFailed(eventsHeld.failedAgain);
  // One failed read keeps what the page holds; the page says so until a read works again.
  const refreshFailed = listingRead.failedAgain || viewsRead.failedAgain || eventsHeld.failedAgain;
  // Once the decided part reads as decided, show the next open part, or stay and say what the
  // run does next.
  if (advanceFrom !== null && views?.ok === true) {
    const from = views.value.find((v) => v.item.itemId === advanceFrom);
    if (from !== undefined && !from.open) {
      setAdvanceFrom(null);
      const next = nextOpenPart(views.value, from);
      if (next === undefined) setFocus("next");
      else {
        setMoved({ asked, to: next.item.itemId });
        setFocus("part");
      }
    }
  }
  // A part brought back after every part was decided on this page is shown, as the page said.
  if (focus === "next" && advanceFrom === null && views?.ok === true) {
    const back = views.value.find((v) => v.open && v.item.source === "parts");
    if (back !== undefined) {
      setMoved({ asked, to: back.item.itemId });
      setFocus("part");
    }
  }
  // The address is kept in step with the part shown, so a reload or a copy of it lands there.
  useEffect(() => {
    if (moved === null) return;
    const address = new URLSearchParams(query);
    address.set("item", moved.to);
    window.history.replaceState(null, "", hrefFor(AREA, SLUG, address));
    // Only when the page moves on by itself; the query it started from is in ``moved``.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moved]);
  const nextLine = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (focus === "next") nextLine.current?.focus();
  }, [focus]);
  const operator = pageOperator();
  const configValue = config?.ok === true ? config.value : undefined;
  const phase = phaseOfResult(status);
  const going = phase === "going";
  useEffect(() => {
    if (runs?.ok === true && runs.value.length === 0)
      setHeader({ title: "Queue", runState: "none" });
    else if (config?.ok === false || runs?.ok === false || listing?.ok === false)
      setHeader({ title: "Queue", runState: "unread" });
    else if (configValue !== undefined)
      setHeader({
        title: "Queue",
        source: runSource(configValue),
        gateMode: configValue.gateMode,
        osLayer: configValue.osLayer,
        inProgress: going,
        phase,
        standing: chosen.standing,
        ...(label === undefined ? {} : { run: label }),
      });
  }, [runs, config, configValue, going, phase, chosen.standing, label, setHeader, listing]);

  if (runs === null) return <LoadingState reading="the run list" />;
  if (!runs.ok)
    return (
      <ErrorState title="The run list could not be read" {...runs.refusal} route="/api/runs" />
    );
  if (chosen.chosen === undefined || base === null)
    return (
      <EmptyState title="Nothing to decide yet">
        A run's queue appears here once a run is recorded on this machine.
      </EmptyState>
    );
  const switcher = (
    <RunSwitcher
      runs={runs.value}
      chosen={chosen.chosen}
      labels={chosen.labels}
      area={AREA}
      slug={SLUG}
      allShown={chosen.allShown}
      showAll={chosen.showAll}
    />
  );
  // The items are read only once the listing is: a refused listing is shown as refused, and
  // never waits on items it will not ask for.
  if (config === null || listing === null || (listing.ok && views === null))
    return (
      <div className="pg-screen">
        {switcher}
        <LoadingState reading="the queue" />
      </div>
    );
  const refused = !config.ok
    ? { title: "The run's configuration could not be read", refusal: config.refusal }
    : !listing.ok
      ? { title: "The queue could not be read", refusal: listing.refusal }
      : views !== null && !views.ok
        ? { title: "An item of the queue could not be read", refusal: views.refusal }
        : null;
  if (refused !== null || !config.ok || !listing.ok || views === null || !views.ok)
    return (
      <div className="pg-screen">
        {switcher}
        <ErrorState
          title={refused?.title ?? "The queue could not be read"}
          {...(refused?.refusal ?? { status: 0, error: "", context: {} })}
          onRetry={() => {
            setVersion((v) => v + 1);
          }}
        />
      </div>
    );
  const names =
    events.result?.ok === true ? subtaskNames(events.result.value) : new Map<string, string>();
  // A run that asks which parts a person has: the plan's parts, and the release once all are decided.
  const components = events.result?.ok === true ? planComponents(events.result.value) : null;
  const released = events.result?.ok === true ? releasedChoices(events.result.value) : null;
  const listed = chosenItem(views.value, wanted);
  const item =
    fresh?.ok === true && fresh.value.item.itemId === listed?.item.itemId ? fresh.value : listed;
  const decided =
    item === undefined
      ? undefined
      : listing.value.decided.find((d) => d.itemId === item.item.itemId);
  const supersededBy =
    item === undefined || status?.ok !== true
      ? undefined
      : status.value.superseded[item.item.itemId];
  const send = (verb: Verb, note: string, position?: Position) =>
    item === undefined
      ? Promise.resolve<Result<never>>({
          ok: false,
          refusal: { status: 0, error: "no item is chosen", context: {} },
        })
      : postAction(
          `${base}/queue/decisions`,
          decisionRequest(item, verb, note, position),
          resolved,
        );
  const sendPart = (position: PartsPosition, stated: StatedPart | null) =>
    item === undefined
      ? Promise.resolve<Result<never>>({
          ok: false,
          refusal: { status: 0, error: "no item is chosen", context: {} },
        })
      : postAction(`${base}/queue/decisions`, partsRequest(item, position, stated), resolved);
  // The parts Find every remaining part decides: each open part asked for the first time, in the
  // queue's order, the one on screen by the view read when it was chosen.
  const remaining = views.value
    .filter((v) => v.open && v.item.source === "parts" && partRound(v.item.itemId)?.round === 1)
    .sort((a, b) => a.position - b.position)
    .map((v) => {
      const view = item !== undefined && item.item.itemId === v.item.itemId ? item : v;
      const label =
        componentOf(v.item.itemId, v.item.decisionRequired, components)?.label ?? v.item.itemId;
      return { view, label };
    });
  const findPart = (view: ItemView) =>
    postAction(`${base}/queue/decisions`, partsRequest(view, "find", null), resolved);
  return (
    <div className="pg-screen">
      {switcher}
      {foundAll !== null && (
        <div ref={foundLine} tabIndex={-1}>
          {foundAll.refusal === null ? (
            <p className="pg-queue-recorded pg-parts-found-all" role="status">
              {foundAllWords(foundAll.recorded, operator ?? "no one")}
            </p>
          ) : (
            <div className="pg-parts-refused pg-parts-found-all-refused" role="alert">
              <p className="pg-parts-refused-title">
                {foundAllStoppedWords(foundAll.recorded, foundAll.of)}
              </p>
              <p>{foundAll.refusal.error}</p>
              {Object.entries(foundAll.refusal.context).map(([key, said]) => (
                <p key={key} className="pg-parts-refused-reason">
                  {said}
                </p>
              ))}
              <p className="pg-panel-note">{PARTS_COPY.refusedReread}</p>
            </div>
          )}
        </div>
      )}
      {released !== null && (
        <p className="pg-parts-released" role="status">
          {releasedWords(released)}
        </p>
      )}
      {just !== null && (
        <p className="pg-queue-recorded pg-parts-screen-recorded" role="status">
          Recorded for the part "{just.label}":{" "}
          <span className="mono">{just.resolved.decision}</span> by{" "}
          <span className="mono">{just.resolved.resolvedBy}</span> at{" "}
          <span className="mono">{just.resolved.ts}</span>
        </p>
      )}
      {item !== undefined && !item.open && refusedOn?.itemId === item.item.itemId && (
        // The part's panel gave way to the decided view: its refusal stays on screen.
        <PartsRefusal refusal={refusedOn.refusal} />
      )}
      {refreshFailed && (
        <p className="pg-panel-note pg-queue-refresh-failed" role="status">
          {REFRESH_FAILED}
        </p>
      )}
      {released === null && components !== null && everyPartDecided(views.value) && (
        <p className="pg-parts-next" role="status" tabIndex={-1} ref={nextLine}>
          {PARTS_COPY.next}
        </p>
      )}
      <div className="pg-queue-layout">
        <ItemList
          views={views.value}
          chosen={item}
          query={query}
          names={names}
          onPick={() => {
            setMoved(null);
            setAdvanceFrom(null);
            setFocus(null);
          }}
        />
        {item === undefined ? (
          <EmptyState title="Nothing to decide">
            This run's queue is empty: no subtask was set aside for a person.
          </EmptyState>
        ) : (
          <QueueItem
            view={item}
            decided={decided}
            source={runSource(config.value)}
            subtaskName={names.get(item.item.subtaskId) ?? "The whole design"}
            supersededBy={supersededBy}
            phase={phase}
          >
            {item.item.source === "parts" ? (
              <>
                <PartsDecide
                  // Started again once the plan's line is read: its rows are the part's names. A
                  // read of the queue again keeps it, and what the person typed in it.
                  key={`${item.item.itemId}#${String(components !== null)}`}
                  view={item}
                  component={componentOf(item.item.itemId, item.item.decisionRequired, components)}
                  total={components === null ? null : components.length}
                  earlier={earlierDecision(item.item.itemId, listing.value.decided)}
                  raised={raisedBy(
                    item.item.itemId,
                    events.result?.ok === true ? events.result.value : null,
                  )}
                  runId={config.value.runId}
                  operator={operator}
                  holdsToken={actToken() !== null}
                  send={sendPart}
                  focusOnStart={focus === "part"}
                  onDecided={(written) => {
                    const component = componentOf(
                      item.item.itemId,
                      item.item.decisionRequired,
                      components,
                    );
                    setJust({ label: component?.label ?? item.item.itemId, resolved: written });
                    setFoundAll(null);
                    setRefusedOn(null);
                    setAdvanceFrom(item.item.itemId);
                    setVersion((v) => v + 1);
                  }}
                  onRefused={(refusal) => {
                    setRefusedOn({ itemId: item.item.itemId, refusal });
                    setVersion((v) => v + 1);
                  }}
                />
                <FindRemaining
                  parts={remaining}
                  runId={config.value.runId}
                  operator={operator}
                  holdsToken={actToken() !== null}
                  send={findPart}
                  onDone={(recorded, of, refusal) => {
                    setJust(null);
                    setRefusedOn(null);
                    setAdvanceFrom(null);
                    setFoundAll({ recorded, of, refusal });
                    setVersion((v) => v + 1);
                  }}
                />
              </>
            ) : (
              <Decide
                key={`${item.item.itemId}#${String(version)}`}
                view={item}
                runId={config.value.runId}
                operator={operator}
                holdsToken={actToken() !== null}
                send={send}
                onDecided={() => {
                  setVersion((v) => v + 1);
                }}
                supersededBy={supersededBy}
              />
            )}
          </QueueItem>
        )}
      </div>
    </div>
  );
}
