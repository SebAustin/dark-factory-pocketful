// `/authorizations` — reserve money, and capture or void holds.
import { h, clear, icon, spinner, announce } from "../dom.js";
import { api } from "../api.js";
import { authToken, clearSession, setMe, currentUser } from "../session.js";
import { formatAmount, formatPlain } from "../money.js";
import { latestOnly } from "../refresh.js";
import { Attempt } from "../idem.js";
import { writeForm, refusalText } from "../forms/writeform.js";
import { amountFrom, buildAuthorizePanel } from "../forms/panels.js";
import { whenText } from "./wallet.js";

const STATUS = {
  open: ["badge--open", "hold", "Open"],
  captured: ["badge--ok", "check", "Captured"],
  voided: ["badge--neutral", "strike", "Voided"],
  expired: ["badge--neutral", "clock", "Expired"],
};

async function loadAll(token) {
  const items = [];
  for (let offset = 0; ; offset += 200) {
    const res = await api("GET", `/authorizations?limit=200&offset=${offset}`, { token });
    if (!res.ok) return { failed: res };
    items.push(...res.body.authorizations);
    if (!res.body.has_more) break;
  }
  const meRes = await api("GET", "/me", { token });
  if (!meRes.ok) return { failed: meRes };
  return { items, me: meRes.body };
}

export function expiresIn(iso) {
  const ms = new Date(iso).getTime() - Date.now();
  if (Number.isNaN(ms)) return "";
  if (ms <= 0) return "Expired";
  const minutes = Math.round(ms / 60000);
  if (minutes < 60) return `Expires in ${Math.max(minutes, 1)} min`;
  const hours = Math.round(minutes / 60);
  return hours < 48 ? `Expires in ${hours} h` : `Expires in ${Math.round(hours / 24)} days`;
}

export async function authorizationsScreen({ go }) {
  const run = latestOnly();
  const attempts = new Map();
  const drafts = new Map();        // authorization id -> {amount, keepOpen} typed by the user
  const feedback = h("div", { class: "form-feedback requests-feedback", "aria-live": "polite" });
  const list = h("ul", { class: "request-list", "data-testid": "authorization-list" });
  const emptyBlock = h("div", { class: "empty", "data-testid": "empty-authorizations", hidden: true },
    h("p", { class: "empty__title", text: "No holds yet" }),
    h("p", { class: "empty__hint", text: "Reserve money for someone to collect later. Open holds reduce what you can spend until they are collected, voided or expire." }));
  const me = () => currentUser();

  const showError = (text) => {
    feedback.replaceChildren(h("div", { class: "notice notice--refused", role: "alert", tabindex: "-1", "data-testid": "authorization-error" },
      icon("cross"), h("div", { class: "notice__body", text })));
    feedback.firstChild.scrollIntoView({ block: "nearest" });
  };

  const load = () => loadAll(authToken());
  const apply = (result) => {
    if (result.failed) {
      if (result.failed.status === 401) { clearSession(); go("/login", { replace: true }); return; }
      announce("Couldn't refresh. Your last list is still shown.", "info"); return;
    }
    setMe(result.me);
    render(result.items, result.me);
  };
  const refresh = () => run(load, apply);

  function captureControls(a, user) {
    const id = a.authorization_id;
    const draft = drafts.get(id) || {};
    const amountInput = h("input", { class: "input input--small", id: `cap-${id}`, "data-testid": `authorization-capture-amount-${id}`, inputmode: "decimal", autocomplete: "off",
      value: draft.amount ?? formatPlain(a.remaining_amount, user.minor_units) });
    const keep = h("input", { type: "checkbox", id: `keep-${id}`, "data-testid": `authorization-keep-open-${id}` });
    keep.checked = Boolean(draft.keepOpen);
    const button = h("button", { class: "btn btn--small", type: "submit", "data-testid": `authorization-capture-${id}` }, "Capture");
    const form = h("form", { class: "capture-form", novalidate: true },
      h("div", { class: "field" }, h("label", { for: `cap-${id}`, text: `Capture amount (${user.currency})` }), amountInput),
      h("label", { class: "check", for: `keep-${id}` }, keep, h("span", { text: "Keep the rest on hold" })),
      button);
    form.addEventListener("input", () => drafts.set(id, { amount: amountInput.value, keepOpen: keep.checked }));
    if (!attempts.has(id)) attempts.set(id, new Attempt(`/authorizations/${id}/capture`));
    writeForm({ form, button, label: "Capture", busyLabel: "Capturing…", path: `/authorizations/${id}/capture`, attempt: attempts.get(id), slot: feedback,
      ids: { error: "authorization-error", uncertain: "authorization-uncertain", success: "authorization-captured", already: "authorization-already" },
      retryLabel: "Retry capture",
      build: () => {
        const parsed = amountFrom(amountInput.value, me());
        if (parsed.error) return { error: parsed.error };
        const body = { amount: parsed.minor };
        if (keep.checked) body.final = false;
        return { body };
      },
      successText: (r) => `Captured ${formatAmount(r.body.amount, me().minor_units, me().currency)} from ${a.from_handle}.`,
      onSuccess: async () => { drafts.delete(id); await refresh(); }, onRefused: refresh });
    return form;
  }

  function voidButton(a) {
    const id = a.authorization_id;
    const button = h("button", { class: "btn btn--small btn--danger", type: "button", "data-testid": `authorization-void-${id}` }, "Void hold");
    button.addEventListener("click", async () => {
      feedback.replaceChildren();
      button.disabled = true;
      button.replaceChildren(spinner(), document.createTextNode("Voiding…"));
      const result = await api("POST", `/authorizations/${id}/void`, { token: authToken() });
      if (result.networkError) { showError("We didn't get an answer. Check the list before trying again."); await refresh(); return; }
      if (!result.ok) { showError(refusalText(result)); await refresh(); return; }
      await refresh();
    });
    return button;
  }

  function item(a, user) {
    const id = a.authorization_id;
    const [cls, glyph, word] = STATUS[a.status] || STATUS.open;
    const incoming = a.to_user_id === user.user_id;
    const who = incoming ? `${a.from_handle} reserved for you` : `You reserved for ${a.to_handle}`;
    const actions = [];
    if (a.status === "open" && incoming) actions.push(captureControls(a, user));
    if (a.status === "open" && !incoming) actions.push(voidButton(a));
    return h("li", { class: "request-item", "data-testid": `authorization-item-${id}`, "data-status": a.status },
      h("div", { class: "request-item__main" },
        h("div", { class: "request-item__top" }, h("span", { class: `badge ${cls}` }, icon(glyph), word),
          a.visibility === "private" ? h("span", { class: "badge badge--neutral" }, icon("lock"), "Private") : null),
        h("p", { class: "request-item__who", text: who }),
        h("p", { class: "request-item__note", text: a.note }),
        a.status === "open" ? h("p", { class: "hold-remaining" }, h("span", { class: "num", text: formatAmount(a.remaining_amount, user.minor_units, user.currency) }), " still on hold") : null,
        h("p", { class: "hold-expiry" }, a.status === "open" ? `${expiresIn(a.expires_at)} · ` : "Expiry ", h("span", { class: "num mono", "data-testid": `authorization-expires-${id}`, text: a.expires_at })),
        h("time", { class: "request-item__time", datetime: a.created_at, title: a.created_at, text: whenText(a.created_at) })),
      h("div", { class: "hold-amounts" },
        h("span", { class: "request-item__amount num", "data-testid": `authorization-amount-${id}`, text: formatAmount(a.amount, user.minor_units, user.currency) }),
        a.status === "captured" ? h("span", { class: "hold-captured" }, "Captured ", h("span", { class: "num", "data-testid": `authorization-captured-${id}`, text: formatAmount(a.captured_amount, user.minor_units, user.currency) })) : null),
      actions.length ? h("div", { class: "request-item__actions" }, actions) : null);
  }

  function render(items, user) {
    clear(list);
    if (!items.length) { list.hidden = true; emptyBlock.hidden = false; return; }
    list.hidden = false; emptyBlock.hidden = true;
    list.append(...items.map((a) => item(a, user)));
  }

  const panel = buildAuthorizePanel({ me, refresh });
  list.append(h("li", {}, h("div", { class: "skeleton feed-skeleton" })));
  const page = h("div", { class: "page" },
    h("div", { class: "page-head" }, h("h1", { class: "page-title", text: "Authorizations" }),
      h("button", { class: "btn btn--quiet btn--small", type: "button", onclick: refresh }, "Refresh")),
    h("div", { class: "holds-layout" },
      h("div", { class: "holds-form" }, panel.root),
      h("section", { "aria-labelledby": "holds-title" }, h("h2", { id: "holds-title", text: "Your holds" }), feedback, emptyBlock, list)));
  refresh();
  return page;
}
