/** CSV export, built on the device and handed to the OS share sheet.
 *
 * The column sets below are copied from the web portal's own exports
 * (apps/web/src/app/portal/transactions/page.tsx) so a merchant who opens
 * a file from the phone and one from the laptop gets the same spreadsheet.
 *
 * What this exports is what the screen is holding — the page the merchant
 * is looking at, not the whole account. A phone asking the API for every
 * transaction a 34-merchant platform has ever recorded, to build a file
 * in memory, is how one tap takes the API down. The row count is stated
 * in the share dialog so nobody mistakes a page for a full statement; the
 * emailed PDF report covers a date range properly.
 */

import { File, Paths } from "expo-file-system";
import * as Sharing from "expo-sharing";

import { LedgerEntry, Transaction } from "../api/client";

/** Quote every cell and double any embedded quote. The simplest thing
 * that stays correct for a reference or channel containing a comma, and
 * the same approach the web export takes. */
function cell(value: string | number | null | undefined): string {
  const text = value === null || value === undefined ? "" : String(value);
  return `"${text.replace(/"/g, '""')}"`;
}

function toCsv(header: string[], rows: (string | number | null | undefined)[][]): string {
  // CRLF: Excel on Windows is the usual destination, and it is what the
  // web export writes.
  return [header.map(cell).join(","), ...rows.map((row) => row.map(cell).join(","))].join("\r\n");
}

/** ISO-ish and sortable, in the merchant's own local time. A bare
 * toISOString() would show UTC, which reads as the wrong day for anything
 * logged after 03:00 in Dar es Salaam. */
function stamp(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ` +
    `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  );
}

const TRANSACTION_HEADER = [
  "Date",
  "Type",
  "Transaction ID",
  "Reference",
  "Channel",
  "Customer Phone",
  "Opening Balance",
  "Amount",
  "Charge",
  "Net",
  "Closing Balance",
  "Currency",
  "Direction",
  "Status",
];

export function transactionsToCsv(transactions: Transaction[]): string {
  return toCsv(
    TRANSACTION_HEADER,
    transactions.map((t) => [
      stamp(t.created_at),
      t.type,
      t.id,
      t.reference,
      t.method,
      // Exported in full, unlike the on-screen list: a merchant
      // reconciling their own books needs the number they can match
      // against a receipt, and this is their own customer's data in a
      // file they asked for.
      t.customer_phone ?? "",
      t.balance_before ?? "",
      `${t.type === "collection" ? "+" : "-"}${t.gross_amount}`,
      t.fee_amount,
      t.net_amount,
      t.balance_after ?? "",
      t.currency,
      t.direction ?? "",
      t.status,
    ]),
  );
}

const LEDGER_HEADER = [
  "Date",
  "Description",
  "Direction",
  "Type",
  "Reference",
  "Channel",
  "Customer Phone",
  "Opening Balance",
  "Amount",
  "Charge",
  "Net",
  "Closing Balance",
  "Status",
];

export function ledgerToCsv(entries: LedgerEntry[]): string {
  return toCsv(
    LEDGER_HEADER,
    entries.map((e) => [
      stamp(e.date),
      e.description ?? "",
      e.direction,
      e.type ?? "",
      e.reference ?? "",
      e.method ?? "",
      e.customer_phone ?? "",
      e.balance_before,
      `${e.direction === "credit" ? "+" : "-"}${e.amount}`,
      e.fee_amount ?? "",
      e.net_amount ?? "",
      e.balance_after,
      e.status ?? "",
    ]),
  );
}

export class ExportError extends Error {}

/** Writes the CSV to the app's own cache directory and opens the share
 * sheet, which is how a file leaves an app on both platforms — there is no
 * "Downloads folder" to drop it in.
 *
 * The cache directory is private to the app and is the OS's to reclaim.
 * Nothing is written to shared storage, so the app needs no storage
 * permission (`android.permissions` stays empty) and no copy of a
 * merchant's financial data is left anywhere the OS will not clean up.
 */
export async function shareCsv(filename: string, csv: string, dialogTitle: string): Promise<void> {
  if (!(await Sharing.isAvailableAsync())) {
    throw new ExportError("Sharing is not available on this device.");
  }

  const file = new File(Paths.cache, filename);
  try {
    // overwrite, because a second export on the same day reuses the name.
    file.create({ overwrite: true });
    file.write(csv);
  } catch {
    throw new ExportError("Couldn't write the file on this device.");
  }

  await Sharing.shareAsync(file.uri, {
    mimeType: "text/csv",
    dialogTitle,
    UTI: "public.comma-separated-values-text",
  });
}

/** `infinitypay-transactions-2026-10-09.csv` — matches the web export's
 * naming so the two sit together in a folder. */
export function exportFilename(kind: "transactions" | "wallet-ledger"): string {
  return `infinitypay-${kind}-${new Date().toISOString().slice(0, 10)}.csv`;
}
