#!/usr/bin/env python3
"""Credit payments whose transaction row was lost to INFINITYPAY-API-14.

`transactions.provider_reference` carries its own UNIQUE index and is
copied from the collection at push time; only the collection's copy is
ever refreshed afterwards. A superseded value therefore stays locked in
`transactions` while being free in `collections`, and when Selcom reuses
one the transaction insert raises 23505 *after* the customer has paid.
The collection survives, later resolves to `successful`, and has no
transaction behind it - so no ledger posting, and the merchant is never
credited.

The insert is guarded now (app/services/provider_references.py::
insert_transaction_tolerating_repeated_reference). This repairs the rows
that were already lost.

What it does, per collection, mirroring the success branch of
resolve_collection():

    create_processing_transaction()  - same fee calculation, no special case
    status -> successful
    post_collection_entries()        - the normal double-entry posting

What it deliberately does NOT do:

  * **enqueue a webhook.** These payments are days old and were settled
    with the customer by hand. Re-sending `collection.success` could
    activate a customer a second time, which is the merchant's loss and
    ours to have caused.
  * touch a wallet balance directly. The balance is derived from ledger
    entries; writing it would break the double entry this repairs.
  * invent anything. A collection that is not `successful`, or that
    already has a transaction, is skipped and reported.

Dry run by default. Nothing is written without --apply.

    python scripts/credit_missing_collection_transactions.py
    python scripts/credit_missing_collection_transactions.py --apply
"""

from __future__ import annotations

import argparse
import pathlib
import sys
import uuid
from decimal import Decimal

APP = pathlib.Path(__file__).resolve().parents[1] / "apps" / "api"
sys.path.insert(0, str(APP))

# The four collections found on 2026-10-25, all BennyWiFi, all
# API_WALLET_PUSH. Listed explicitly rather than discovered by query so
# this script can only ever touch rows a human has read.
TARGETS = [
    "1942173233",
    "1944713404",
    "1944714936",
    "1944714033",
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="actually write (default: dry run)")
    args = ap.parse_args()

    from app.database.session import get_supabase_admin
    from app.services.collections import create_processing_transaction
    from app.services.crud import update_row
    from app.services.ledger import post_collection_entries

    client = get_supabase_admin()
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"\n  {mode} - crediting collections with no transaction row\n")

    total_gross = total_net = Decimal(0)
    done = skipped = 0

    for ref in TARGETS:
        rows = (
            client.table("collections").select("*").eq("provider_reference", ref).execute()
        ).data or []
        if len(rows) != 1:
            print(f"  SKIP {ref}: expected 1 collection, found {len(rows)}")
            skipped += 1
            continue
        col = rows[0]
        cid = uuid.UUID(str(col["id"]))

        if col["status"] != "successful":
            print(f"  SKIP {ref}: status is {col['status']}, not successful")
            skipped += 1
            continue

        # Re-checked immediately before writing, every run.
        #
        # The question is "was the wallet credited", and the only honest
        # answer is whether ledger entries exist - NOT whether a
        # transaction row does. Crediting is three separate writes
        # (create the transaction, mark it successful, post the entries),
        # so an interruption between the first and the last leaves a
        # transaction with no posting and a merchant with no money.
        #
        # This guard used to ask only whether a transaction existed, and
        # printed "already credited" when it found one. A re-run would
        # therefore skip exactly the rows that most needed finishing, and
        # report success while doing it. Production had one such row
        # (TXN-20261024-FC86CC73, net TZS 488.50) from the same
        # non-atomic sequence inside resolve_collection.
        existing = (
            client.table("transactions").select("id, status").eq("collection_id", str(cid)).execute()
        ).data or []
        if existing:
            txn_id = str(existing[0]["id"])
            posted = (
                client.table("ledger_entries").select("id").eq("transaction_id", txn_id).limit(1).execute()
            ).data or []
            if posted:
                print(f"  SKIP {ref}: transaction {txn_id[:8]} is posted - already credited")
                skipped += 1
                continue
            # A transaction with no posting. Finishing it is the whole
            # point of the script, so this is reported loudly rather than
            # skipped quietly - but it is NOT repaired automatically here:
            # completing a half-written credit needs the same deliberate
            # look as making one.
            print(
                f"  ATTENTION {ref}: transaction {txn_id[:8]} exists with NO ledger entries "
                f"- the wallet was never credited. Not repaired automatically; see "
                f"scripts/ledger_integrity_check.py"
            )
            skipped += 1
            continue

        merchant_id = uuid.UUID(str(col["merchant_id"]))
        amount = Decimal(str(col["amount"]))
        currency = col["currency"]
        method = col.get("method") or "WALLET_PUSH"

        if not args.apply:
            from app.services.collection_pricing import calculate_collection_fee

            fee = calculate_collection_fee(
                client, merchant_id=merchant_id, amount=amount, channel=method
            )
            print(
                f"  WOULD CREDIT {ref}  collection {str(cid)[:8]}  "
                f"gross {amount:,.2f} fee {fee:,.2f} net {amount - fee:,.2f} {currency}"
            )
            total_gross += amount
            total_net += amount - fee
            done += 1
            continue

        txn = create_processing_transaction(
            client,
            merchant_id=merchant_id,
            method=method,
            collection_id=str(cid),
            provider_reference=col.get("provider_reference"),
            amount=amount,
            currency=currency,
        )
        txn_id = uuid.UUID(str(txn["id"]))
        update_row(client, "transactions", txn_id, {"status": "successful"})
        post_collection_entries(
            client,
            transaction_id=txn_id,
            merchant_id=merchant_id,
            gross_amount=Decimal(str(txn["gross_amount"])),
            fee_amount=Decimal(str(txn["fee_amount"])),
            net_amount=Decimal(str(txn["net_amount"])),
            currency=currency,
        )
        print(
            f"  CREDITED {ref}  txn {str(txn_id)[:8]}  "
            f"gross {txn['gross_amount']} fee {txn['fee_amount']} net {txn['net_amount']} {currency}"
        )
        total_gross += Decimal(str(txn["gross_amount"]))
        total_net += Decimal(str(txn["net_amount"]))
        done += 1

    verb = "would credit" if not args.apply else "credited"
    print(f"\n  {verb} {done} payment(s) · skipped {skipped}")
    print(f"  gross TZS {total_gross:,.2f} · net to merchant TZS {total_net:,.2f}")
    if not args.apply:
        print("\n  nothing was written. re-run with --apply to commit.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
