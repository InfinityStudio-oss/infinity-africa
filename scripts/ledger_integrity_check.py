#!/usr/bin/env python3
"""Money that was marked received but never posted to the ledger.

Read-only. Finds successful collection transactions with no ledger
entries behind them - a customer who paid, a transaction that says so,
and a merchant who was never credited.

**Why a wallet-balance check cannot find these.** The usual integrity
check compares each wallet's stated balance against the sum of its own
entries, and those two agree perfectly here: the posting is missing from
*both* sides. A transaction with no entries is invisible to it. That is
how one sat in production from 24 October unnoticed while a balance
reconciliation reported all 92 wallets clean.

**How it happens.** Crediting is three separate writes - mark the
collection successful, mark the transaction successful, post the double
entry. resolve_collection() does them in that order and so did
scripts/credit_missing_collection_transactions.py. An interruption
between the second and the third leaves exactly this state, and nothing
retries it.

Prints what it finds and exits non-zero if anything is unposted, so it
can be run from a scheduler. It never writes: repairing a half-written
credit is a money decision and belongs with a human.

    python scripts/ledger_integrity_check.py
    python scripts/ledger_integrity_check.py --days 7
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
import sys
from decimal import Decimal

try:
    import httpx
except ImportError:  # pragma: no cover
    sys.exit("httpx is required: pip install httpx")

ENV = pathlib.Path(__file__).resolve().parents[1] / "apps" / "api" / ".env"


def env(name: str) -> str | None:
    if not ENV.is_file():
        return None
    m = re.search(rf"^{name}=(.*)$", ENV.read_text(encoding="utf-8"), re.M)
    return m.group(1).strip().strip('"').strip("'") if m else None


def page(client, base, table, select, extra=""):
    """PostgREST caps a response at 1000 rows whatever limit you ask for."""
    out, offset = [], 0
    while True:
        r = client.get(f"{base}/rest/v1/{table}?select={select}{extra}&limit=1000&offset={offset}")
        if r.status_code >= 400:
            print(f"  query failed {r.status_code} on {table}")
            return out
        batch = r.json()
        if not isinstance(batch, list):
            return out
        out += batch
        if len(batch) < 1000:
            return out
        offset += 1000


def eat(value: str) -> str:
    return (
        dt.datetime.fromisoformat(value.replace("Z", "+00:00")) + dt.timedelta(hours=3)
    ).strftime("%d %b %H:%M")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=0, help="limit to the last N days (0 = all time)")
    args = ap.parse_args()

    base, key = env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY")
    if not base or not key:
        print("  SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not found in apps/api/.env")
        return 2

    window = ""
    if args.days > 0:
        since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)).isoformat()
        window = f"&created_at=gte.{since.replace('+00:00', 'Z')}"

    client = httpx.Client(headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=240)
    with client:
        names = {
            m["id"]: m["business_name"]
            for m in client.get(f"{base}/rest/v1/merchants?select=id,business_name").json()
        }
        transactions = page(
            client,
            base,
            "transactions",
            "id,merchant_id,status,gross_amount,fee_amount,net_amount,created_at,reference",
            f"&type=eq.collection&status=eq.successful{window}",
        )
        ids = [str(t["id"]) for t in transactions]

        posted: set[str] = set()
        for i in range(0, len(ids), 60):
            for entry in page(
                client, base, "ledger_entries", "transaction_id",
                f"&transaction_id=in.({','.join(ids[i : i + 60])})",
            ):
                posted.add(str(entry["transaction_id"]))

        unposted = [t for t in transactions if str(t["id"]) not in posted]

        scope = f"last {args.days} days" if args.days else "all time"
        print(f"\n  LEDGER INTEGRITY - successful collections, {scope}\n")
        print(f"    transactions marked successful   {len(transactions):,}")
        print(f"    with a double entry behind them  {len(posted):,}")
        print(f"    NEVER POSTED                     {len(unposted)}")

        if not unposted:
            print("\n    Every successful collection has its posting. "
                  "No new findings in the checked scope.\n")
            return 0

        owed = sum(Decimal(str(t.get("net_amount") or 0)) for t in unposted)
        print(f"    merchant money never credited    TZS {owed:,.2f}\n")
        for t in sorted(unposted, key=lambda r: r["created_at"]):
            print(
                f"      {eat(t['created_at'])}  {names.get(t['merchant_id'], '?')[:22]:<23} "
                f"gross {str(t['gross_amount']):<10} net {str(t['net_amount']):<10} {t.get('reference')}"
            )
        print(
            "\n    These are NOT repaired here. Posting a missing credit is a money\n"
            "    decision: confirm the payment against the provider first, then\n"
            "    post through the ordinary path so the double entry is written by\n"
            "    the same code that writes every other one.\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
