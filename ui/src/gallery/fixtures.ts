/**
 * Fixture data for the component gallery, taken from the design's mockup. None of it is a
 * record: every source id here starts with "fixture-", and the gallery says so at its top.
 */
import type { CanvasEdge, CanvasNode } from "../design/components/graph/GraphCanvas";
import type { Part } from "../design/components/parts/PartRow";
import type { PlotSpec } from "../design/components/plot/Plot";

export const FIXTURE_SOURCE = { id: "fixture-run-0417", commit: "a3f91c2e5d" };

/** The mockup's design graph, with labels long enough to wrap in a card. */
export const GRAPH_NODES: readonly CanvasNode[] = [
  { id: "ctl.speed_loop", label: "Speed control loop", kind: "module", domain: "control" },
  {
    id: "fw.foc",
    label: "Motor-control firmware, field-oriented current loop at the encoder interrupt",
    kind: "module",
    domain: "firmware",
  },
  { id: "elec.encoder", label: "Absolute encoder", kind: "component", domain: "electrical" },
  {
    id: "elec.driver",
    label: "Motor driver sized for the peak phase current of the stalled motor",
    kind: "component",
    domain: "electrical",
  },
  { id: "elec.bus", label: "Supply bus", kind: "component", domain: "electrical" },
  { id: "elec.motor", label: "BLDC motor", kind: "component", domain: "electrical" },
  { id: "mech.gearbox", label: "Planetary gearbox", kind: "component", domain: "mechanical" },
  {
    id: "mech.housing.envelope_and_mounting_interface_to_the_frame",
    label: "Gearbox housing, its envelope and the mounting interface to the frame",
    kind: "component",
    domain: "mechanical",
  },
  { id: "mech.shaft", label: "Output shaft", kind: "component", domain: "mechanical" },
  {
    id: "req.trace",
    label: "Requirement tracing across every domain",
    kind: "requirement",
    domain: "cross",
  },
];

export const GRAPH_EDGES: readonly CanvasEdge[] = [
  { from: "ctl.speed_loop", to: "fw.foc" },
  { from: "elec.encoder", to: "fw.foc" },
  { from: "fw.foc", to: "elec.driver" },
  { from: "elec.bus", to: "elec.driver" },
  { from: "elec.driver", to: "elec.motor" },
  { from: "elec.motor", to: "mech.gearbox" },
  { from: "mech.gearbox", to: "mech.shaft" },
  { from: "mech.housing.envelope_and_mounting_interface_to_the_frame", to: "mech.gearbox" },
  { from: "req.trace", to: "ctl.speed_loop" },
];

/** The mockup's parts list. */
export const PARTS: readonly Part[] = [
  {
    name: "Motor driver",
    role: "elec.driver",
    domain: "electrical",
    choice: "have",
    status: "Specs 6 of 6 · gate checked: fail",
  },
  {
    name: "Gearbox housing",
    role: "mech.housing",
    domain: "mechanical",
    choice: "make",
    status: "2 constraints stated",
  },
  {
    name: "BLDC motor",
    role: "elec.motor",
    domain: "electrical",
    choice: "have",
    status: "Specs 7 of 7 · gate checked: pass",
  },
  {
    name: "Absolute encoder",
    role: "elec.encoder",
    domain: "electrical",
    choice: "find",
    status: "Not yet sized · Sizer agent",
  },
  {
    name: "Planetary gearbox",
    role: "mech.gearbox",
    domain: "mechanical",
    choice: "find",
    status: "3 candidates · Sizer agent, opus-5.5",
  },
  {
    name: "Microcontroller",
    role: "fw.mcu",
    domain: "firmware",
    choice: "find",
    status: "Not yet sized · Sizer agent",
  },
  {
    name: "Bus capacitor bank",
    role: "elec.bus",
    domain: "electrical",
    choice: "find",
    status: "Not yet sized · Sizer agent",
  },
  {
    name: "Output shaft",
    role: "mech.shaft",
    domain: "mechanical",
    choice: "make",
    status: "1 constraint stated",
  },
  {
    name: "Phase current sensor",
    role: "elec.isense",
    domain: "electrical",
    choice: "find",
    status: "Not yet sized · Sizer agent",
  },
];

export const STEP: PlotSpec = {
  title: "Step response of the speed loop",
  x: { label: "time", unit: "s", scale: "linear" },
  xValues: [0, 0.01, 0.02, 0.03, 0.04, 0.05],
  y: { label: "speed", unit: "rad/s", scale: "linear" },
  series: [
    { label: "recorded", unit: "rad/s", y: [0, 61.2, 94.8, 103.1, 100.6, 100.0] },
    { label: "what-if", unit: "rad/s", y: [0, 70.4, 104.9, 108.2, 101.3, 100.0], whatIf: true },
  ],
  source: FIXTURE_SOURCE,
};
