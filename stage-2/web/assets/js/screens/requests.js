// `/requests` — incoming and outgoing requests with pay, decline and cancel.
import { h, clear, icon, spinner, announce } from "../dom.js";
import { api, errorCode } from "../api.js";
import { authToken, clearSession, currentUser, setMe } from "../session.js";
import { formatAmount } from "../money.js";
import { latestOnly } from "../refresh.js";
import { Attempt } from "../idem.js";
import { writeForm, refusalText } from "../forms/writeform.js";
import { whenText } from "./wallet.js";

const STATUS = {
  pending: ["badge--pending", "clock", "Pending"],
  paid: ["badge--ok", "check", "Paid"],
  declined: ["badge--refused", "strike", "Declined"],
  cancelled: ["badge--neutral", "strike", "Cancelled"],
};

async function loadAll(token) {
  const requests = [];
  for (let offset = 0; ; offset += 200) {
    const res = await api("GET", `/requests?limit=200&offset=${offset}`, { token });
    if (!res.ok) return { failed: res };
    requests.push(...res.body.requests);
    if (!res.body.has_more) break;
  }
  const meRes = await api("GET", "/me", { token });
  if (!meRes.ok) return { failed: meRes };
  return { requests, me: meRes.body };
}

export async function requestsScreen({ go }) {
  const run = latestOnly();
  const attempts = new Map();           // request id -> Attempt, kept across re-renders
  const feedback = h("div", { class: "form-feedback requests-feedback", "aria-live": "polite" });
  const incomingList = h("ul", { class: "request-list", "data-testid": "incoming-list" });
  const outgoingList = h("ul", { class: "request-list", "data-testid": "outgoing-list" });
  const emptyBlock = h("div", { class: "empty", "data-testid": "empty-requests", hidden: true },
    h("p", { class: "empty__title", text: "No requests yet" }),
    h("p", { class: "empty__hint", text: "Ask someone for money from your wallet, or split a bill. Requests to you and from you show up here." }));
  let loaded = false;

  const showError = (text) => {
    feedback.replaceChildren(h("div", { class: "notice notice--refused", role: "alert", tabindex: "-1", "data-testid": "request-error" },
      icon("cross"), h("div", { class: "notice__body", text })));
  };
  const clearFeedback = () => feedback.replaceChildren();

  const load = () => loadAll(authToken());
  const apply = (result) => {
    if (result.failed) {
      if (result.failed.status === 401) { clearSession(); go("/login", { replace: true }); return; }
      announce("Couldn't refresh. Your last list is still shown.", "info"); return;
    }
    setMe(result.me);
    loaded = true;
    render(result.requests, result.me);
  };
  const refresh = () => run(load, apply);

  function decideButton(label, testid, path, cls) {
    const button = h("button", { class: `btn btn--small ${cls}`, type: "button", "data-testid": testid }, label);
    button.addEventListener("click", async () => {
      clearFeedback();
      button.disabled = true;
      button.replaceChildren(spinner(), document.createTextNode("Working…"));
      const result = await api("POST", path, { token: authToken() });
      if (result.networkError) { button.disabled = false; button.textContent = label; showError("We didn't get an answer. Check the list before trying again."); await refresh(); return; }
      if (!result.ok) { showError(refusalText(result)); await refresh(); return; }
      await refresh();
    });
    return button;
  }

  function payControls(r, me) {
    const select = h("select", { class: "select select--small", id: `vis-${r.request_id}`, "data-testid": `request-visibility-${r.request_id}`, "aria-label": `Who can see your payment to ${r.requester_handle}` },
      h("option", { value: "public", text: "Public" }), h("option", { value: "private", text: "Private" }));
    const button = h("button", { class: "btn btn--small", type: "submit", "data-testid": `request-pay-${r.request_id}` }, "Pay");
    const form = h("form", { class: "request-pay", novalidate: true }, select, button);
    if (!attempts.has(r.request_id)) attempts.set(r.request_id, new Attempt(`/requests/${r.request_id}/pay`));
    writeForm({ form, button, label: "Pay", busyLabel: "Paying…", path: `/requests/${r.request_id}/pay`, attempt: attempts.get(r.request_id), slot: feedback,
      ids: { error: "request-error", uncertain: "request-uncertain", success: "request-paid", already: "request-already" },
      uncertainText: "We didn't get an answer. This payment may or may not have gone through. Retrying is safe: it can't pay twice.",
      retryLabel: "Retry",
      build: () => ({ body: { visibility: select.value } }),
      successText: (res) => `Paid ${formatAmount(res.body.amount, me.minor_units, me.currency)} to ${r.requester_handle}.`,
      onSuccess: refresh, onRefused: refresh });
    return form;
  }

  function item(r, me, incoming) {
    const [cls, glyph, word] = STATUS[r.status] || STATUS.pending;
    const who = incoming ? r.requester_handle : r.payer_handle;
    const actions = [];
    if (r.status === "pending" && incoming) {
      actions.push(payControls(r, me), decideButton("Decline", `request-decline-${r.request_id}`, `/requests/${r.request_id}/decline`, "btn--danger"));
    }
    if (r.status === "pending" && !incoming) actions.push(decideButton("Cancel request", `request-cancel-${r.request_id}`, `/requests/${r.request_id}/cancel`, "btn--danger"));
    return h("li", { class: "request-item", "data-testid": `request-item-${r.request_id}`, "data-status": r.status },
      h("div", { class: "request-item__main" },
        h("div", { class: "request-item__top" }, h("span", { class: `badge ${cls}` }, icon(glyph), word)),
        h("p", { class: "request-item__who", text: incoming ? `${who} asked you` : `You asked ${who}` }),
        h("p", { class: "request-item__note", text: r.note }),
        h("time", { class: "request-item__time", datetime: r.created_at, title: r.created_at, text: whenText(r.created_at) })),
      h("span", { class: "request-item__amount num", "data-testid": `request-amount-${r.request_id}`, text: formatAmount(r.amount, me.minor_units, me.currency) }),
      actions.length ? h("div", { class: "request-item__actions" }, actions) : null);
  }

  function render(requests, me) {
    const incoming = requests.filter((r) => r.payer_id === me.user_id);
    const outgoing = requests.filter((r) => r.requester_id === me.user_id);
    clear(incomingList).append(...(incoming.length ? incoming.map((r) => item(r, me, true)) : [h("li", { class: "request-none", text: "None" })]));
    clear(outgoingList).append(...(outgoing.length ? outgoing.map((r) => item(r, me, false)) : [h("li", { class: "request-none", text: "None" })]));
    emptyBlock.hidden = requests.length > 0;
  }

  const skeleton = h("div", { class: "skeleton feed-skeleton" });
  incomingList.append(skeleton.cloneNode());
  outgoingList.append(skeleton.cloneNode());
  const page = h("div", { class: "page" },
    h("div", { class: "page-head" }, h("h1", { class: "page-title", text: "Requests" }),
      h("button", { class: "btn btn--quiet btn--small", type: "button", onclick: refresh }, "Refresh")),
    emptyBlock, feedback,
    h("div", { class: "requests-grid" },
      h("section", { "aria-labelledby": "incoming-title" }, h("h2", { id: "incoming-title", text: "Asked of you" }), incomingList),
      h("section", { "aria-labelledby": "outgoing-title" }, h("h2", { id: "outgoing-title", text: "You asked" }), outgoingList)));
  refresh();
  return page;
}
