// Latest refresh wins: only the response of the most recently STARTED load is applied, whole.
export function latestOnly() {
  let seq = 0;
  return async function run(load, apply) {
    const mine = ++seq;
    const result = await load();
    if (mine !== seq) return { stale: true };
    apply(result);
    return { stale: false, result };
  };
}
