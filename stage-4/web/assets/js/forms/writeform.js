// One controller for every "submit a write" form: validation, key lifecycle, refusal vs unknown outcome.
import { h, icon, spinner } from "../dom.js";
import { api, errorCode, errorMessage } from "../api.js";
import { Attempt } from "../idem.js";
import { authToken } from "../session.js";

const REFUSALS = {
  insufficient_funds: "Not enough available funds for that.",
  self_payment: "You can't send money to yourself.",
  self_request: "You can't request money from yourself.",
  not_found: "No one has that handle.",
  validation_failed: null,
  request_not_pending: "That request is no longer pending.",
  authorization_not_open: "That hold is already closed.",
  authorization_expired: "That hold has expired.",
  capture_exceeds_authorization: "That's more than what is still on hold.",
  forbidden: "You can't do that.",
  unauthenticated: "Your session has ended. Log in again.",
};

export function refusalText(result) {
  const code = errorCode(result);
  const friendly = REFUSALS[code];
  const server = errorMessage(result);
  return friendly || server || "That didn't go through.";
}

function notice(kind, glyph, testid, role, text, extra) {
  return h("div", { class: `notice notice--${kind}`, role, tabindex: "-1", "data-testid": testid },
    icon(glyph), h("div", { class: "notice__body" }, text, extra || null));
}

/**
 * config: {form, button, label, busyLabel, path, build(): {body}|{error}, ids: {error, uncertain, success, already},
 *          successText(result): string, onSuccess(): Promise, onRefused(result): Promise, uncertainText, retryLabel}
 */
export function writeForm(config) {
  const { form, button, label, busyLabel, ids } = config;
  const attempt = config.attempt || new Attempt(config.path);
  const slot = config.slot || h("div", { class: "form-feedback", "aria-live": "polite" });
  if (!config.slot) button.after(slot);   // below the button: feedback appearing or clearing never moves the button under the pointer
  let busy = false;

  const clearFeedback = () => slot.replaceChildren();
  // Every feedback element is brought fully into view; scroll-padding/margin in the CSS keep it clear of the tab bar.
  const put = (node) => { slot.replaceChildren(node); node.scrollIntoView({ block: "nearest" }); };
  const setLabel = (text) => { button.replaceChildren(document.createTextNode(text)); };
  const showError = (text) => put(notice("refused", "cross", ids.error, "alert", text));
  const showUncertain = () => {
    put(notice("unsure", "question", ids.uncertain, "status",
      config.uncertainText || "We didn't get an answer. This may or may not have gone through. Retrying is safe: it can't happen twice."));
    setLabel(config.retryLabel || "Retry safely");
  };
  const showStaleNote = () => {
    put(notice("info", "info", `${ids.uncertain}-note`, "status",
      "A previous attempt wasn't confirmed. Check your activity before sending again."));
    setLabel(label);
  };

  // Any edit makes the form a different request, even if the values are later put back (new key on the next send).
  const onEdit = () => {
    attempt.markDirty();            // also while a submit is in flight: the next send is a new request
    if (busy) return;
    if (attempt.phase === "uncertain") { showStaleNote(); return; }
    if (slot.firstChild && slot.firstChild.getAttribute("data-testid") !== `${ids.uncertain}-note`) clearFeedback();
  };
  form.addEventListener("input", onEdit);
  // `change` fires on blur, i.e. on mousedown of the button the user is about to press: it only records the edit,
  // never touches the feedback, so nothing can move under the pointer.
  form.addEventListener("change", () => attempt.markDirty());

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy) return;
    const built = config.build();
    if (built.error) { showError(built.error); slot.firstChild.focus(); return; }
    const plan = attempt.prepare(built.body);
    if (plan.skip) {
      put(notice("info", "check", ids.already, "status", config.alreadyText || "Already done. Change a field to do it again."));
      return;
    }
    clearFeedback();
    busy = true;
    attempt.begin();
    button.disabled = true;
    button.replaceChildren(spinner(), document.createTextNode(busyLabel));
    const result = await api("POST", config.path, { body: built.body, key: plan.key, token: authToken() });
    busy = false;
    button.disabled = false;
    setLabel(label);
    if (result.networkError) { attempt.uncertain(); showUncertain(); return; }
    if (!result.ok) {
      attempt.refused();
      showError(refusalText(result));
      if (config.onRefused) await config.onRefused(result);
      return;
    }
    attempt.succeeded();
    if (config.onSuccess) await config.onSuccess(result);  // refresh first, then say it worked
    put(notice("ok", "check", ids.success, "status", config.successText(result)));
  });

  return { attempt, slot };
}
