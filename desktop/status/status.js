// The shell's own page. Everything it shows comes from its address's fragment, put there by
// the shell as JSON; it is written as text, never as markup.
"use strict";

function render() {
  let state = { kind: "starting", title: "Starting the operator UI", lines: [] };
  try {
    if (location.hash.length > 1) state = JSON.parse(decodeURIComponent(location.hash.slice(1)));
  } catch {
    state = { kind: "problem", title: "The app sent this page something it could not read", lines: [] };
  }
  document.body.dataset.kind = state.kind;
  document.getElementById("title").textContent = state.title;
  const lines = document.getElementById("lines");
  lines.replaceChildren(
    ...(state.lines || []).map((text) => {
      const p = document.createElement("p");
      p.textContent = text;
      return p;
    }),
  );
  for (const id of ["command", "detail"]) {
    const el = document.getElementById(id);
    el.textContent = state[id] || "";
    el.hidden = !state[id];
  }
}

window.addEventListener("hashchange", render);
render();
