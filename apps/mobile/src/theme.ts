/** InfinityPay's palette, as the mobile app sees it.
 *
 * These values are copied from apps/web/src/app/globals.css rather than
 * reinvented — the merchant who checks their balance on a phone at a
 * till and then on a laptop that evening is looking at one product, and
 * two slightly different greens is how it stops feeling like one.
 *
 * Keep them in step by hand if the web tokens change. They are not
 * imported from the web app because that would drag Tailwind and the
 * whole Next build into a React Native bundle for the sake of a handful
 * of hex strings.
 */

import { TextStyle } from "react-native";

export const colors = {
  /** Deep emerald. Headers, primary actions, the brand. */
  primary: "#04332a",
  onPrimary: "#ffffff",
  primaryContainer: "#04332a",
  onPrimaryContainer: "#93ecb8",

  secondary: "#56615e",
  secondaryContainer: "#dae5e1",
  onSecondaryContainer: "#5c6764",

  /** Pale, slightly cool page background — cards lift off it. */
  background: "#f9f9ff",
  surface: "#ffffff",
  surfaceLow: "#f1f3ff",
  surfaceHigh: "#e1e8fd",
  surfaceHighest: "#dce2f7",

  onSurface: "#141b2b",
  onSurfaceVariant: "#3f4942",

  outline: "#6f7a71",
  outlineVariant: "#bec9bf",

  error: "#ba1a1a",
  onError: "#ffffff",
  errorContainer: "#ffdad6",
  onErrorContainer: "#93000a",

  /** Status tones. Money states need to read at a glance, in sunlight,
   * on a cheap screen — hence solid fills rather than tints. */
  success: "#166534",
  successContainer: "#dcfce7",
  warning: "#854d0e",
  warningContainer: "#fef9c3",
  neutral: "#3f4942",
  neutralContainer: "#e9edff",
} as const;

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
} as const;

export const radius = {
  sm: 8,
  md: 12,
  /** Cards. Matches the portal's rounded-xl. */
  lg: 16,
  pill: 9999,
} as const;

/** Typed as TextStyle rather than `as const`: a const assertion makes
 * fontVariant a readonly tuple, which React Native's style types reject. */
export const typography: Record<
  "display" | "title" | "heading" | "body" | "label" | "caption" | "amount",
  TextStyle
> = {
  display: { fontSize: 28, fontWeight: "700" },
  title: { fontSize: 20, fontWeight: "700" },
  heading: { fontSize: 16, fontWeight: "600" },
  body: { fontSize: 14, fontWeight: "400" },
  label: { fontSize: 13, fontWeight: "500" },
  caption: { fontSize: 12, fontWeight: "400" },
  /** Amounts. Tabular so a column of figures lines up. */
  amount: { fontSize: 24, fontWeight: "700", fontVariant: ["tabular-nums"] },
};

/** Tanzanian Shillings, the way the portal writes them.
 *
 * Amounts arrive from the API as decimal strings, never as numbers —
 * see the note in src/api/client.ts about why. Formatting is the only
 * thing done to them here; nothing in this app computes money. */
export function formatTzs(amount: string | number | null | undefined): string {
  if (amount === null || amount === undefined || amount === "") return "TZS 0.00";
  const value = typeof amount === "number" ? amount : Number(amount);
  if (!Number.isFinite(value)) return "TZS 0.00";
  return `TZS ${value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

/** For balance columns, which the API returns as null when it has no
 * figure: transactions created before the column existed, or with no
 * wallet-affecting leg. Null means "not available" and is shown as such
 * — formatTzs would print TZS 0.00, which is a different claim and a
 * false one. Mirrors the portal's own money() helper.
 */
export function formatTzsOrUnavailable(amount: string | number | null | undefined): string {
  if (amount === null || amount === undefined || amount === "") return "Not available";
  return formatTzs(amount);
}

/** Shows enough of a number to recognise a customer, not enough to
 * reuse it. Mirrors the portal's maskAccountIdentifier. */
export function maskPhone(phone: string | null | undefined): string {
  if (!phone) return "—";
  const digits = phone.replace(/\D/g, "");
  if (digits.length < 4) return "••••";
  return `•••• ${digits.slice(-4)}`;
}
