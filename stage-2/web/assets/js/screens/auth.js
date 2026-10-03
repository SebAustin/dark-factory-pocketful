// /login and /signup. Errors live in one `auth-error` element that exists only while there is an error.
import { h, field, icon, spinner } from "../dom.js";
import { api, errorCode, errorMessage } from "../api.js";
import { setToken } from "../session.js";

function authError(code, message, status) {
  if (code === "email_taken") return "That email is already registered. Log in instead?";
  if (code === "handle_taken") return "The handle made from that email is already taken. Use a different email address.";
  if (status === 401) return "The email or password is wrong.";
  return message || "Something went wrong. Check the details and try again.";
}

function passwordField({ id, label, testid, autocomplete, hint }) {
  const { root, input } = field({ id, label, testid, type: "password", autocomplete, required: true, hint });
  const toggle = h("button", { type: "button", "aria-pressed": "false", "aria-controls": id,
    onclick: () => {
      const show = input.type === "password";
      input.type = show ? "text" : "password";
      toggle.textContent = show ? "Hide" : "Show";
      toggle.setAttribute("aria-pressed", String(show));
    } }, "Show");
  const label_ = root.querySelector("label");
  const wrap = h("span", { class: "input-affix" }, input, toggle);
  root.replaceChildren(label_, wrap, ...(hint ? [root.querySelector(".hint") || h("span", { class: "hint", text: hint })] : []));
  return { root, input };
}

function authForm({ kind, fields, submitLabel, testid, path, build, after, intro, alt }) {
  const errorSlot = h("div", { class: "error-slot" });
  const button = h("button", { class: "btn btn--block", type: "submit", "data-testid": testid }, submitLabel);
  const form = h("form", { class: "form-stack", novalidate: true, "aria-label": intro }, ...fields.map((f) => f.root), errorSlot, button);

  const showError = (text) => {
    errorSlot.replaceChildren(h("div", { class: "notice notice--refused", role: "alert", tabindex: "-1", "data-testid": "auth-error" },
      icon("cross"), h("div", { class: "notice__body", text })));
  };
  const clearError = () => errorSlot.replaceChildren();
  form.addEventListener("input", clearError);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    clearError();
    button.disabled = true;
    button.replaceChildren(spinner(), document.createTextNode(kind === "login" ? "Logging in…" : "Creating account…"));
    const result = await api("POST", path, { body: build() });
    button.disabled = false;
    button.replaceChildren(document.createTextNode(submitLabel));
    if (result.networkError) return showError("Couldn't reach the server. Try again.");
    if (!result.ok) {
      showError(authError(errorCode(result), errorMessage(result), result.status));
      errorSlot.firstChild.focus();
      return;
    }
    setToken(result.body.token);
    await after();
  });
  return form;
}

function signedInNote(me) {
  if (!me) return null;
  return h("div", { class: "notice notice--info auth__signed-in", "data-role": "signed-in-note" }, icon("info"),
    h("div", { class: "notice__body" }, `You're signed in as ${me.display_name}. `,
      h("a", { href: "/", "data-link": "", text: "Continue to your wallet" }),
      ". Submitting this form switches to the other account."));
}

function shell({ title, lede, form, alt, me }) {
  return h("div", { class: "auth" },
    h("div", { class: "auth__lede" }, h("h1", { text: title }), h("p", { text: lede }), h("div", { class: "ledger-rules", "aria-hidden": "true" })),
    h("section", { class: "panel auth__panel" }, h("h2", { text: alt.heading }), signedInNote(me), form,
      h("p", { class: "auth__alt" }, alt.text, " ", h("a", { href: alt.href, "data-link": "", text: alt.link }))));
}

export async function loginScreen({ go, me }) {
  const email = field({ id: "login-email", label: "Email", testid: "login-email", type: "email", autocomplete: "username", required: true });
  const password = passwordField({ id: "login-password", label: "Password", testid: "login-password", autocomplete: "current-password" });
  const form = authForm({
    kind: "login", fields: [email, password], submitLabel: "Log in", testid: "login-submit", path: "/auth/login", intro: "Log in",
    build: () => ({ email: email.input.value.trim(), password: password.input.value }),
    after: () => go("/", { replace: true }),
  });
  return shell({ title: "Money that moves when you say so.", lede: "Send, request and reserve funds with a wallet that always tells you exactly what you can spend.", form,
    me, alt: { heading: "Log in", text: "New here?", href: "/signup", link: "Create an account" } });
}

export async function signupScreen({ go, me }) {
  const name = field({ id: "signup-display-name", label: "Display name", testid: "signup-display-name", autocomplete: "name", required: true });
  const email = field({ id: "signup-email", label: "Email", testid: "signup-email", type: "email", autocomplete: "email", required: true,
    hint: "Your handle is made from the part before the @." });
  const password = passwordField({ id: "signup-password", label: "Password", testid: "signup-password", autocomplete: "new-password", hint: "At least 8 characters." });
  const form = authForm({
    kind: "signup", fields: [name, email, password], submitLabel: "Create account", testid: "signup-submit", path: "/auth/signup", intro: "Create an account",
    build: () => ({ display_name: name.input.value.trim(), email: email.input.value.trim(), password: password.input.value }),
    after: () => go("/", { replace: true }),
  });
  return shell({ title: "A calm place for everyday money.", lede: "Open a wallet in a minute. You can pay anyone by handle and see every movement in plain words.", form,
    me, alt: { heading: "Create your account", text: "Already have one?", href: "/login", link: "Log in" } });
}
