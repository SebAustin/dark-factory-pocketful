// Thin fetch wrapper. A write whose response never arrives has an UNKNOWN outcome, never a refusal.
export const TIMEOUT_MS = 12000;

/**
 * api(method, path, {body, key, token, signal}) ->
 *   {status, ok, body}                 a real answer (2xx ok, 4xx refusal with {error:{code,message}})
 *   {networkError: true}               no usable answer: offline, aborted, timed out, reset, 5xx, unparseable
 */
export async function api(method, path, { body, key, token } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  if (key) headers["Idempotency-Key"] = key;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(path, {
      method, headers, signal: controller.signal, cache: "no-store",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let parsed = null;
    const text = await response.text();
    if (text) {
      try { parsed = JSON.parse(text); } catch { return { networkError: true, status: response.status }; }
    }
    if (response.status >= 500) return { networkError: true, status: response.status, body: parsed };
    return { status: response.status, ok: response.ok, body: parsed };
  } catch {
    return { networkError: true };
  } finally {
    clearTimeout(timer);
  }
}

export function errorCode(result) { return result?.body?.error?.code || null; }
export function errorMessage(result) { return result?.body?.error?.message || ""; }
