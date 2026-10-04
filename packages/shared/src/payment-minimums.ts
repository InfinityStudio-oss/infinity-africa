/** Per-network minimum payment amounts, and the network a Tanzanian
 * mobile number belongs to.
 *
 * Mixx by Yas (Tigo) refuses a push below TZS 1,000; every other network
 * accepts from TZS 100. Enforced on the backend in
 * `apps/api/app/core/payment_minimums.py` — this copy exists so the
 * customer finds out while they are still typing, instead of after a
 * round trip that was always going to fail.
 *
 * The two must agree. `apps/api/tests/test_payment_minimums_sync.py`
 * reads this file and fails if the prefixes or the amounts drift, the
 * same way the destination-code labels are kept in step.
 *
 * This is a convenience, never the enforcement: the backend rejects the
 * same request regardless of what the browser did.
 */

export enum MobileNetwork {
  MPESA = "MPESA",
  MIXXBYYAS = "MIXXBYYAS",
  AIRTELMONEY = "AIRTELMONEY",
  HALOPESA = "HALOPESA",
  TTCLPESA = "TTCLPESA",
}

export const MIXX_BY_YAS_MINIMUM = 1000;
export const DEFAULT_MINIMUM = 100;

/** Two-digit national prefix (what follows "255") -> network. Mirrors
 * _PREFIX_TO_NETWORK in the Python module, including 77 — originally
 * Zantel, merged into Tigo and now sold as Mixx by Yas. */
export const NETWORK_PREFIXES: Record<string, MobileNetwork> = {
  "74": MobileNetwork.MPESA,
  "75": MobileNetwork.MPESA,
  "76": MobileNetwork.MPESA,
  "65": MobileNetwork.MIXXBYYAS,
  "67": MobileNetwork.MIXXBYYAS,
  "71": MobileNetwork.MIXXBYYAS,
  "77": MobileNetwork.MIXXBYYAS,
  "68": MobileNetwork.AIRTELMONEY,
  "69": MobileNetwork.AIRTELMONEY,
  "78": MobileNetwork.AIRTELMONEY,
  "61": MobileNetwork.HALOPESA,
  "62": MobileNetwork.HALOPESA,
  "73": MobileNetwork.TTCLPESA,
};

export const MIXX_BY_YAS_MESSAGE =
  "Minimum amount for Tigo / Mixx by Yas is TZS 1,000. " +
  "Please enter TZS 1,000 or more, or use another mobile money network.";

export const DEFAULT_MINIMUM_MESSAGE = "Minimum payment amount is TZS 100.";

/** Normalises the shapes a customer actually types — 0713…, 713…,
 * +255713…, with spaces or dashes — to "255XXXXXXXXX", or null if it is
 * not a usable Tanzanian number yet. Returns null rather than throwing:
 * this runs on every keystroke, and a half-typed number is normal, not
 * an error. */
export function normalizeTzPhone(raw: string): string | null {
  const digits = raw.replace(/[\s\-()+]/g, "");
  if (!/^\d+$/.test(digits)) return null;
  if (digits.length === 10 && digits.startsWith("0")) return `255${digits.slice(1)}`;
  if (digits.length === 9 && (digits.startsWith("6") || digits.startsWith("7"))) return `255${digits}`;
  if (digits.length === 12 && digits.startsWith("255")) return digits;
  return null;
}

/** The network this number belongs to, or null while it is still being
 * typed or its prefix is not one we map. */
export function detectNetwork(phone: string | null | undefined): MobileNetwork | null {
  if (!phone) return null;
  const normalized = normalizeTzPhone(phone);
  if (!normalized) return null;
  return NETWORK_PREFIXES[normalized.slice(3, 5)] ?? null;
}

export function minimumForNetwork(network: MobileNetwork | null): number {
  return network === MobileNetwork.MIXXBYYAS ? MIXX_BY_YAS_MINIMUM : DEFAULT_MINIMUM;
}

/**
 * The message to show, or null when the amount is fine.
 *
 * Returns null while the number is incomplete: warning someone that
 * their network has a minimum before they have finished typing the
 * number is noise, and the backend is the thing that actually enforces
 * this.
 */
export function minimumAmountError(amount: number | string, phone: string | null | undefined): string | null {
  const value = typeof amount === "number" ? amount : Number(amount);
  if (!Number.isFinite(value)) return null;

  const network = detectNetwork(phone);
  if (network === null) {
    // No network known yet, so only the floor every network shares can
    // be asserted.
    return value < DEFAULT_MINIMUM ? DEFAULT_MINIMUM_MESSAGE : null;
  }
  if (value >= minimumForNetwork(network)) return null;
  return network === MobileNetwork.MIXXBYYAS ? MIXX_BY_YAS_MESSAGE : DEFAULT_MINIMUM_MESSAGE;
}
