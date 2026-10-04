import { h } from "../dom.js";

const COPY = {
  "/": ["Wallet", "Balance, payments and activity arrive in the next step."],
  "/requests": ["Requests", "Incoming and outgoing requests arrive in the next step."],
  "/split": ["Split a bill", "The split form arrives in the next step."],
  "/authorizations": ["Authorizations", "Holds and captures arrive in the next step."],
};

export async function soonScreen({ path }) {
  const [title, lede] = COPY[path] || ["Not found", "There is nothing at this address."];
  return h("section", { class: "page" }, h("h1", { class: "page-title", text: title }),
    h("p", { class: "placeholder", text: lede }));
}
