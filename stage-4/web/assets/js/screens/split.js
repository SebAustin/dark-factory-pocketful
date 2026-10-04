// `/split` — split a bill; the preview is computed here by the same §9 rule the server uses.
import { h, field, icon } from "../dom.js";
import { currentUser } from "../session.js";
import { formatAmount, splitShares } from "../money.js";
import { amountFrom, handleValue } from "../forms/panels.js";
import { writeForm } from "../forms/writeform.js";

/** Split on commas, trim each, keep order. `empty` is true when any segment is blank ("ada,,bob", trailing comma). */
export function parseHandles(text) {
  const raw = String(text ?? "");
  if (!raw.trim()) return { list: [], empty: false };
  const list = raw.split(",").map(handleValue);
  return { list, empty: list.some((handle) => !handle) };
}

export async function splitScreen({ go }) {
  const me = () => currentUser();
  const m = me();
  const amount = field({ id: "split-amount", label: `Total amount (${m.currency})`, testid: "split-amount", inputmode: "decimal", autocomplete: "off", placeholder: "30.00" });
  const handles = field({ id: "split-handles", label: "Who's splitting", testid: "split-handles", autocomplete: "off", autocapitalize: "none", spellcheck: "false",
    placeholder: "ada, bob, cy", hint: "Handles separated by commas, in order. Include yourself if you share the cost." });
  const note = field({ id: "split-note", label: "Note (optional)", testid: "split-note", autocomplete: "off" });
  const preview = h("div", { class: "split-preview", "data-testid": "split-preview", "aria-live": "polite" });
  const button = h("button", { class: "btn btn--block", type: "submit", "data-testid": "split-submit" }, "Split it");
  const form = h("form", { class: "form-stack", novalidate: true, "aria-labelledby": "split-title" }, amount.root, handles.root, note.root, preview, button);

  let lastShares = [];
  const renderPreview = () => {
    const now = me();
    const parsed = amountFrom(amount.input.value, now);
    const parsedHandles = parseHandles(handles.input.value);
    const list = [...new Set(parsedHandles.list)];
    preview.replaceChildren();
    lastShares = [];
    if (parsedHandles.empty) {
      preview.append(h("p", { class: "split-preview__hint", text: "There's an empty entry between commas. Remove it to see each share." }));
      return;
    }
    if (parsed.error || !list.length || parsed.minor < 1) {
      preview.append(h("p", { class: "split-preview__hint", text: "Enter an amount and at least one handle to see each share." }));
      return;
    }
    const shares = splitShares(BigInt(parsed.minor), list.length);
    lastShares = list.map((handle, i) => ({ handle, amount: Number(shares[i]) }));
    preview.append(h("p", { class: "eyebrow", text: "Each share" }),
      h("ul", { class: "split-shares" }, lastShares.map((s) => h("li", { class: "split-share" },
        h("span", { class: "split-share__who", title: s.handle, text: s.handle }),
        h("span", { class: "num", "data-testid": `split-share-${s.handle}`, text: formatAmount(s.amount, now.minor_units, now.currency) })))));
  };
  form.addEventListener("input", renderPreview);
  renderPreview();

  writeForm({ form, button, label: "Split it", busyLabel: "Splitting…", path: "/splits",
    ids: { error: "split-error", uncertain: "split-uncertain", success: "split-success", already: "split-already" },
    alreadyText: "Already split. Change a field to split again.",
    build: () => {
      const now = me();
      const parsed = amountFrom(amount.input.value, now);
      if (parsed.error) return { error: parsed.error };
      const { list, empty } = parseHandles(handles.input.value);
      if (!list.length) return { error: "Enter at least one handle." };
      if (empty) return { error: "There's an empty entry between commas. Remove the extra comma." };
      return { body: { amount: parsed.minor, participant_handles: list, note: note.input.value } };
    },
    successText: (r) => {
      const n = r.body.requests.length;
      const differs = JSON.stringify(r.body.shares.map((s) => s.amount)) !== JSON.stringify(lastShares.map((s) => s.amount));
      return `${n === 0 ? "Recorded. No one else was asked." : `Asked ${n} ${n === 1 ? "person" : "people"} for their share.`}${differs ? " The shares were adjusted by the server." : ""}`;
    } });

  return h("div", { class: "page page--narrow" },
    h("h1", { id: "split-title", class: "page-title", text: "Split a bill" }),
    h("p", { class: "placeholder", text: "You've already paid. Ask everyone else for their share." }),
    h("div", { class: "panel" }, form));
}
