// Session: the bearer token lives in localStorage and is discarded only on a 401.
import { api } from "./api.js";

const KEY = "pocketful.token";
let user = null;

export function token() {
  try { return localStorage.getItem(KEY); } catch { return null; }
}
export function setToken(value) { try { localStorage.setItem(KEY, value); } catch { /* private mode: in-memory only */ memoryToken = value; } }
let memoryToken = null;
export function authToken() { return token() || memoryToken; }
export function clearSession() {
  user = null; memoryToken = null;
  try { localStorage.removeItem(KEY); } catch { /* nothing to clear */ }
}
export function currentUser() { return user; }
export function setMe(me) {
  user = me;
  document.dispatchEvent(new CustomEvent("pocketful:me", { detail: me }));
}

/** Load /me. Returns "ok", "signed-out" (401: token cleared) or "unreachable" (keep the session). */
export async function loadMe() {
  const t = authToken();
  if (!t) return "signed-out";
  const result = await api("GET", "/me", { token: t });
  if (result.networkError) return "unreachable";
  if (result.status === 401) { clearSession(); return "signed-out"; }
  if (!result.ok) return "unreachable";
  setMe(result.body);
  return "ok";
}
