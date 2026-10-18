/**
 * The component gallery: every component of the design system in every state, on fixture data.
 * It sits at `#/gallery`, outside the navigation, and the browser tests read it. Nothing on it is
 * a record and nothing on it writes.
 */
import type { ReactNode } from "react";

import { Button } from "../design/components/actions/Button";
import { Kbd } from "../design/components/actions/Kbd";
import { Segmented } from "../design/components/actions/Segmented";
import { ActorBadge } from "../design/components/actor/ActorBadge";
import { Avatar } from "../design/components/actor/Avatar";
import { ChangeCard } from "../design/components/collaborator/ChangeCard";
import { ChatMessage } from "../design/components/collaborator/ChatMessage";
import { DOMAIN_KINDS, DomainChip } from "../design/components/data/DomainChip";
import { Figure } from "../design/components/data/Figure";
import { Id } from "../design/components/data/Id";
import { Quantity } from "../design/components/data/Quantity";
import { SourceChip } from "../design/components/data/SourceChip";
import { GraphCanvas } from "../design/components/graph/GraphCanvas";
import { GraphNode } from "../design/components/graph/GraphNode";
import { Term } from "../design/components/help/Term";
import { GLOSSARY, type TermKey } from "../design/components/help/glossary";
import { DataTable } from "../design/components/layout/DataTable";
import { Inspector, InspectorSection } from "../design/components/layout/Inspector";
import { ScrollTable } from "../design/components/layout/ScrollTable";
import { partColumns, PartRow } from "../design/components/parts/PartRow";
import { ProvenanceTag } from "../design/components/parts/ProvenanceTag";
import { Plot, PlotTable } from "../design/components/plot/Plot";
import { PlotFrame } from "../design/components/plot/PlotFrame";
import { InProgressBadge } from "../design/components/status/InProgressBadge";
import { ResearchIndicator } from "../design/components/status/ResearchIndicator";
import { StateBanner } from "../design/components/status/StateBanner";
import { EmptyState, ErrorState, LoadingState } from "../design/components/status/States";
import { STATUS_KINDS, type StatusKind, StatusTag } from "../design/components/status/StatusTag";
import { WhatIfMarker } from "../design/components/status/WhatIfMarker";
import { OsLayerBadge } from "../design/components/system/OsLayerBadge";
import { TimelineRow } from "../design/components/timeline/TimelineRow";
import { GateModeBadge, GateOutcome } from "../design/components/verdict/GateMode";
import { Tally } from "../design/components/verdict/Tally";
import { VerdictBadge } from "../design/components/verdict/VerdictBadge";
import { InspectorPortal } from "../shell/inspector";
import { FIXTURE_SOURCE, GRAPH_EDGES, GRAPH_NODES, PARTS, STEP } from "./fixtures";
import "./gallery.css";

const NOTHING = "Nothing: this is the component gallery, and no record is written.";
const NO_ACTION = () => undefined;

function Group({
  id,
  title,
  children,
}: {
  readonly id: string;
  readonly title: string;
  readonly children: ReactNode;
}) {
  return (
    <section className="pg-gallery-group" aria-labelledby={`gallery-${id}`} data-gallery={id}>
      <h2 className="pg-gallery-title" id={`gallery-${id}`}>
        {title}
      </h2>
      {children}
    </section>
  );
}

function Row({ label, children }: { readonly label: string; readonly children: ReactNode }) {
  return (
    <div className="pg-gallery-row">
      <span className="pg-gallery-label">{label}</span>
      <div className="pg-gallery-items">{children}</div>
    </div>
  );
}

export default function Gallery() {
  return (
    <div className="pg-gallery">
      <StateBanner kind="queued" title="Component gallery">
        Fixture data from the design's mockup, not a record. Nothing here is written anywhere.
      </StateBanner>

      <InspectorPortal>
        <Inspector
          label="Part inspector"
          crumbs={["This run", "Motor driver"]}
          title="Motor driver"
          badges={<DomainChip domain="electrical" />}
        >
          <InspectorSection label="Quantities">
            <Figure value="14.25" unit="A" source={FIXTURE_SOURCE} verdict="fail" />
          </InspectorSection>
          <InspectorSection label="Key">
            <Id value="elec.driver" />
          </InspectorSection>
        </Inspector>
      </InspectorPortal>

      <Group id="data" title="Data: quantities, sources, figures, domains, ids">
        <Row label="Quantity">
          <Quantity value={0.625} unit="rad" />
          <Quantity value={2.36} unit="1" />
          <Quantity value="14.790000" unit="USD" />
          <Quantity value="3.20" unit="USD" partial />
          <Quantity value={24} unit="V" size="lg" />
          <Quantity value="10.70" unit="A" whatIf />
          <Quantity value={1000} unit="Hz" />
        </Row>
        <Row label="Source chip">
          <SourceChip {...FIXTURE_SOURCE} />
          <SourceChip {...FIXTURE_SOURCE} compact />
          <SourceChip id="fixture-run-0418" commit={null} />
          <SourceChip id={null} commit={null} />
        </Row>
        <Row label="Figure">
          <Figure value="14.25" unit="A" source={FIXTURE_SOURCE} verdict="fail" />
          <Figure value="0.042" unit="N·m/A" source={FIXTURE_SOURCE} verdict="pass" />
          <Figure value="3.20" unit="USD" source={FIXTURE_SOURCE} partial />
          <Figure value="10.70" unit="A" whatIf={{ draft: "fixture-draft-12" }} />
          <Figure value="47" unit="°" source={null} />
        </Row>
        <Row label="Domain">
          {DOMAIN_KINDS.map((d) => (
            <DomainChip key={d} domain={d} />
          ))}
        </Row>
        <Row label="Id">
          <Id value="firmware.main_loop.sample_rate" />
          <Id value="a3f91c2" copy={false} />
        </Row>
      </Group>

      <Group id="verdict" title="Verdicts and gate modes">
        <Row label="Verdict">
          <VerdictBadge verdict="pass" />
          <VerdictBadge verdict="fail" />
          <VerdictBadge verdict="warn" />
          <VerdictBadge verdict="unchecked" />
          <VerdictBadge verdict="pass" count={11} />
        </Row>
        <Row label="Tally">
          <Tally pass={11} fail={1} warn={2} unchecked={3} />
        </Row>
        <Row label="Tally, observe">
          <Tally pass={11} fail={1} warn={2} unchecked={3} observed />
        </Row>
        <Row label="Tally, partial">
          <Tally pass={4} fail={0} warn={1} unchecked={6} partial />
        </Row>
        <Row label="Tally, compact">
          <Tally pass={11} fail={1} warn={2} unchecked={3} compact />
          <Tally pass={11} fail={1} warn={2} unchecked={3} compact observed />
        </Row>
        <Row label="Gate mode">
          <GateModeBadge mode="on" />
          <GateModeBadge mode="observe" />
          <GateModeBadge mode="off" />
        </Row>
        <Row label="Gate outcome">
          {(["pass", "fail", "warn", "unchecked"] as const).map((o) => (
            <GateOutcome key={`on-${o}`} mode="on" outcome={o} />
          ))}
          {(["pass", "fail", "warn", "unchecked"] as const).map((o) => (
            <GateOutcome key={`observe-${o}`} mode="observe" outcome={o} />
          ))}
        </Row>
      </Group>

      <Group id="status" title="States">
        <Row label="Markers">
          <WhatIfMarker />
          <InProgressBadge />
          <ResearchIndicator session="fixture-study-07" />
          <ResearchIndicator recording={false} />
        </Row>
        <Row label="Not verdicts">
          {(Object.keys(STATUS_KINDS) as StatusKind[]).map((s) => (
            <StatusTag key={s} status={s} />
          ))}
          <StatusTag status="frozen" strong />
        </Row>
        <div className="pg-gallery-stack">
          <StateBanner kind="whatif" title="What-if overlay">
            The draft's values are shown dashed; none carries a verdict.
          </StateBanner>
          <StateBanner kind="observe" title="Observe mode">
            The gate checked this run but was not allowed to stop it.
          </StateBanner>
          <StateBanner kind="progress" title="In progress">
            Figures are partial; totals say so far.
          </StateBanner>
          <StateBanner kind="queued" title="Queued">
            Lands at the next safe point.
          </StateBanner>
          <StateBanner kind="research" title="Recording">
            A consented study session.
          </StateBanner>
          <StateBanner kind="error" title="Refused">
            The record could not be read.
          </StateBanner>
          <EmptyState title="No runs yet">Runs appear here once one has been recorded.</EmptyState>
          <LoadingState reading="fixture-run-0417" />
          <ErrorState
            title="The task ledger could not be shown."
            error="the ledger disagrees with the run-event log"
            status={422}
            context={{ route: "/api/runs/0/fixture-run-0417/ledger" }}
          />
        </div>
      </Group>

      <Group id="actor" title="Actors">
        <Row label="Actor">
          <ActorBadge kind="deterministic" name="Orchestrator" />
          <ActorBadge kind="agent" name="Sizer agent" role="implementer" model="opus-5.5" />
          <ActorBadge kind="collaborator" quote="Try the bus at 32 V instead." />
          <ActorBadge kind="human" name="Yasin K." />
        </Row>
        <Row label="Small">
          <ActorBadge kind="deterministic" name="Gate" size="sm" />
          <ActorBadge kind="agent" name="Reviewer" role="reviewer" model="sonnet-5" size="sm" />
        </Row>
        <Row label="Avatar">
          <Avatar name="Yasin K." />
          <Avatar name="Yasin K." size="md" />
        </Row>
      </Group>

      <Group id="actions" title="Actions">
        <Row label="Browse">
          <Button>Open the run</Button>
          <Button icon="download">With an icon</Button>
          <Button variant="ghost" icon="settings" title="Settings" />
          <Button size="sm">Small</Button>
          <Button disabled>Disabled</Button>
        </Row>
        <Row label="Act">
          <Button
            variant="act"
            label="Approve sizing…"
            confirm={{
              title: "Approve the motor-driver sizing?",
              summary: "This is the gallery: confirming writes nothing.",
              writes: NOTHING,
              check: "Nothing is checked: the gallery has no record.",
              outcome: "Nothing follows.",
              recordedAs: "Gallery (no record)",
              confirmLabel: "Approve",
              onConfirm: NO_ACTION,
            }}
          />
          <Button
            variant="reject"
            label="Reject…"
            confirm={{
              title: "Reject the motor-driver sizing?",
              writes: (reason) => `${NOTHING} Reason typed: ${reason}`,
              recordedAs: "Gallery (no record)",
              confirmLabel: "Reject",
              needsReason: true,
              onConfirm: NO_ACTION,
            }}
          />
          <Button
            variant="act"
            label="Apply…"
            disabledBecause="No route records this yet."
            confirm={{
              title: "Apply?",
              writes: NOTHING,
              recordedAs: "Gallery (no record)",
              confirmLabel: "Apply",
              onConfirm: NO_ACTION,
            }}
          />
        </Row>
        <Row label="Segmented">
          <Segmented
            label="Fixture choice"
            value="graph"
            onChange={NO_ACTION}
            options={[
              { value: "graph", label: "Graph", icon: "network" },
              { value: "table", label: "Table", icon: "table" },
            ]}
          />
        </Row>
        <Row label="Key">
          <Kbd>⌘K</Kbd>
          <Kbd>⌘J</Kbd>
          <Kbd>g</Kbd>
        </Row>
      </Group>

      <Group id="layout" title="Tables and inspector">
        <DataTable
          label="Fixture quantities"
          rowKey={(r) => r.name}
          filterText={(r) => r.name}
          columns={[
            { key: "name", label: "Quantity", sortValue: (r) => r.name, render: (r) => r.name },
            {
              key: "value",
              label: "Value",
              numeric: true,
              sortValue: (r) => Number(r.value),
              render: (r) => <Quantity value={r.value} unit={r.unit} />,
            },
            { key: "key", label: "Key", mono: true, render: (r) => r.key },
          ]}
          rows={[
            { name: "Peak phase current", value: "14.25", unit: "A", key: "elec.driver.i_peak" },
            { name: "Bus voltage", value: "24", unit: "V", key: "elec.bus.v_bus" },
            { name: "Torque constant", value: "0.042", unit: "N·m/A", key: "elec.motor.k_t" },
          ]}
          empty={<EmptyState title="No quantity matches the filter" />}
        />
        <ScrollTable label="A wide fixture table">
          <table className="pg-table">
            <thead>
              <tr>
                <th scope="col">Column</th>
                <th scope="col">Value</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Gear ratio</td>
                <td className="pg-num">
                  <Quantity value={6} unit="1" />
                </td>
              </tr>
            </tbody>
          </table>
        </ScrollTable>
      </Group>

      <Group id="parts" title="Parts">
        <DataTable label="Parts" rowKey={(p) => p.role} columns={partColumns()} rows={PARTS} />
        <PartRow
          part={PARTS[0] ?? { name: "", role: "", domain: "cross", choice: "find", status: "" }}
        />
        <Row label="Provenance">
          <ProvenanceTag kind="have" />
          <ProvenanceTag kind="make" />
          <ProvenanceTag kind="find" />
        </Row>
      </Group>

      <Group id="timeline" title="Timeline">
        <div className="pg-card">
          <TimelineRow
            time="13:58"
            actor={{ kind: "deterministic", name: "Orchestrator" }}
            what="Run started"
            meta="gate on · 9 subtasks"
          />
          <TimelineRow
            depth={1}
            time="14:03"
            actor={{ kind: "agent", name: "Sizer agent", role: "implementer", model: "opus-5.5" }}
            what="Attempt 1: proposed the driver at 24 V"
            end={<VerdictBadge verdict="fail" />}
          />
          <TimelineRow
            depth={2}
            time="14:12"
            actor={{ kind: "collaborator", quote: "Try the bus at 32 V instead." }}
            what="Proposed raising the bus voltage"
          />
          <TimelineRow
            depth={1}
            time="14:15"
            actor={{ kind: "human", name: "Yasin K." }}
            what="Approved the sizing"
          />
        </div>
      </Group>

      <Group id="graph" title="Graph">
        <Row label="Node">
          <GraphNode
            id="elec.driver"
            label="Motor driver sized for the peak phase current of the stalled motor"
            domain="electrical"
            summary="component · 2 quantities"
            quantities={[{ name: "Peak phase current", value: "14.25", unit: "A" }]}
            verdict="fail"
            provenance="have"
          />
          <GraphNode
            id="elec.bus"
            label="Supply bus"
            domain="electrical"
            quantities={[{ name: "Bus voltage", value: "32", unit: "V" }]}
            whatIf
          />
          <GraphNode
            id="mech.housing"
            label="Gearbox housing"
            domain="mechanical"
            provenance="make"
            verdict="unchecked"
            selected
          />
        </Row>
        <GraphCanvas nodes={GRAPH_NODES} edges={GRAPH_EDGES} />
      </Group>

      <Group id="collaborator" title="Collaborator (library only)">
        <div className="pg-gallery-cards">
          {(["proposed", "queued", "applied", "declined", "refused"] as const).map((state) => (
            <ChangeCard
              key={state}
              state={state}
              id="fixture-change-14"
              what="Raise the bus voltage"
              label="Bus voltage"
              target="elec.bus.v_bus"
              from={<Quantity value={24} unit="V" />}
              to={<Quantity value={32} unit="V" />}
              why="The driver's peak current falls below its rating at 32 V."
              quote="Try the bus at 32 V instead."
              quotedBy="Yasin K. · 14:12"
              reason="Refused: the collaborator cannot skip a review."
            />
          ))}
          <ChatMessage from="collaborator" author="Collaborator" question time="14:02">
            Do you already have a motor driver?
          </ChatMessage>
          <ChatMessage
            from="collaborator"
            author="Collaborator"
            time="14:03"
            attachment="fixture check · fixture-run-0417"
          >
            The peak current check failed at 14.25 A.
          </ChatMessage>
          <ChatMessage from="human" author="Yasin K." time="14:04">
            Yes, a DRV8316 evaluation board.
          </ChatMessage>
        </div>
      </Group>

      <Group id="plot" title="Plot">
        <PlotFrame
          title={STEP.title}
          subtitle="Recorded and what-if, 0–50 ms"
          summary="The recorded response settles at 100 rad/s by 50 ms with a 3 % overshoot; the what-if draft overshoots by 8 %."
          source={STEP.source}
          whatIf
          plot={<Plot spec={STEP} />}
          data={<PlotTable spec={STEP} />}
        />
      </Group>

      <Group id="system" title="OS layer">
        <Row label="OS layer">
          <OsLayerBadge layer={{ state: "present", mechanism: "seatbelt" }} />
          <OsLayerBadge
            layer={{
              state: "absent",
              reason: "bubblewrap is not installed",
              noOsProtection: false,
            }}
          />
          <OsLayerBadge
            layer={{ state: "absent", reason: "native Windows", noOsProtection: true }}
          />
          <OsLayerBadge layer={null} />
        </Row>
      </Group>

      <Group id="help" title="Terms">
        <Row label="Term">
          {(Object.keys(GLOSSARY) as TermKey[]).map((key) => (
            <Term key={key} term={key} />
          ))}
        </Row>
      </Group>
    </div>
  );
}
