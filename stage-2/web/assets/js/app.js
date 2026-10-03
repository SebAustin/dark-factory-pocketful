// Boot, router and chrome. Every UI route serves the same shell; this file mounts the screen.
import { h, clear, icon } from "./dom.js";
import { authToken, clearSession, currentUser, loadMe } from "./session.js";
import { formatAmount } from "./money.js";

const NAV = [
  { path: "/", label: "Wallet", icon: "wallet" },
  { path: "/requests", label: "Requests", icon: "requests" },
  { path: "/split", label: "Split", icon: "split" },
  { path: "/authorizations", label: "Holds", icon: "hold", long: "Authorizations" },
];
const PUBLIC_ROUTES = new Set(["/login", "/signup"]);
const SCREENS = {
  "/requests": () => import("./screens/requests.js").then((m) => m.requestsScreen),
  "/authorizations": () => import("./screens/authorizations.js").then((m) => m.authorizationsScreen),
  "/split": () => import("./screens/split.js").then((m) => m.splitScreen),
  "/": () => import("./screens/wallet.js").then((m) => m.walletScreen),
  "/login": () => import("./screens/auth.js").then((m) => m.loginScreen),
  "/signup": () => import("./screens/auth.js").then((m) => m.signupScreen),
};

let renderToken = 0;

export function go(path, { replace = false } = {}) {
  if (replace) history.replaceState({}, "", path); else history.pushState({}, "", path);
  return render();
}

const WIDE = window.matchMedia("(min-width: 1240px)");

// The chip only exists in the DOM when the header has room for it (>= 1240px).
function balanceChip(me) {
  if (!me || !WIDE.matches) return null;
  const available = me.available ?? me.balance;
  return h("span", { class: "balance-chip", "data-chip": "balance" },
    h("span", { text: "Available" }),
    h("b", { class: "num", text: formatAmount(available, me.minor_units, me.currency) }));
}

function userArea(me) {
  return h("div", { class: "user-area" },
    balanceChip(me),
    h("div", { class: "user-chip" },
      h("span", { "data-testid": "current-user", title: me.display_name, text: me.display_name }),
      h("span", { "data-testid": "current-handle", text: me.handle })),
    h("button", { class: "btn btn--quiet btn--small btn--on-dark", type: "button", "data-testid": "logout-button",
      onclick: () => { clearSession(); go("/login", { replace: true }); } }, "Log out"));
}

function navLink(item, path, className) {
  const current = item.path === path;
  return h("a", { href: item.path, "data-link": "", "aria-current": current ? "page" : false },
    icon(item.icon), item.label);
}

function chrome(path, me) {
  const signedIn = Boolean(me);
  const header = h("header", { class: "app-header" },
    h("div", { class: "app-header__inner" },
      h("a", { class: "brand", href: signedIn ? "/" : "/login", "data-link": "", "aria-label": "Pocketful home" },
        icon("logo"), "Pocketful"),
      signedIn ? h("nav", { class: "nav-main", "aria-label": "Main" },
        NAV.map((item) => h("a", { href: item.path, "data-link": "", "aria-current": item.path === path ? "page" : false },
          icon(item.icon), item.long || item.label))) : null,
      signedIn ? userArea(me) : h("nav", { class: "guest-links", "aria-label": "Account" },
        h("a", { href: "/login", "data-link": "", "aria-current": path === "/login" ? "page" : false }, "Log in"),
        h("a", { href: "/signup", "data-link": "", "aria-current": path === "/signup" ? "page" : false }, "Sign up"))));
  const main = h("main", { id: "main", tabindex: "-1" });
  const tabbar = signedIn ? h("nav", { class: "tabbar", "aria-label": "Main" },
    h("div", { class: "tabbar__inner" }, NAV.map((item) => navLink(item, path)))) : null;
  document.body.classList.toggle("has-tabbar", signedIn);
  return { header, main, tabbar };
}

async function render() {
  const mine = ++renderToken;
  const app = document.getElementById("app");
  app.setAttribute("aria-busy", "true");
  const path = location.pathname.replace(/\/+$/, "") || "/";
  const isPublic = PUBLIC_ROUTES.has(path);

  let state = authToken() ? await loadMe() : "signed-out";
  if (mine !== renderToken) return;
  if (state === "signed-out" && !isPublic) return go("/login", { replace: true });

  const me = state === "ok" || state === "unreachable" ? currentUser() : null;
  const { header, main, tabbar } = chrome(path, state === "ok" ? me : null);
  clear(app).append(header, main, ...(tabbar ? [tabbar] : []));
  document.title = path === "/" ? "Pocketful" : `${titleFor(path)} · Pocketful`;

  const loader = SCREENS[path];
  const screen = loader ? await loader() : (await import("./screens/soon.js")).soonScreen;
  if (mine !== renderToken) return;
  main.append(await screen({ path, me, go }));
  app.setAttribute("aria-busy", "false");
}

function titleFor(path) {
  return { "/login": "Log in", "/signup": "Sign up", "/requests": "Requests", "/split": "Split",
    "/authorizations": "Authorizations" }[path] || "Pocketful";
}

document.addEventListener("click", (event) => {
  const link = event.target.closest?.("a[data-link]");
  if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
  const url = new URL(link.href, location.href);
  if (url.origin !== location.origin) return;
  event.preventDefault();
  if (url.pathname !== location.pathname) go(url.pathname);
});
window.addEventListener("popstate", render);
WIDE.addEventListener("change", () => {
  const area = document.querySelector(".user-area"), me = currentUser();
  if (!area || !me) return;
  area.querySelector('[data-chip="balance"]')?.remove();
  const chip = balanceChip(me);
  if (chip) area.prepend(chip);
});
// Keep the header balance chip in step with every refresh of /me.
document.addEventListener("pocketful:me", (event) => {
  const chip = document.querySelector('[data-chip="balance"]');
  const me = event.detail;
  if (!chip || !me) return;
  chip.querySelector("b").textContent = formatAmount(me.available ?? me.balance, me.minor_units, me.currency);
});

render();
