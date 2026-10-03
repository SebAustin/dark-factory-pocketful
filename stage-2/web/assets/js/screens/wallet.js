// `/` — balance, send/request/reserve forms, activity feed, and the refresh button.
import { h, clear, icon, spinner, announce } from "../dom.js";
import { api } from "../api.js";
import { authToken, clearSession, currentUser, setMe } from "../session.js";
import { formatAmount } from "../money.js";
import { latestOnly } from "../refresh.js";
import { buildPanels } from "../forms/panels.js";

const PAGE = 50;

export function whenText(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const now = new Date();
  const time = date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return `Today ${time}`;
  const opts = date.getFullYear() === now.getFullYear() ? { day: "numeric", month: "short" } : { day: "numeric", month: "short", year: "numeric" };
  return `${date.toLocaleDateString([], opts)}, ${time}`;
}

function amountLine(label, minor, me, testid, extraClass = "") {
  return h("span", { class: `wallet-line ${extraClass}` }, h("span", { class: "wallet-line__label", text: label }),
    h("span", { class: "num", "data-testid": testid, "data-amount": String(minor), text: formatAmount(minor, me.minor_units, me.currency) }));
}

function hero(me) {
  const available = me.available ?? me.balance;
  const held = me.held ?? 0;
  const total = me.total ?? me.balance;
  const availableText = formatAmount(available, me.minor_units, me.currency);
  const figure = h("span", { class: "hero__amount num", "data-testid": "wallet-available", "data-amount": String(available), text: availableText });
  figure.style.setProperty("--len", String(availableText.length));
  return h("section", { class: "panel hero", "aria-label": "Your wallet" },
    h("p", { class: "eyebrow", text: "Available to spend" }),
    h("div", { class: "hero__figure" }, figure),
    h("div", { class: "hero__secondary" },
      amountLine("Total balance", total, me, "wallet-balance"),
      held > 0 ? h("span", { class: "badge badge--held hero__held" }, icon("hold"), h("span", { class: "wallet-line__label", text: "On hold" }),
        h("span", { class: "num", "data-testid": "wallet-held", "data-amount": String(held), text: formatAmount(held, me.minor_units, me.currency) })) : null));
}

function heroSkeleton() {
  return h("section", { class: "panel hero", "aria-busy": "true", "aria-label": "Loading your wallet" },
    h("p", { class: "eyebrow", text: "Available to spend" }),
    h("div", { class: "skeleton hero__skeleton" }), h("div", { class: "skeleton hero__skeleton hero__skeleton--small" }));
}

function feedItem(p, me) {
  const sent = p.from_user_id === me.user_id, received = p.to_user_id === me.user_id;
  const chip = sent ? h("span", { class: "badge badge--neutral" }, icon("up"), "Sent")
    : received ? h("span", { class: "badge badge--ok" }, icon("down"), "Received")
      : h("span", { class: "badge badge--neutral" }, icon("info"), "Public");
  return h("li", { class: "feed-item", "data-testid": `activity-item-${p.payment_id}`, "data-visibility": p.visibility },
    h("div", { class: "feed-item__main" },
      h("div", { class: "feed-item__top" }, chip,
        p.visibility === "private" ? h("span", { class: "badge badge--neutral" }, icon("lock"), "Private") : null),
      h("p", { class: "feed-item__parties", "data-testid": `activity-parties-${p.payment_id}`, text: `${p.from_handle} → ${p.to_handle}` }),
      h("p", { class: "feed-item__note", "data-testid": `activity-note-${p.payment_id}`, text: p.note }),
      h("time", { class: "feed-item__time", datetime: p.created_at, title: p.created_at, text: whenText(p.created_at) })),
    h("span", { class: "feed-item__amount num", "data-testid": `activity-amount-${p.payment_id}`,
      text: formatAmount(p.amount, me.minor_units, me.currency) }));
}

export async function walletScreen({ go }) {
  const run = latestOnly();
  const heroSlot = h("div", { class: "hero-slot" }, heroSkeleton());
  const feedSlot = h("div", { class: "feed-slot" });
  const refreshBtn = h("button", { class: "btn btn--quiet btn--small", type: "button", "data-testid": "wallet-refresh" }, "Refresh");
  const updated = h("span", { class: "feed-updated", "aria-live": "off" });
  let feed = [], hasMore = false, loaded = false;
  const me = () => currentUser();

  const renderFeed = () => {
    clear(feedSlot);
    const user = me();
    if (!loaded) { feedSlot.append(h("div", { class: "skeleton feed-skeleton" }), h("div", { class: "skeleton feed-skeleton" })); return; }
    if (!feed.length) {
      feedSlot.append(h("div", { class: "empty", "data-testid": "empty-activity" },
        h("p", { class: "empty__title", text: "No payments yet" }),
        h("p", { class: "empty__hint", text: "When you send or receive money, or someone makes a public payment, it shows up here." })));
      return;
    }
    feedSlot.append(h("ol", { class: "feed", "data-testid": "activity-list" }, feed.map((p) => feedItem(p, user))));
    if (hasMore) {
      const more = h("button", { class: "btn btn--quiet btn--block", type: "button" }, "Show more");
      more.addEventListener("click", async () => {
        more.disabled = true;
        const result = await api("GET", `/activity?limit=${PAGE}&offset=${feed.length}`, { token: authToken() });
        if (result.ok) { feed = feed.concat(result.body.payments); hasMore = result.body.has_more; renderFeed(); } else { more.disabled = false; announce("Couldn't load more. Try again.", "info"); }
      });
      feedSlot.append(more);
    }
  };

  const load = async () => {
    const token = authToken();
    const [meRes, feedRes] = await Promise.all([api("GET", "/me", { token }), api("GET", `/activity?limit=${PAGE}`, { token })]);
    return { meRes, feedRes };
  };
  const apply = ({ meRes, feedRes }) => {
    if (meRes.status === 401 || feedRes.status === 401) { clearSession(); go("/login", { replace: true }); return; }
    if (!meRes.ok || !feedRes.ok) { announce("Couldn't refresh. Your last numbers are still shown.", "info"); return; }
    setMe(meRes.body);
    feed = feedRes.body.payments; hasMore = feedRes.body.has_more; loaded = true;
    clear(heroSlot).append(hero(meRes.body));
    renderFeed();
    updated.textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
  };
  const refresh = () => run(load, apply);

  // The button stays enabled while a refresh runs, so a stalled read can always be superseded by a later one.
  let lastClick = 0;
  refreshBtn.addEventListener("click", async () => {
    const mine = ++lastClick;
    refreshBtn.setAttribute("aria-busy", "true");
    refreshBtn.replaceChildren(spinner(), document.createTextNode("Refreshing…"));
    await refresh();
    if (mine === lastClick) {
      refreshBtn.removeAttribute("aria-busy");
      refreshBtn.replaceChildren(document.createTextNode("Refresh"));
    }
  });

  const panels = buildPanels({ me, refresh });
  renderFeed();
  const page = h("div", { class: "page wallet" },
    h("div", { class: "wallet__money" }, heroSlot, panels.send.root, panels.request.root, panels.authorize.root),
    h("section", { class: "wallet__record", "aria-labelledby": "feed-title" },
      h("div", { class: "feed-head" }, h("h2", { id: "feed-title", text: "Activity" }), h("div", { class: "feed-head__tools" }, updated, refreshBtn)),
      feedSlot));
  refresh();
  return page;
}
