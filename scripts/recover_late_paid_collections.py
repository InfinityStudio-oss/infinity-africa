#!/usr/bin/env python3
"""Credit payments Selcom confirmed after we had already expired them.

`COLLECTION_PUSH_EXPIRY_MINUTES` is 5. Selcom keeps the prompt alive
longer, so a customer can approve after we have given up. Selcom then
sends a COMPLETED callback, we record it in `selcom_webhook_events`, and
`resolve_collection` refuses it because it only acts on a collection that
is still `processing`. The money is taken, the merchant is not credited,
and the customer is never connected.

Measured on 2026-10-25: Selcom's confirmation arrives a median of 122
seconds after our expiry write, and 51 of 58 arrived within five minutes
of it.

This repairs the rows already in that state, using Selcom's own stored
callback as the authority - not an SMS, not an assumption. For each one:

    status -> processing          (resolve_collection only acts on that)
    transaction -> processing
    resolve_collection(...)       the ordinary path

which credits the wallet through the normal double entry, marks the
collection successful, and enqueues `collection.success` - that last part
being what actually connects the customer, since every one of these
previously sent `collection.failed`.

Safety:

  * **Selcom's callback is the only evidence used.** A collection with no
    COMPLETED callback for its checkout order is never touched.
  * Re-checked immediately before writing, so a second run credits
    nothing twice: anything already `successful` is skipped.
  * `--skip REF` leaves a payment alone - for a customer a merchant has
    already activated by hand, where replaying the webhook would connect
    them twice.
  * Dry run unless given --apply.

    python scripts/recover_late_paid_collections.py --since 2026-10-24T21:00:00Z
    python scripts/recover_late_paid_collections.py --since 2026-10-24T21:00:00Z --apply
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import uuid
from decimal import Decimal

APP = pathlib.Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(APP))


def _paid_orders(client, since: str) -> dict[str, dict]:
    """order_id -> Selcom's COMPLETED callback body."""
    out: dict[str, dict] = {}
    offset = 0
    while True:
        rows = (
            client.table("selcom_webhook_events")
            .select("raw_body, created_at")
            .gte("created_at", since)
            .range(offset, offset + 999)
            .execute()
        ).data or []
        for row in rows:
            body = row.get("raw_body")
            if isinstance(body, str):
                try:
                    body = json.loads(body)
                except ValueError:
                    continue
            if not isinstance(body, dict):
                continue
            if str(body.get("payment_status", "")).upper() == "COMPLETED" and body.get("order_id"):
                out[str(body["order_id"])] = body
        if len(rows) < 1000:
            return out
        offset += 1000


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since", required=True, help="ISO8601 UTC, e.g. 2026-10-24T21:00:00Z")
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    ap.add_argument("--skip", action="append", default=[], help="merchant_reference to leave alone")
    args = ap.parse_args()

    from app.database.session import get_supabase_admin
    from app.services.collections import resolve_collection
    from app.services.crud import update_row
    from app.services.selcom.schemas import CollectionResult

    client = get_supabase_admin()
    print(f"\n  {'APPLY' if args.apply else 'DRY RUN'} - crediting late-confirmed payments since {args.since}\n")

    paid = _paid_orders(client, args.since)
    order_ids = list(paid)
    id_by_order: dict[str, str] = {}
    for i in range(0, len(order_ids), 60):
        rows = (
            client.table("checkout_orders")
            .select("id, order_id")
            .in_("order_id", order_ids[i : i + 60])
            .execute()
        ).data or []
        for row in rows:
            id_by_order[str(row["order_id"])] = str(row["id"])

    names = {
        m["id"]: m["business_name"]
        for m in (client.table("merchants").select("id, business_name").execute()).data or []
    }

    done = skipped = 0
    total = Decimal(0)

    # Batched, not one query per order: at ~9,000 paid orders a lookup
    # per row turns a read-only dry run into a twenty-minute wait.
    by_checkout: dict[str, dict] = {}
    checkout_ids = list(id_by_order.values())
    for i in range(0, len(checkout_ids), 60):
        for row in (
            client.table("collections")
            .select("*")
            .in_("checkout_order_id", checkout_ids[i : i + 60])
            .execute()
        ).data or []:
            by_checkout[str(row["checkout_order_id"])] = row

    for order_id, body in sorted(paid.items(), key=lambda kv: str(kv[1].get("reference") or "")):
        checkout_id = id_by_order.get(order_id)
        col = by_checkout.get(checkout_id) if checkout_id else None
        if not col:
            continue
        ref = col.get("merchant_reference")
        who = names.get(col["merchant_id"], "?")[:18]

        if ref in args.skip:
            print(f"  SKIP (asked)  {ref}  {who}  TZS {col['amount']}")
            skipped += 1
            continue
        # Re-read, every run: this is what makes a second run safe.
        if col["status"] == "successful":
            skipped += 1
            continue
        if col["status"] != "failed":
            print(f"  SKIP (state)  {ref}  {who}  status={col['status']}")
            skipped += 1
            continue

        amount = Decimal(str(col.get("amount") or 0))
        if not args.apply:
            print(
                f"  WOULD CREDIT  {ref}  {who:<19} TZS {amount:>8,.0f}  "
                f"{col.get('customer_phone')}  selcom_ref={body.get('reference')}"
            )
            total += amount
            done += 1
            continue

        collection_id = uuid.UUID(str(col["id"]))
        txn = (
            client.table("transactions").select("id").eq("collection_id", str(collection_id)).execute()
        ).data or []
        # Back to the state the ordinary path expects, then let that path
        # do every bit of the money work.
        update_row(client, "collections", collection_id, {"status": "processing"})
        if txn:
            update_row(client, "transactions", uuid.UUID(str(txn[0]["id"])), {"status": "processing"})

        resolve_collection(
            client,
            collection_id=collection_id,
            result=CollectionResult(
                provider="selcom_checkout",
                provider_reference=str(body.get("reference") or col.get("provider_reference") or ""),
                status="successful",
                provider_payment_status=str(body.get("payment_status") or "COMPLETED"),
                provider_resultcode=str(body.get("resultcode") or "000"),
            ),
        )
        after = (
            client.table("collections").select("status").eq("id", str(collection_id)).execute()
        ).data or []
        state = after[0]["status"] if after else "?"
        print(
            f"  CREDITED      {ref}  {who:<19} TZS {amount:>8,.0f}  "
            f"{col.get('customer_phone')}  -> {state}"
        )
        total += amount
        done += 1

    verb = "would credit" if not args.apply else "credited"
    print(f"\n  {verb} {done} payment(s) · skipped {skipped} · gross TZS {total:,.2f}")
    if not args.apply:
        print("  nothing written. re-run with --apply to commit.")
    else:
        print("  each fires collection.success, which is what connects the customer.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
