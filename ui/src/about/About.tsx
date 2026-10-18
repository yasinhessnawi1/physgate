/**
 * About physgate: what the operator UI is, and the licences of what it bundles. The texts are
 * part of the app's own code, so nothing is fetched and no file of another kind is served.
 */
import lucide from "../design/icons/LICENSE.txt?raw";
import instrumentSans from "../design/licences/instrument-sans-OFL.txt?raw";
import jetbrainsMono from "../design/licences/jetbrains-mono-OFL.txt?raw";
import tokens from "../design/tokens.json" with { type: "json" };
import "./about.css";

/** What the app bundles, under which licence, with the licence's text. */
export const BUNDLED = [
  {
    name: tokens.font.family.sans,
    what: "the interface typeface",
    licence: "SIL Open Font License 1.1",
    text: instrumentSans,
  },
  {
    name: tokens.font.family.mono,
    what: "the typeface of every number, id, hash and unit",
    licence: "SIL Open Font License 1.1",
    text: jetbrainsMono,
  },
  {
    name: "Lucide icons, version 0.460",
    what: "the interface icons",
    licence: "ISC License",
    text: lucide,
  },
] as const;

export default function About() {
  return (
    <div className="pg-about">
      <section className="pg-card pg-about-card" aria-labelledby="about-what">
        <h2 id="about-what" className="pg-about-title">
          The physgate operator
        </h2>
        <p>
          A local view of the runs physgate recorded: what was designed, what the gate checked, what
          the reviewers decided, and the decisions waiting for a person. It reads the records on
          this machine and makes no request to anywhere else.
        </p>
      </section>
      <section className="pg-card pg-about-card" aria-labelledby="about-licences">
        <h2 id="about-licences" className="pg-about-title">
          What this app bundles, and its licences
        </h2>
        {BUNDLED.map((item) => (
          <details key={item.name} className="pg-details pg-about-licence">
            <summary>
              {item.name}, {item.what}: {item.licence}
            </summary>
            <pre className="pg-about-text" tabIndex={0}>
              {item.text}
            </pre>
          </details>
        ))}
      </section>
    </div>
  );
}
