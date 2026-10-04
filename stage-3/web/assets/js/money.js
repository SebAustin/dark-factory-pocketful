// Integer money. No floats anywhere: amounts are BigInt minor units, text is split on the decimal point.
const DECIMAL = /^\d+(\.\d+)?$/;

/** Parse what a person typed. Returns {minor: BigInt} or {error}. */
export function parseAmount(text, minorUnits) {
  const raw = String(text ?? "").trim();
  if (!DECIMAL.test(raw)) return { error: "not_a_number" };
  const [whole, fraction = ""] = raw.split(".");
  if (fraction.length > minorUnits || (minorUnits === 0 && raw.includes("."))) return { error: "too_many_decimals" };
  const padded = fraction.padEnd(minorUnits, "0");
  return { minor: BigInt(whole) * 10n ** BigInt(minorUnits) + BigInt(padded || "0") };
}

/** "100.00", "1200", "1.234" — no currency code, no grouping. */
export function formatPlain(minor, minorUnits) {
  const value = BigInt(minor);
  if (value < 0n) throw new RangeError("negative amount");
  const digits = value.toString().padStart(minorUnits + 1, "0");
  if (minorUnits === 0) return digits;
  return `${digits.slice(0, -minorUnits)}.${digits.slice(-minorUnits)}`;
}

/** "100.00 EUR", "1200 JPY". */
export function formatAmount(minor, minorUnits, currency) {
  return `${formatPlain(minor, minorUnits)} ${currency}`;
}

/** Equal split (spec §9): the first `amount % n` participants get one extra unit. */
export function splitShares(minor, n) {
  const total = BigInt(minor), count = BigInt(n);
  const base = total / count, extra = total % count;
  return Array.from({ length: n }, (_, i) => base + (BigInt(i) < extra ? 1n : 0n));
}

export const MAX_AMOUNT = 1000000000n;
