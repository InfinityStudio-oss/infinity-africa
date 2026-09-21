/** How a merchant receives payouts from their InfinityPay balance — matches disbursements.method in the DB schema. */
export enum DisbursementMethod {
  SELCOM_PESA = "SELCOM_PESA",
  MOBILE_MONEY = "MOBILE_MONEY",
  BANK_ACCOUNT = "BANK_ACCOUNT",
}

export const DISBURSEMENT_METHOD_LABELS: Record<DisbursementMethod, string> = {
  [DisbursementMethod.SELCOM_PESA]: "Selcom Pesa",
  [DisbursementMethod.MOBILE_MONEY]: "Mobile Money",
  [DisbursementMethod.BANK_ACCOUNT]: "Bank Account",
};

/** Surfaced in the merchant portal's payout method picker — Selcom Pesa is
 * the fastest/cheapest rail, so it's flagged for the UI to highlight
 * (e.g. a "Recommended" badge), not because the others are unsupported. */
export const DISBURSEMENT_METHOD_RECOMMENDED: Record<DisbursementMethod, boolean> = {
  [DisbursementMethod.SELCOM_PESA]: true,
  [DisbursementMethod.MOBILE_MONEY]: false,
  [DisbursementMethod.BANK_ACCOUNT]: false,
};
