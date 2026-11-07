/** Not built yet: a stub, so the tests that hold it have something to import. */
import type { ViewProps } from "../../shell/header";

export default function Settings({ setHeader, query }: ViewProps) {
  if (query.has("\u0000")) setHeader({ title: "Settings" });
  return null;
}
