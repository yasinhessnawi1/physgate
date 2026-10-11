/**
 * The desktop app's opening: about seven seconds, in four beats.
 *   1. The product mark draws itself.
 *   2. Two quantities reach the gate: one passes, one is held.
 *   3. design · gate · review.
 *   4. The wordmark.
 * Colours are the operator UI's dark-theme tokens; type is the UI's own Plex.
 */
import { loadFont } from "@remotion/fonts";
import {
  AbsoluteFill,
  Easing,
  interpolate,
  Sequence,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";

export const INTRO_FPS = 30;
export const INTRO_FRAMES = 210;

const C = {
  bg: "#0E1217",
  surface: "#161B22",
  border: "#2C343F",
  text: "#E6EAF0",
  text2: "#B0B9C6",
  accent: "#7AA7FF",
  pass: "#4FC08D",
  passBg: "#10291F",
  fail: "#FF8A7A",
  failBg: "#34140F",
  markBg: "#DCE7FA",
  markText: "#0B2A55",
};

const SANS = "IBM Plex Sans";
const MONO = "IBM Plex Mono";

void Promise.all([
  loadFont({ family: SANS, url: staticFile("fonts/ibm-plex-sans-latin-400-normal.woff2"), weight: "400" }),
  loadFont({ family: SANS, url: staticFile("fonts/ibm-plex-sans-latin-600-normal.woff2"), weight: "600" }),
  loadFont({ family: MONO, url: staticFile("fonts/ibm-plex-mono-latin-500-normal.woff2"), weight: "500" }),
]);

const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
const ease = Easing.bezier(0.2, 0.7, 0.2, 1);

/** The shield-and-check mark, drawn by its stroke. */
const Mark = ({ size, draw }: { size: number; draw: number }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={C.markText}
       strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3l8 4v6c0 4-3.5 7-8 8-4.5-1-8-4-8-8V7z" pathLength={1}
          strokeDasharray={1} strokeDashoffset={1 - Math.min(1, draw * 1.4)} />
    <path d="M9 12l2 2 4-4" pathLength={1} strokeDasharray={1}
          strokeDashoffset={1 - Math.max(0, Math.min(1, (draw - 0.7) / 0.3))} />
  </svg>
);

const MarkTile = ({ scale, draw, size }: { scale: number; draw: number; size: number }) => (
  <div style={{
    width: size, height: size, borderRadius: size * 0.22, background: C.markBg,
    display: "flex", alignItems: "center", justifyContent: "center", transform: `scale(${scale})`,
  }}>
    <Mark size={size * 0.62} draw={draw} />
  </div>
);

/** Beat 1: the mark arrives and draws itself. */
const Opening = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const scale = spring({ frame, fps, config: { damping: 14, stiffness: 120 } });
  const draw = interpolate(frame, [6, 40], [0, 1], { ...clamp, easing: ease });
  const out = interpolate(frame, [44, 54], [1, 0], clamp);
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: out }}>
      <MarkTile scale={scale} draw={draw} size={220} />
    </AbsoluteFill>
  );
};

const Chip = ({ label, x, tone }: { label: string; x: number; tone: "plain" | "pass" | "fail" }) => {
  const colour = tone === "pass" ? C.pass : tone === "fail" ? C.fail : C.text;
  const bg = tone === "pass" ? C.passBg : tone === "fail" ? C.failBg : C.surface;
  return (
    <div style={{
      position: "absolute", left: x, top: 340, height: 120, padding: "0 40px", borderRadius: 18,
      display: "flex", alignItems: "center", background: bg, border: `3px solid ${tone === "plain" ? C.border : colour}`,
      fontFamily: MONO, fontWeight: 500, fontSize: 64, color: colour, whiteSpace: "nowrap",
      fontVariantNumeric: "tabular-nums",
    }}>
      {label}
    </div>
  );
};

/** Beat 2: a quantity with its unit passes the gate; one without a sane value is held. */
const Gate = () => {
  const frame = useCurrentFrame();
  const fadeIn = interpolate(frame, [0, 8], [0, 1], clamp);
  const fadeOut = interpolate(frame, [62, 72], [1, 0], clamp);
  const gateX = 640;
  // The first quantity travels through the gate and turns green as it crosses.
  const firstX = interpolate(frame, [4, 34], [70, 860], { ...clamp, easing: ease });
  const firstTone = frame >= 22 ? "pass" : "plain";
  // The second arrives, is held at the gate, and is marked.
  const secondX = interpolate(frame, [30, 50], [70, gateX - 370], { ...clamp, easing: ease });
  const held = frame >= 50;
  const shake = held ? Math.sin((frame - 50) * 1.6) * interpolate(frame, [50, 60], [10, 0], clamp) : 0;
  const barColour = held ? C.fail : frame >= 22 && frame < 40 ? C.pass : C.text2;
  return (
    <AbsoluteFill style={{ opacity: fadeIn * fadeOut }}>
      <div style={{ position: "absolute", left: gateX - 4, top: 250, width: 8, height: 300,
                    borderRadius: 4, background: barColour }} />
      <div style={{ position: "absolute", left: gateX - 120, top: 580, width: 240, textAlign: "center",
                    fontFamily: SANS, fontWeight: 600, fontSize: 52, color: barColour }}>
        gate
      </div>
      <Chip label="2.4 V" x={firstX} tone={firstTone} />
      {frame >= 30 ? <Chip label="−0.8 kg" x={secondX + shake} tone={held ? "fail" : "plain"} /> : null}
    </AbsoluteFill>
  );
};

/** Beat 3: the three words, one after another. */
const Words = () => {
  const frame = useCurrentFrame();
  const words = ["design", "gate", "review"];
  const out = interpolate(frame, [44, 52], [1, 0], clamp);
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", opacity: out }}>
      <div style={{ display: "flex", gap: 36, fontFamily: SANS, fontWeight: 600, fontSize: 104, color: C.text }}>
        {words.map((word, i) => {
          const start = i * 10;
          const shown = interpolate(frame, [start, start + 10], [0, 1], { ...clamp, easing: ease });
          return (
            <span key={word} style={{ opacity: shown, transform: `translateY(${(1 - shown) * 30}px)`,
                                      color: word === "gate" ? C.accent : C.text }}>
              {i > 0 ? <span style={{ color: C.text2, marginRight: 36 }}>·</span> : null}
              {word}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

/** Beat 4: the wordmark, held to the end. */
const Wordmark = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const scale = spring({ frame, fps, config: { damping: 16, stiffness: 140 } });
  const words = interpolate(frame, [6, 18], [0, 1], { ...clamp, easing: ease });
  return (
    <AbsoluteFill style={{ alignItems: "center", justifyContent: "center" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 44 }}>
        <MarkTile scale={scale} draw={1} size={170} />
        <div style={{ opacity: words, transform: `translateX(${(1 - words) * -24}px)` }}>
          <div style={{ fontFamily: SANS, fontWeight: 600, fontSize: 120, color: C.text, lineHeight: 1 }}>physgate</div>
          <div style={{ fontFamily: SANS, fontWeight: 400, fontSize: 52, color: C.text2, marginTop: 14 }}>Operator</div>
        </div>
      </div>
    </AbsoluteFill>
  );
};

export const Intro = () => (
  <AbsoluteFill style={{ background: C.bg }}>
    <Sequence durationInFrames={56}><Opening /></Sequence>
    <Sequence from={54} durationInFrames={74}><Gate /></Sequence>
    <Sequence from={126} durationInFrames={54}><Words /></Sequence>
    <Sequence from={176}><Wordmark /></Sequence>
  </AbsoluteFill>
);
