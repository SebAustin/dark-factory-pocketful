// One Attempt per write form: the idempotency key lives exactly as long as the request body it was made for.
export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    return `{${Object.keys(value).sort().map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`).join(",")}}`;
  }
  return JSON.stringify(value);
}

export function newKey() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  return "k-" + Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export class Attempt {
  constructor(path) { this.path = path; this.fingerprint = null; this.key = null; this.phase = "idle"; this.dirty = false; }

  /** Any edit of a field makes the next send a new request, even if the values are later put back. */
  markDirty() { this.dirty = true; }

  fingerprintOf(body) { return `${this.path} ${canonical(body)}`; }

  /** Decide what a submit of `body` should do: {send, key} or {skip}. */
  prepare(body) {
    const fp = this.fingerprintOf(body);
    if (fp !== this.fingerprint || this.dirty) {   // an edited form is a different request: a new key
      this.fingerprint = fp; this.key = newKey(); this.phase = "idle"; this.dirty = false;
      return { send: true, key: this.key };
    }
    if (this.phase === "succeeded") return { skip: true };
    if (this.phase === "refused") this.key = newKey(); // a confirmed refusal changed nothing
    return { send: true, key: this.key };      // idle or uncertain: same key, same body
  }

  begin() { this.phase = "inflight"; }
  succeeded() { this.phase = "succeeded"; }
  refused() { this.phase = "refused"; }
  uncertain() { this.phase = "uncertain"; }
  isUncertainFor(body) { return this.phase === "uncertain" && this.fingerprintOf(body) === this.fingerprint; }
}
