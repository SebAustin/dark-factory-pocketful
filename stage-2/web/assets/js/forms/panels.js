// The three money forms on the wallet: send, request, reserve. Each is a writeForm with its own test ids.
import { h, field } from "../dom.js";
import { parseAmount, formatAmount, formatPlain, MAX_AMOUNT } from "../money.js";
import { writeForm } from "./writeform.js";

export function handleValue(raw) { return String(raw ?? "").trim().replace(/^@/, ""); }

/** Parse an amount input for `me`; returns {minor:number} or {error: text}. */
export function amountFrom(text, me) {
  const parsed = parseAmount(text, me.minor_units);
  if (parsed.error === "not_a_number") return { error: me.minor_units === 0 ? "Enter a whole amount like 15." : "Enter an amount like 15.00." };
  if (parsed.error === "too_many_decimals") return { error: me.minor_units === 0 ? `${me.currency} has no decimals.` : `Use at most ${me.minor_units} decimal places.` };
  if (parsed.minor > MAX_AMOUNT) return { error: "That amount is too large." };
  return { minor: Number(parsed.minor) };
}

function visibilitySelect(id, testid) {
  const select = h("select", { class: "select", id, "data-testid": testid },
    h("option", { value: "public", text: "Public: anyone can see it in the feed" }),
    h("option", { value: "private", text: "Private: only you and the other person" }));
  return { root: h("div", { class: "field" }, h("label", { for: id, text: "Who can see this" }), select), select };
}

function panel({ kind, title, lede, primary, fields, submit }) {
  const button = h("button", { class: `btn ${primary ? "" : "btn--quiet"} btn--block`, type: "submit", "data-testid": submit.testid }, submit.label);
  const form = h("form", { class: "form-stack", novalidate: true, "aria-labelledby": `${kind}-title` }, ...fields.map((f) => f.root), button);
  const root = h("section", { class: `panel money-panel ${primary ? "money-panel--primary" : ""}` },
    h("h2", { id: `${kind}-title`, text: title }), h("p", { class: "money-panel__lede", text: lede }), form);
  return { root, form, button };
}

function common(kind, me, { visibility }) {
  const id = (n) => `${kind}-${n}`;
  const handle = field({ id: id("handle"), label: kind === "request" ? "Ask whom" : "Send to", testid: `${kind === "authorize" ? "authorize" : kind}-handle`,
    autocomplete: "off", autocapitalize: "none", spellcheck: "false", placeholder: "handle" , hint: "Their handle, without the @." });
  const amount = field({ id: id("amount"), label: `Amount (${me.currency})`, testid: `${kind === "authorize" ? "authorize" : kind}-amount`,
    inputmode: "decimal", autocomplete: "off", placeholder: formatPlain(0, me.minor_units) });
  const note = field({ id: id("note"), label: "Note (optional)", testid: `${kind === "authorize" ? "authorize" : kind}-note`, autocomplete: "off" });
  const vis = visibility ? visibilitySelect(id("visibility"), `${kind === "authorize" ? "authorize" : kind}-visibility`) : null;
  return { handle, amount, note, vis };
}

/** Build one of the three panels. `me()` returns the latest /me; `refresh()` reloads wallet data. */
export function buildPanels({ me, refresh }) {
  const meNow = () => me();
  const send = (() => {
    const m = meNow();
    const f = common("pay", m, { visibility: true });
    const p = panel({ kind: "pay", title: "Send money", lede: "Money moves right away.", primary: true,
      fields: [f.handle, f.amount, f.note, f.vis], submit: { testid: "pay-submit", label: "Send money" } });
    writeForm({ form: p.form, button: p.button, label: "Send money", busyLabel: "Sending…", path: "/payments",
      ids: { error: "pay-error", uncertain: "pay-uncertain", success: "pay-success", already: "pay-already" },
      alreadyText: "Already sent. Change a field to send another payment.",
      uncertainText: "We didn't get an answer. Your payment may or may not have gone through. Retrying is safe: it can't pay twice.",
      retryLabel: "Retry payment",
      build: () => {
        const now = meNow();
        const amount = amountFrom(f.amount.input.value, now);
        if (amount.error) return { error: amount.error };
        const handle = handleValue(f.handle.input.value);
        if (!handle) return { error: "Enter who to send to." };
        return { body: { to_handle: handle, amount: amount.minor, note: f.note.input.value, visibility: f.vis.select.value } };
      },
      successText: (r) => `Sent ${formatAmount(r.body.amount, meNow().minor_units, meNow().currency)} to ${r.body.to_handle}.`,
      onSuccess: refresh, onRefused: refresh });
    return p;
  })();

  const request = (() => {
    const m = meNow();
    const f = common("request", m, { visibility: false });
    const p = panel({ kind: "request", title: "Request money", lede: "Ask someone to pay you. They decide whether and when.", primary: false,
      fields: [f.handle, f.amount, f.note], submit: { testid: "request-submit", label: "Request money" } });
    writeForm({ form: p.form, button: p.button, label: "Request money", busyLabel: "Requesting…", path: "/requests",
      ids: { error: "request-error", uncertain: "request-uncertain", success: "request-success", already: "request-already" },
      alreadyText: "Already requested. Change a field to ask again.",
      build: () => {
        const now = meNow();
        const amount = amountFrom(f.amount.input.value, now);
        if (amount.error) return { error: amount.error };
        const handle = handleValue(f.handle.input.value);
        if (!handle) return { error: "Enter who to ask." };
        return { body: { payer_handle: handle, amount: amount.minor, note: f.note.input.value } };
      },
      successText: (r) => `Asked ${r.body.payer_handle} for ${formatAmount(r.body.amount, meNow().minor_units, meNow().currency)}.`,
      onSuccess: refresh, onRefused: async () => {} });
    return p;
  })();

  const authorize = buildAuthorizePanel({ me, refresh });
  return { send, request, authorize };
}

export function buildAuthorizePanel({ me, refresh }) {
  const meNow = () => me();
  const m = meNow();
  const f = common("authorize", m, { visibility: true });
  const p = panel({ kind: "authorize", title: "Reserve money", lede: "Hold funds for someone to collect later, in one or more captures.", primary: false,
    fields: [f.handle, f.amount, f.note, f.vis], submit: { testid: "authorize-submit", label: "Reserve money" } });
  writeForm({ form: p.form, button: p.button, label: "Reserve money", busyLabel: "Reserving…", path: "/authorizations",
    ids: { error: "authorize-error", uncertain: "authorize-uncertain", success: "authorize-success", already: "authorize-already" },
    alreadyText: "Already reserved. Change a field to reserve again.",
    build: () => {
      const now = meNow();
      const amount = amountFrom(f.amount.input.value, now);
      if (amount.error) return { error: amount.error };
      const handle = handleValue(f.handle.input.value);
      if (!handle) return { error: "Enter who may collect." };
      return { body: { to_handle: handle, amount: amount.minor, note: f.note.input.value, visibility: f.vis.select.value } };
    },
    successText: (r) => `Reserved ${formatAmount(r.body.amount, meNow().minor_units, meNow().currency)} for ${r.body.to_handle}.`,
    onSuccess: refresh, onRefused: refresh });
  return p;
}
