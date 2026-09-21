"""Double-entry ledger posting for successful collections/disbursements.

Every posting here traces back to a transactions row and is enforced
balanced (debits == credits per transaction_id) by a deferred constraint
trigger in the database itself — see
supabase/migrations/20260814090013_ledger_entries.sql. This module just has
to get the debit/credit split right; the database refuses to commit if it
doesn't.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from supabase import Client

from app.core.errors import InsufficientBalanceError
from app.core.pagination import PaginationParams
from app.core.time import dar_es_salaam_day_bounds_utc
from app.services.crud import execute_maybe_single, get_by_id, insert_row


def _get_or_create_ledger_account(
    client: Client,
    *,
    merchant_id: uuid.UUID | None,
    purpose: str,
    account_type: str,
    currency: str,
) -> uuid.UUID:
    query = client.table("ledger_accounts").select("id").eq("purpose", purpose).eq("currency", currency)
    query = query.eq("merchant_id", str(merchant_id)) if merchant_id else query.is_("merchant_id", "null")
    existing = execute_maybe_single(query.maybe_single())

    if existing:
        return uuid.UUID(existing["id"])

    try:
        row = insert_row(
            client,
            "ledger_accounts",
            {
                "merchant_id": str(merchant_id) if merchant_id else None,
                "name": _account_name(purpose, merchant_id),
                "account_type": account_type,
                "purpose": purpose,
                "currency": currency,
                "balance": "0",
            },
        )
    except Exception:
        # Lost a race with a concurrent get-or-create for the same account —
        # the unique index on ledger_accounts guarantees only one row can
        # exist, so re-fetch rather than fail the whole request.
        existing = execute_maybe_single(query.maybe_single())
        if existing:
            return uuid.UUID(existing["id"])
        raise

    return uuid.UUID(row["id"])


def _account_name(purpose: str, merchant_id: uuid.UUID | None) -> str:
    label = purpose.replace("_", " ").title()
    return f"{label} ({merchant_id})" if merchant_id else f"{label} (Platform)"


def _post_entries(client: Client, entries: list[dict]) -> list[dict]:
    """Posts a batch of ledger_entries and updates each account's cached
    balance atomically, via the post_ledger_entries Postgres function —
    supabase-py can't wrap multiple inserts/updates in one client-side
    transaction, and the deferred debits=credits trigger needs the whole
    batch to land in a single transaction to check correctly. The same
    function also rejects the whole batch, atomically, if it would take a
    merchant_wallet balance negative — see
    supabase/migrations/20260814140001_post_ledger_entries_balance_check.sql.

    Returns the inserted rows exactly as the database wrote them — each one
    carries its own balance_before/balance_after snapshot (see
    supabase/migrations/20260828020000_post_ledger_entries_balance_snapshot.sql),
    captured atomically under the same row lock used for the balance-check
    above, not re-derived here. Callers use this to denormalize the
    merchant-wallet leg's snapshot onto the transactions row — see
    _record_wallet_snapshot below.
    """
    try:
        result = client.rpc("post_ledger_entries", {"p_entries": entries}).execute()
    except InsufficientBalanceError:
        raise
    except Exception as exc:
        if "INSUFFICIENT_BALANCE" in str(exc):
            raise InsufficientBalanceError("Insufficient balance for this operation") from exc
        raise
    return result.data or []


def _record_wallet_snapshot(
    client: Client,
    *,
    transaction_id: uuid.UUID,
    wallet_account_id: uuid.UUID,
    posted_entries: list[dict],
) -> None:
    """Denormalizes the merchant-wallet leg's balance_before/after/direction
    (captured atomically by _post_entries, above) onto the transactions row,
    so the merchant/admin Transactions views can display it without an
    extra join per row. Best-effort by design: if this update fails for any
    reason, the authoritative snapshot still exists on the ledger_entries
    row itself (immutable, already committed) — a transactions row simply
    falls back to showing "not available" for these three fields rather
    than blocking the financial posting that already succeeded."""
    wallet_entry = next(
        (e for e in posted_entries if e.get("ledger_account_id") == str(wallet_account_id)), None
    )
    if not wallet_entry:
        return
    try:
        client.table("transactions").update(
            {
                "balance_before": wallet_entry.get("balance_before"),
                "balance_after": wallet_entry.get("balance_after"),
                "direction": wallet_entry.get("direction"),
            }
        ).eq("id", str(transaction_id)).execute()
    except Exception:  # noqa: BLE001, S110 — display-only denormalization, never blocks a posting
        pass


def get_wallet_balance(client: Client, *, merchant_id: uuid.UUID, currency: str) -> Decimal:
    """The merchant's current available balance — used to validate a
    disbursement up front, before even creating its row. Not itself the
    race-proof check (two concurrent reads can both see the same balance);
    that guarantee comes from post_ledger_entries' atomic check at actual
    deduction time, this is just for a fast, friendly rejection."""
    account_id = _get_or_create_ledger_account(
        client, merchant_id=merchant_id, purpose="merchant_wallet", account_type="liability", currency=currency
    )
    account = get_by_id(client, "ledger_accounts", account_id)
    return Decimal(str(account["balance"])) if account else Decimal(0)


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _wallet_ledger_entries(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    currency: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict]:
    """Every ledger_entries row for the merchant's wallet account, newest
    first, with a per-row balance_after computed here — ledger_entries
    itself stores no running balance (only ledger_accounts.balance, the
    current cached total; see supabase/migrations/20260814090012_ledger_accounts.sql).
    Credits increase the wallet, debits decrease it (a `merchant_wallet`
    row is a liability account) — same sign convention already used by
    post_collection_entries/post_disbursement_entries/reverse_disbursement_entries
    above.

    Always replays the COMPLETE, unfiltered history first to compute
    correct running balances, then applies start_date/end_date afterward —
    filtering before the replay would make the first entry inside the
    window look like it opened at balance 0, which is wrong. Fetches
    everything before paginating in Python — acceptable at merchant-portal
    scale, the same tradeoff app/services/merchant_overview.py already
    makes; revisit with a real query/materialized view if this ever needs
    to scale past that.

    Joins each entry onto its transactions row (type/reference/provider_
    reference/method/fee_amount/net_amount/status) for the Wallet Ledger's
    audit columns — batched in one query, not per-row."""
    account_id = _get_or_create_ledger_account(
        client, merchant_id=merchant_id, purpose="merchant_wallet", account_type="liability", currency=currency
    )
    entries = (
        client.table("ledger_entries")
        .select("*")
        .eq("ledger_account_id", str(account_id))
        .order("created_at", desc=False)
        .execute()
        .data
        or []
    )

    transaction_ids = {e["transaction_id"] for e in entries if e.get("transaction_id")}
    transactions_by_id: dict[str, dict] = {}
    if transaction_ids:
        txn_rows = client.table("transactions").select("*").in_("id", list(transaction_ids)).execute().data or []
        transactions_by_id = {t["id"]: t for t in txn_rows}

    running = Decimal(0)
    enriched = []
    for entry in entries:
        amount = Decimal(str(entry["amount"]))
        opening = running
        running += amount if entry["direction"] == "credit" else -amount
        # Newer rows already carry their own balance_before/after, captured
        # atomically at posting time (see
        # supabase/migrations/20260828020000_post_ledger_entries_balance_snapshot.sql)
        # — prefer those; older rows (posted before that column existed)
        # fall back to this replay, which is exactly as reliable since
        # ledger_entries is immutable and this scans the complete history.
        balance_before = entry.get("balance_before")
        balance_after = entry.get("balance_after")
        txn = transactions_by_id.get(entry.get("transaction_id")) or {}
        enriched.append(
            {
                "id": entry["id"],
                "transaction_id": entry.get("transaction_id"),
                "date": entry["created_at"],
                "description": entry.get("description"),
                "direction": entry["direction"],
                "amount": str(amount),
                "balance_before": str(balance_before) if balance_before is not None else str(opening),
                "balance_after": str(balance_after) if balance_after is not None else str(running),
                "type": txn.get("type"),
                "reference": txn.get("reference"),
                "provider_reference": txn.get("provider_reference"),
                "method": txn.get("method"),
                "fee_amount": txn.get("fee_amount"),
                "net_amount": txn.get("net_amount"),
                "status": txn.get("status"),
            }
        )
    enriched.reverse()  # newest first, matching every other list endpoint's convention

    start_utc, end_utc = dar_es_salaam_day_bounds_utc(start_date, end_date)
    if start_utc is not None or end_utc is not None:
        enriched = [
            e
            for e in enriched
            if (start_utc is None or _parse_iso(e["date"]) >= start_utc)
            and (end_utc is None or _parse_iso(e["date"]) < end_utc)
        ]

    return enriched


def list_wallet_ledger(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    currency: str,
    pagination: PaginationParams,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[list[dict], int]:
    enriched = _wallet_ledger_entries(
        client, merchant_id=merchant_id, currency=currency, start_date=start_date, end_date=end_date
    )
    total = len(enriched)
    page = enriched[pagination.start : pagination.end + 1]
    return page, total


def export_wallet_ledger_rows(
    client: Client,
    *,
    merchant_id: uuid.UUID,
    currency: str,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict]:
    """Same rows list_wallet_ledger's callers page through, but complete
    and unpaginated — for a one-shot Excel export of the whole filtered
    range."""
    return _wallet_ledger_entries(
        client, merchant_id=merchant_id, currency=currency, start_date=start_date, end_date=end_date
    )


def post_collection_entries(
    client: Client,
    *,
    transaction_id: uuid.UUID,
    merchant_id: uuid.UUID,
    gross_amount: Decimal,
    fee_amount: Decimal,
    net_amount: Decimal,
    currency: str,
) -> None:
    """A customer's payment lands in InfinityPay's settlement account; the
    merchant's wallet balance grows by the net amount, and the fee becomes
    platform revenue. Debit (settlement_clearing) == credits (wallet + fee).
    """
    settlement_account_id = _get_or_create_ledger_account(
        client, merchant_id=None, purpose="settlement_clearing", account_type="asset", currency=currency
    )
    wallet_account_id = _get_or_create_ledger_account(
        client,
        merchant_id=merchant_id,
        purpose="merchant_wallet",
        account_type="liability",
        currency=currency,
    )

    entries = [
        {
            "transaction_id": str(transaction_id),
            "ledger_account_id": str(settlement_account_id),
            "direction": "debit",
            "amount": str(gross_amount),
            "currency": currency,
            "description": "Customer payment received into settlement",
        },
        {
            "transaction_id": str(transaction_id),
            "ledger_account_id": str(wallet_account_id),
            "direction": "credit",
            "amount": str(net_amount),
            "currency": currency,
            "description": "Merchant wallet credited (net of fee)",
        },
    ]

    if fee_amount > 0:
        revenue_account_id = _get_or_create_ledger_account(
            client, merchant_id=None, purpose="platform_revenue", account_type="revenue", currency=currency
        )
        entries.append(
            {
                "transaction_id": str(transaction_id),
                "ledger_account_id": str(revenue_account_id),
                "direction": "credit",
                "amount": str(fee_amount),
                "currency": currency,
                "description": "Platform fee revenue",
            }
        )

    posted = _post_entries(client, entries)
    _record_wallet_snapshot(
        client, transaction_id=transaction_id, wallet_account_id=wallet_account_id, posted_entries=posted
    )


def post_disbursement_entries(
    client: Client,
    *,
    transaction_id: uuid.UUID,
    merchant_id: uuid.UUID,
    amount: Decimal,
    currency: str,
    fee_amount: Decimal = Decimal(0),
) -> None:
    """A payout draws down the merchant's wallet by `amount + fee_amount`
    (the total reserved), sends `amount` out through InfinityPay's
    settlement account to the recipient, and books `fee_amount` (when > 0)
    as platform revenue — the withdrawal-side mirror of
    post_collection_entries' existing fee leg. Debit (wallet) == credits
    (settlement + revenue)."""
    wallet_account_id = _get_or_create_ledger_account(
        client,
        merchant_id=merchant_id,
        purpose="merchant_wallet",
        account_type="liability",
        currency=currency,
    )
    settlement_account_id = _get_or_create_ledger_account(
        client, merchant_id=None, purpose="settlement_clearing", account_type="asset", currency=currency
    )

    entries = [
        {
            "transaction_id": str(transaction_id),
            "ledger_account_id": str(wallet_account_id),
            "direction": "debit",
            "amount": str(amount + fee_amount),
            "currency": currency,
            "description": "Merchant wallet debited for payout + fees",
        },
        {
            "transaction_id": str(transaction_id),
            "ledger_account_id": str(settlement_account_id),
            "direction": "credit",
            "amount": str(amount),
            "currency": currency,
            "description": "Payout disbursed from settlement",
        },
    ]

    if fee_amount > 0:
        revenue_account_id = _get_or_create_ledger_account(
            client, merchant_id=None, purpose="platform_revenue", account_type="revenue", currency=currency
        )
        entries.append(
            {
                "transaction_id": str(transaction_id),
                "ledger_account_id": str(revenue_account_id),
                "direction": "credit",
                "amount": str(fee_amount),
                "currency": currency,
                "description": "Withdrawal fee revenue",
            }
        )

    posted = _post_entries(client, entries)
    _record_wallet_snapshot(
        client, transaction_id=transaction_id, wallet_account_id=wallet_account_id, posted_entries=posted
    )


def post_refund_entry(
    client: Client,
    *,
    transaction_id: uuid.UUID,
    merchant_id: uuid.UUID,
    amount: Decimal,
    currency: str,
) -> None:
    """A refund draws down the merchant's wallet back out through
    settlement, same shape as post_disbursement_entries — the difference is
    only in which transactions row it's posted against (a new type='refund'
    row, not the original collection's, so each transaction_id's own
    debits/credits still balance independently). See
    app/services/disputes_service.py.update_refund_status()."""
    wallet_account_id = _get_or_create_ledger_account(
        client,
        merchant_id=merchant_id,
        purpose="merchant_wallet",
        account_type="liability",
        currency=currency,
    )
    settlement_account_id = _get_or_create_ledger_account(
        client, merchant_id=None, purpose="settlement_clearing", account_type="asset", currency=currency
    )

    entries = [
        {
            "transaction_id": str(transaction_id),
            "ledger_account_id": str(wallet_account_id),
            "direction": "debit",
            "amount": str(amount),
            "currency": currency,
            "description": "Merchant wallet debited for refund",
        },
        {
            "transaction_id": str(transaction_id),
            "ledger_account_id": str(settlement_account_id),
            "direction": "credit",
            "amount": str(amount),
            "currency": currency,
            "description": "Refund returned to customer via settlement",
        },
    ]

    posted = _post_entries(client, entries)
    _record_wallet_snapshot(
        client, transaction_id=transaction_id, wallet_account_id=wallet_account_id, posted_entries=posted
    )


def reverse_collection_entries(
    client: Client,
    *,
    transaction_id: uuid.UUID,
    merchant_id: uuid.UUID,
    gross_amount: Decimal,
    fee_amount: Decimal,
    net_amount: Decimal,
    currency: str,
) -> None:
    """The opposite of post_collection_entries(), against the *same*
    transaction_id (same convention as reverse_disbursement_entries below)
    — for a collection that was already marked successful and credited,
    then later reported reversed/rejected by the provider (e.g. Selcom
    reversing an M-Pesa "own till" payment after the fact). Unlike
    reverse_disbursement_entries, this *debits* the wallet, so it can
    raise InsufficientBalanceError if the merchant no longer has the
    funds available (already withdrawn) — callers must handle that case
    explicitly rather than letting it crash the caller."""
    settlement_account_id = _get_or_create_ledger_account(
        client, merchant_id=None, purpose="settlement_clearing", account_type="asset", currency=currency
    )
    wallet_account_id = _get_or_create_ledger_account(
        client,
        merchant_id=merchant_id,
        purpose="merchant_wallet",
        account_type="liability",
        currency=currency,
    )

    entries = [
        {
            "transaction_id": str(transaction_id),
            "ledger_account_id": str(wallet_account_id),
            "direction": "debit",
            "amount": str(net_amount),
            "currency": currency,
            "description": "Merchant wallet credit reversed (collection reversed by provider)",
        },
        {
            "transaction_id": str(transaction_id),
            "ledger_account_id": str(settlement_account_id),
            "direction": "credit",
            "amount": str(gross_amount),
            "currency": currency,
            "description": "Settlement clearing reversed (collection reversed by provider)",
        },
    ]

    if fee_amount > 0:
        revenue_account_id = _get_or_create_ledger_account(
            client, merchant_id=None, purpose="platform_revenue", account_type="revenue", currency=currency
        )
        entries.append(
            {
                "transaction_id": str(transaction_id),
                "ledger_account_id": str(revenue_account_id),
                "direction": "debit",
                "amount": str(fee_amount),
                "currency": currency,
                "description": "Platform fee revenue reversed (collection reversed by provider)",
            }
        )

    posted = _post_entries(client, entries)
    _record_wallet_snapshot(
        client, transaction_id=transaction_id, wallet_account_id=wallet_account_id, posted_entries=posted
    )


def reverse_disbursement_entries(
    client: Client,
    *,
    transaction_id: uuid.UUID,
    merchant_id: uuid.UUID,
    amount: Decimal,
    currency: str,
    fee_amount: Decimal = Decimal(0),
) -> None:
    """Reverses a disbursement reservation that didn't go through: the
    opposite entries against the *same* transaction_id (full amount +
    fee_amount credited back to the wallet), so the transaction nets to
    zero — exactly what a reserved-then-failed payout should look like in
    the ledger. Crediting the wallet back only increases its balance, so
    this never trips the insufficient-balance guard."""
    wallet_account_id = _get_or_create_ledger_account(
        client,
        merchant_id=merchant_id,
        purpose="merchant_wallet",
        account_type="liability",
        currency=currency,
    )
    settlement_account_id = _get_or_create_ledger_account(
        client, merchant_id=None, purpose="settlement_clearing", account_type="asset", currency=currency
    )

    entries = [
        {
            "transaction_id": str(transaction_id),
            "ledger_account_id": str(wallet_account_id),
            "direction": "credit",
            "amount": str(amount + fee_amount),
            "currency": currency,
            "description": "Merchant wallet reservation reversed (payout failed)",
        },
        {
            "transaction_id": str(transaction_id),
            "ledger_account_id": str(settlement_account_id),
            "direction": "debit",
            "amount": str(amount),
            "currency": currency,
            "description": "Settlement clearing reversed (payout failed)",
        },
    ]

    if fee_amount > 0:
        revenue_account_id = _get_or_create_ledger_account(
            client, merchant_id=None, purpose="platform_revenue", account_type="revenue", currency=currency
        )
        entries.append(
            {
                "transaction_id": str(transaction_id),
                "ledger_account_id": str(revenue_account_id),
                "direction": "debit",
                "amount": str(fee_amount),
                "currency": currency,
                "description": "Withdrawal fee revenue reversed (payout failed)",
            }
        )

    posted = _post_entries(client, entries)
    _record_wallet_snapshot(
        client, transaction_id=transaction_id, wallet_account_id=wallet_account_id, posted_entries=posted
    )
