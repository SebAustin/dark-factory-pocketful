// Tiny DOM builder. Text always goes through textContent: notes and names are verbatim user input.
const SVG_NS = "http://www.w3.org/2000/svg";

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === false || value === null || value === undefined) continue;
    if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, String(value));
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function clear(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

const ICONS = {
  logo: "M4 7.5A2.5 2.5 0 0 1 6.5 5H19v3M4 7.5V17a2 2 0 0 0 2 2h13a1 1 0 0 0 1-1v-9a1 1 0 0 0-1-1H6.5M16 13.5h.01",
  wallet: "M4 7.5A2.5 2.5 0 0 1 6.5 5H19v3M4 7.5V17a2 2 0 0 0 2 2h13a1 1 0 0 0 1-1v-9a1 1 0 0 0-1-1H6.5M16 13.5h.01",
  requests: "M7 4h10a1 1 0 0 1 1 1v15l-3-2-3 2-3-2-3 2V5a1 1 0 0 1 1-1zM9 9h6M9 13h4",
  split: "M12 3v6m0 0-5 5v6m5-11 5 5v6M5 20h4M15 20h4",
  hold: "M7 11V8a5 5 0 0 1 10 0v3M6 11h12a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1z",
  lock: "M7 11V8a5 5 0 0 1 10 0v3M6 11h12a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1z",
  check: "M5 12.5l4.5 4.5L19 7.5",
  cross: "M6 6l12 12M18 6 6 18",
  clock: "M12 7v5l3 2M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17z",
  question: "M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 .9-1 1.7M12 17.5h.01M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17z",
  up: "M12 19V6m0 0-5 5m5-5 5 5",
  down: "M12 5v13m0 0-5-5m5 5 5-5",
  strike: "M5 12h14M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17z",
  info: "M12 11v5.5M12 7.5h.01M12 3.5a8.5 8.5 0 1 0 0 17 8.5 8.5 0 0 0 0-17z",
  undo: "M9 7 4.5 11.5 9 16M5 11.5h9a5 5 0 0 1 5 5v1",
};

export function icon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke", "currentColor");
  svg.setAttribute("stroke-width", "1.8");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  const path = document.createElementNS(SVG_NS, "path");
  path.setAttribute("d", ICONS[name] || ICONS.info);
  svg.append(path);
  return svg;
}

/** A labelled input. Returns {root, input}. The label is always visible. */
export function field({ id, label, hint, testid, type = "text", ...inputAttrs }) {
  const input = h("input", { class: "input", id, type, "data-testid": testid, ...inputAttrs });
  const root = h("div", { class: "field" }, h("label", { for: id, text: label }), input,
    hint ? h("span", { class: "hint", text: hint }) : null);
  return { root, input };
}

export function spinner() { return h("span", { class: "spinner", "aria-hidden": "true" }); }

/** Announce a message politely for screen readers and as a transient notice. */
export function announce(message, kind = "ok") {
  let live = document.getElementById("status");
  if (!live) {
    live = h("div", { id: "status", role: "status", "aria-live": "polite" });
    document.body.append(live);
  }
  clear(live);
  if (!message) return;
  live.append(h("div", { class: `notice notice--${kind}` }, icon(kind === "ok" ? "check" : "info"), h("div", { class: "notice__body", text: message })));
  clearTimeout(announce.timer);
  announce.timer = setTimeout(() => clear(live), 5000);
}
