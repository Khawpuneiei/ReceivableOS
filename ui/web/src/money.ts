// Decimal strings in, display strings out. Money never goes through a float: amounts are parsed into
// integer micro-units (6 decimals) and formatted from there, per the repo's money convention.

const SCALE = 1_000_000n;

export function toMicros(value: string): bigint {
  const m = /^(-)?(\d+)(?:\.(\d+))?$/.exec(value.trim());
  if (!m) throw new Error(`not a decimal string: ${value}`);
  const frac = (m[3] ?? "").padEnd(6, "0").slice(0, 6);
  const n = BigInt(m[2]) * SCALE + BigInt(frac);
  return m[1] ? -n : n;
}

const micros = (v: string | bigint): bigint => (typeof v === "bigint" ? v : toMicros(v));

/** amount x rate, both decimal strings, in micro-units. */
export const times = (amount: string, rate: string): bigint => (toMicros(amount) * toMicros(rate)) / SCALE;

export const minus = (a: string | bigint, ...bs: (string | bigint)[]): bigint =>
  bs.reduce<bigint>((acc, b) => acc - micros(b), micros(a));

export const plus = (...xs: (string | bigint)[]): bigint => xs.reduce<bigint>((acc, x) => acc + micros(x), 0n);

export const lesser = (a: string | bigint, b: string | bigint): bigint =>
  micros(a) < micros(b) ? micros(a) : micros(b);


/** "749000.00" -> "THB 749,000.00" (rounded half up to the cent). */
export function money(value: string | bigint, currency = "THB"): string {
  const m = micros(value);
  const neg = m < 0n;
  const cents = ((neg ? -m : m) + 5_000n) / 10_000n;
  const whole = (cents / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const frac = (cents % 100n).toString().padStart(2, "0");
  return `${neg ? "- " : ""}${currency} ${whole}.${frac}`;
}

/** "50000" -> "50,000", "700000.00" -> "700,000.00": digits grouped, decimals as given. */
export const grouped = (value: string): string => value.replace(/^(-?\d+)/, (w) => w.replace(/\B(?=(\d{3})+(?!\d))/g, ","));

/** A rate as a percentage: "0.70" -> "70%", "0.1095" -> "10.95%", "0.009" -> "0.9%". */
export function percent(rate: string, maxDp = 2): string {
  const unit = 10n ** BigInt(6 - maxDp);
  const scaled = (toMicros(rate) * 100n + unit / 2n) / unit;
  const div = 10n ** BigInt(maxDp);
  const frac = (scaled % div).toString().padStart(maxDp, "0").replace(/0+$/, "");
  return `${scaled / div}${frac ? `.${frac}` : ""}%`;
}

/** A 0.0-1.0 score (a float by contract) as a percentage: 0.002702 -> "0.27%". */
export const scorePercent = (score: number): string => `${Number((score * 100).toFixed(2))}%`;

const DATE = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const DATE_TIME = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
});

/** "2026-11-15" -> "15 Nov 2026". */
export const day = (iso: string): string => (iso ? DATE.format(new Date(`${iso.slice(0, 10)}T00:00:00Z`)) : "-");

/** An ISO timestamp in the viewer's time zone: "19 Oct, 09:14". */
export const when = (iso: string): string => DATE_TIME.format(new Date(iso));

/** Whole days from one ISO date to another. */
export const daysBetween = (from: string, to: string): number =>
  Math.round((Date.parse(to.slice(0, 10)) - Date.parse(from.slice(0, 10))) / 86_400_000);
