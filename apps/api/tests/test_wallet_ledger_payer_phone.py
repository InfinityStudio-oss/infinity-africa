"""The payer's phone number on wallet ledger rows.

A merchant reading their wallet sees money arriving, but until now nothing
on the row said who sent it — reconciling a payment against a customer
meant opening the Collections page and matching by amount and time.

The phone is resolved on read, through transactions.collection_id ->
collections.customer_phone, rather than copied onto ledger_entries when the
entry is posted. These tests pin the consequences of that choice: it works
for entries posted before the feature existed, it cannot drift from the
collection, and it stays null where there genuinely is no payer.
"""

import uuid
from decimal import Decimal

from app.services.crud import insert_row
from app.services.ledger import (
    list_wallet_ledger,
    post_collection_entries,
    post_disbursement_entries,
)
from tests.factories import create_merchant


class _Pagination:
    def __init__(self, start: int = 0, end: int = 49):
        self.start = start
        self.end = end


def _merchant(fake_client) -> uuid.UUID:
    return uuid.UUID(create_merchant(fake_client)["id"])


def _collection(
    fake_client, merchant_id: uuid.UUID, *, phone: str | None, method: str = "STK_PUSH"
) -> uuid.UUID:
    row = insert_row(
        fake_client,
        "collections",
        {
            "merchant_id": str(merchant_id),
            "method": method,
            "amount": "1000.00",
            "currency": "TZS",
            "customer_phone": phone,
            "status": "successful",
        },
    )
    return uuid.UUID(row["id"])


def _transaction(
    fake_client,
    merchant_id: uuid.UUID,
    *,
    collection_id: uuid.UUID | None = None,
    type_: str = "collection",
) -> uuid.UUID:
    row = insert_row(
        fake_client,
        "transactions",
        {
            "merchant_id": str(merchant_id),
            "reference": f"TXN-{uuid.uuid4().hex[:8]}",
            "type": type_,
            "method": "STK_PUSH" if type_ == "collection" else "SELCOM_PESA",
            "collection_id": str(collection_id) if collection_id else None,
            "gross_amount": "1000",
            "fee_amount": "0",
            "net_amount": "1000",
            "currency": "TZS",
            "status": "successful",
        },
    )
    return uuid.UUID(row["id"])


def _credit(
    fake_client, merchant_id: uuid.UUID, transaction_id: uuid.UUID, *, net: str = "1000"
) -> None:
    post_collection_entries(
        fake_client,
        transaction_id=transaction_id,
        merchant_id=merchant_id,
        gross_amount=Decimal(net),
        fee_amount=Decimal(0),
        net_amount=Decimal(net),
        currency="TZS",
    )


def _ledger(fake_client, merchant_id: uuid.UUID) -> list[dict]:
    rows, _total = list_wallet_ledger(
        fake_client, merchant_id=merchant_id, currency="TZS", pagination=_Pagination()
    )
    return rows


# --- the payment shows who paid -------------------------------------------


def test_a_successful_payment_shows_the_payers_phone(fake_client):
    merchant_id = _merchant(fake_client)
    collection_id = _collection(fake_client, merchant_id, phone="+255712345678")
    _credit(
        fake_client, merchant_id, _transaction(fake_client, merchant_id, collection_id=collection_id)
    )

    assert _ledger(fake_client, merchant_id)[0]["payer_phone"] == "+255712345678"


def test_each_row_carries_its_own_payer(fake_client):
    """Two customers, two entries — the phones must not be shared between
    rows or applied from whichever collection was fetched first."""
    merchant_id = _merchant(fake_client)
    for phone in ("+255700000001", "+255700000002"):
        collection_id = _collection(fake_client, merchant_id, phone=phone)
        _credit(
            fake_client,
            merchant_id,
            _transaction(fake_client, merchant_id, collection_id=collection_id),
        )

    rows = _ledger(fake_client, merchant_id)

    assert {r["payer_phone"] for r in rows} == {"+255700000001", "+255700000002"}


def test_the_phone_follows_the_collection_rather_than_a_stored_copy(fake_client):
    """Resolved on read, so a correction to the collection is reflected —
    the property a denormalized column on ledger_entries would not have.
    The ledger amounts stay immutable either way; only the display of who
    paid is derived."""
    merchant_id = _merchant(fake_client)
    collection_id = _collection(fake_client, merchant_id, phone="+255700000009")
    _credit(
        fake_client, merchant_id, _transaction(fake_client, merchant_id, collection_id=collection_id)
    )

    fake_client.table("collections").update({"customer_phone": "+255711111111"}).eq(
        "id", str(collection_id)
    ).execute()

    assert _ledger(fake_client, merchant_id)[0]["payer_phone"] == "+255711111111"


def test_an_entry_posted_before_the_feature_existed_still_shows_a_phone(fake_client):
    """Nothing is written at posting time, so there is no backfill and no
    "null for everything older than the deploy" cliff. Any entry whose
    collection recorded a phone shows it."""
    merchant_id = _merchant(fake_client)
    collection_id = _collection(fake_client, merchant_id, phone="+255700000003")
    transaction_id = _transaction(fake_client, merchant_id, collection_id=collection_id)
    _credit(fake_client, merchant_id, transaction_id)

    # An entry row as it existed before this change: no phone stored on it.
    entry = next(
        r
        for r in fake_client.table("ledger_entries")._table.rows
        if r.get("transaction_id") == str(transaction_id)
    )
    assert "payer_phone" not in entry

    assert _ledger(fake_client, merchant_id)[0]["payer_phone"] == "+255700000003"


# --- and stays empty where there is genuinely no payer --------------------


def test_a_withdrawal_has_no_payer_phone(fake_client):
    """A payout goes to the merchant's own destination; there is no
    customer on the other side. Null, not the merchant's own number."""
    merchant_id = _merchant(fake_client)
    funding_collection = _collection(fake_client, merchant_id, phone="+255700000004")
    _credit(
        fake_client,
        merchant_id,
        _transaction(fake_client, merchant_id, collection_id=funding_collection),
        net="5000",
    )

    post_disbursement_entries(
        fake_client,
        transaction_id=_transaction(fake_client, merchant_id, type_="disbursement"),
        merchant_id=merchant_id,
        amount=Decimal(1000),
        currency="TZS",
    )

    debit = next(r for r in _ledger(fake_client, merchant_id) if r["direction"] == "debit")
    assert debit["payer_phone"] is None


def test_a_qr_scan_with_no_captured_phone_is_null_not_guessed(fake_client):
    """DYNAMIC_QR records no phone (see the column comment in
    supabase/migrations/20260814090009_collections.sql). The row must say
    "unknown", never invent a value."""
    merchant_id = _merchant(fake_client)
    collection_id = _collection(fake_client, merchant_id, phone=None, method="DYNAMIC_QR")
    _credit(
        fake_client, merchant_id, _transaction(fake_client, merchant_id, collection_id=collection_id)
    )

    assert _ledger(fake_client, merchant_id)[0]["payer_phone"] is None


# --- the money path is untouched ------------------------------------------


def test_adding_the_payer_phone_did_not_change_any_balance(fake_client):
    """The join is read-side only. Balances, direction and amounts must be
    exactly what they were before."""
    merchant_id = _merchant(fake_client)
    collection_id = _collection(fake_client, merchant_id, phone="+255700000005")
    post_collection_entries(
        fake_client,
        transaction_id=_transaction(fake_client, merchant_id, collection_id=collection_id),
        merchant_id=merchant_id,
        gross_amount=Decimal(1000),
        fee_amount=Decimal(30),
        net_amount=Decimal(970),
        currency="TZS",
    )

    row = _ledger(fake_client, merchant_id)[0]

    assert row["direction"] == "credit"
    assert Decimal(row["amount"]) == Decimal(970)
    assert Decimal(row["balance_before"]) == Decimal(0)
    assert Decimal(row["balance_after"]) == Decimal(970)
