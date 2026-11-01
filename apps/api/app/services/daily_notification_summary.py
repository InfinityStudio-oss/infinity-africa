"""One email a day, for merchants who asked not to be told 540 times.

A merchant on `collection_notification_frequency = 'daily_summary'` gets
no per-payment email (app/services/email.py suppresses it there) and one
message the next morning covering the previous Dar es Salaam day.

**The day is the merchant's, not UTC's.** Tanzania is UTC+3, so a
calendar day runs 21:00 to 21:00 in UTC. Summarising a UTC day would put
the first three hours of every evening into the wrong report, and a
merchant reconciling against their own records would find the totals
nearly-but-not-quite right — the worst kind of wrong for a money figure.

**Sent once, guaranteed by the database.** The sweep runs on a timer
across replicas, so "did we already send today's?" cannot be answered in
process memory: two replicas waking together would both read no. Claiming
the day is an INSERT into merchant_daily_notification_summaries, whose
unique (merchant_id, summary_date) makes the second one lose. The row is
written whatever the outcome — a failed send that left no trace would be
retried forever, and a skipped one would be re-evaluated every tick.

**Nothing here can affect a payment.** It reads transactions and
merchants, writes its own table, and talks to the email provider. No
ledger, no collection, no disbursement, no balance.
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from supabase import Client

from app.core.time import dar_es_salaam_day_start_utc
from app.services.crud import fetch_all
from app.services.email import send_daily_collection_summary_email
from app.services.merchant_notifications import get_notification_settings

logger = logging.getLogger("infinity.daily_summary")

EAT = timezone(timedelta(hours=3))


def _previous_local_day(now: datetime) -> tuple[date, str, str]:
    """Yesterday on the Tanzanian calendar, and the UTC window for it.

    Returns (date being reported, window start ISO, window end ISO). The
    end is this morning's local midnight, exclusive — so a payment at
    23:59:59 local belongs to the day it was made and one at 00:00:00
    does not.
    """
    today_start = dar_es_salaam_day_start_utc(now)
    start_dt = datetime.fromisoformat(today_start.replace("Z", "+00:00")) - timedelta(days=1)
    reported = (start_dt.astimezone(EAT)).date()
    return reported, start_dt.isoformat().replace("+00:00", "Z"), today_start


def _already_claimed(client: Client, merchant_id: str, summary_date: date) -> bool:
    try:
        rows = (
            client.table("merchant_daily_notification_summaries")
            .select("id")
            .eq("merchant_id", merchant_id)
            .eq("summary_date", summary_date.isoformat())
            .execute()
        ).data
    except Exception:  # noqa: BLE001 - a read failure must not double-send
        logger.warning("daily_summary_claim_check_failed merchant_id=%s", merchant_id)
        return True
    return bool(rows)


def _claim(client: Client, merchant_id: str, summary_date: date, **fields) -> bool:
    """Take the day, or discover somebody else already has.

    The INSERT is the claim. A unique-violation here is not an error — it
    is another replica having got there first, which is exactly what the
    constraint is for.
    """
    try:
        client.table("merchant_daily_notification_summaries").insert(
            {
                "merchant_id": merchant_id,
                "summary_date": summary_date.isoformat(),
                **fields,
            }
        ).execute()
        return True
    except Exception as exc:  # noqa: BLE001
        if "23505" in str(exc) or "duplicate key" in str(exc).lower():
            logger.info("daily_summary_already_claimed merchant_id=%s", merchant_id)
            return False
        logger.warning("daily_summary_claim_failed merchant_id=%s", merchant_id)
        return False


def send_daily_collection_summaries(client: Client, *, now: datetime | None = None) -> dict:
    """Send yesterday's summary to every merchant who wants one.

    Returns counts for the log. Never raises: this runs on a scheduler,
    and one merchant's bad address must not stop the other sixty-nine
    getting theirs.
    """
    now = now or datetime.now(timezone.utc)
    reported, window_start, window_end = _previous_local_day(now)

    try:
        wanting = (
            client.table("merchant_notification_settings")
            .select("merchant_id, primary_notification_email, collection_notifications_enabled,"
                    " collection_notification_frequency")
            .eq("collection_notification_frequency", "daily_summary")
            .eq("collection_notifications_enabled", True)
            .execute()
        ).data or []
    except Exception:
        logger.exception("daily_summary_settings_unreadable")
        return {"date": reported.isoformat(), "sent": 0, "skipped": 0, "failed": 0, "considered": 0}

    sent = skipped = failed = 0

    for row in wanting:
        merchant_id = str(row["merchant_id"])
        if _already_claimed(client, merchant_id, reported):
            continue

        # Re-read the preference immediately before sending. The list
        # above may be minutes old by the time this merchant's turn
        # comes, and a Super Admin switching them off in between should
        # not then receive one.
        current = get_notification_settings(client, uuid.UUID(merchant_id)) or {}
        if not current.get("collection_notifications_enabled") or current.get(
            "collection_notification_frequency"
        ) != "daily_summary":
            continue

        try:
            # merchant_id bound as a default, not captured: this closure
            # is rebuilt every iteration, and a late-binding capture
            # would read whichever merchant the loop had reached by the
            # time fetch_all paged. It happens to work while the call is
            # immediate; it is one refactor away from emailing a merchant
            # another merchant's totals.
            payments = fetch_all(
                lambda mid=merchant_id: client.table("transactions")
                .select("gross_amount, currency")
                .eq("merchant_id", mid)
                .eq("type", "collection")
                .eq("status", "successful")
                .gte("created_at", window_start)
                .lt("created_at", window_end)
            )
        except Exception:  # noqa: BLE001 - one merchant's failure is not the sweep's
            logger.warning("daily_summary_payments_unreadable merchant_id=%s", merchant_id)
            failed += 1
            continue

        count = len(payments)
        gross = sum((Decimal(str(p["gross_amount"] or 0)) for p in payments), Decimal(0))
        currency = (payments[0].get("currency") if payments else None) or "TZS"

        if count == 0:
            # A quiet day. Claimed so it is not reconsidered every tick,
            # but no email — "you received nothing yesterday" is the kind
            # of message that makes people stop reading the ones that
            # matter.
            _claim(
                client,
                merchant_id,
                reported,
                collection_count=0,
                gross_amount="0",
                currency=currency,
                status="skipped",
                detail="no successful collections on this day",
            )
            skipped += 1
            continue

        merchant = None
        try:
            merchant = (
                client.table("merchants")
                .select("id, business_name, contact_email")
                .eq("id", merchant_id)
                .execute()
            ).data
            merchant = merchant[0] if merchant else None
        except Exception:  # noqa: BLE001
            merchant = None

        if not merchant:
            logger.warning("daily_summary_merchant_missing merchant_id=%s", merchant_id)
            failed += 1
            continue

        # Same recipient rule as the per-payment email: the configured
        # address, or the account's own. A merchant moving between the
        # two frequencies must not find their emails going somewhere
        # different.
        recipient = (current.get("primary_notification_email") or "").strip() or (
            merchant.get("contact_email") or ""
        ).strip()
        if not recipient:
            _claim(
                client,
                merchant_id,
                reported,
                collection_count=count,
                gross_amount=str(gross),
                currency=currency,
                status="skipped",
                detail="no recipient address",
            )
            skipped += 1
            continue

        # Claim BEFORE sending. If the send then fails, the day is still
        # taken and nobody gets a second copy — the failure is recorded
        # and visible instead. The other order risks sending twice, which
        # is the one outcome this whole table exists to prevent.
        if not _claim(
            client,
            merchant_id,
            reported,
            collection_count=count,
            gross_amount=str(gross),
            currency=currency,
            recipient_email=recipient,
            status="sent",
        ):
            continue

        try:
            send_daily_collection_summary_email(
                client,
                merchant=merchant,
                recipient=recipient,
                summary_date=reported,
                collection_count=count,
                gross_amount=gross,
                currency=currency,
            )
            sent += 1
        except Exception:
            logger.exception("daily_summary_send_failed merchant_id=%s", merchant_id)
            failed += 1

    return {
        "date": reported.isoformat(),
        "considered": len(wanting),
        "sent": sent,
        "skipped": skipped,
        "failed": failed,
    }
