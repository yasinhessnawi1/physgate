import { Composition } from "remotion";
import { Intro, INTRO_FRAMES, INTRO_FPS } from "./Intro";

export const Root = () => (
  <Composition
    id="Intro"
    component={Intro}
    durationInFrames={INTRO_FRAMES}
    fps={INTRO_FPS}
    width={1280}
    height={800}
  />
);
