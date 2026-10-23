#!/usr/bin/env python3
"""Health check for one merchant, for watching a partner closely.

Read-only. Takes a merchant name fragment or merchant code and reports
what actually matters for a growing integration: whether payments reach
them, whether money reaches their wallet, and whether their own endpoint
is keeping up.

    python scripts/merchant_health.py BennyWiFi
    python scripts/merchant_health.py 27004818 --days 7

Why these numbers and not the obvious ones:

**Latency is measured over successful payments only.** Mixing in expired
ones measures how long a customer took to ignore an STK prompt, not how
fast the platform settles. That mistake made the median look like eleven
minutes when payments that actually complete were settling in seventy
seconds.

**Expiry is reported separately from failure.** A customer who never
entered their PIN is a conversion problem for the merchant, not a fault
on the platform, and the two need different responses.

**Undelivered money events are listed individually.** A merchant whose
endpoint was down has customers who paid and received nothing, and the
only way to close that is to hand them the references.
"""

from __future__ import annotations

import argparse
import datetime as dt
import pathlib
import re
import sys
from collections import Counter
from decimal import Decimal

try:
    import httpx
except ImportError:  # pragma: no cover
    sys.exit("httpx is required: pip install httpx")

ENV = pathlib.Path(__file__).resolve().parents[1] / "apps" / "api" / ".env"
MONEY_EVENTS = ("collection.success", "disbursement.success")


def env(name: str) -> str | None:
    if not ENV.is_file():
        return None
    m = re.search(rf"^{name}=(.*)$", ENV.read_text(encoding="utf-8"), re.M)
    return m.group(1).strip().strip('"').strip("'") if m else None


def page(client, base, path, select, extra=""):
    """PostgREST caps a response at 1000 rows whatever limit you ask for."""
    out, offset = [], 0
    while True:
        r = client.get(
            f"{base}/rest/v1/{path}?select={select}{extra}"
            f"&order=created_at.asc&limit=1000&offset={offset}"
        )
        if r.status_code >= 400:
            break
        batch = r.json()
        out += batch
        if len(batch) < 1000:
            break
        offset += 1000
    return out


def secs_between(a: str, b: str) -> float:
    return (
        dt.datetime.fromisoformat(b.replace("Z", "+00:00"))
        - dt.datetime.fromisoformat(a.replace("Z", "+00:00"))
    ).total_seconds()


def pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:.1f}%" if whole else "-"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("merchant", help="business name fragment, or merchant code")
    ap.add_argument("--days", type=int, default=1, help="window in days (default 1)")
    args = ap.parse_args()

    base, key = env("SUPABASE_URL"), env("SUPABASE_SERVICE_ROLE_KEY")
    if not base or not key:
        print("  SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY not found in apps/api/.env")
        return 2

    now = dt.datetime.now(dt.timezone.utc)
    since = (now - dt.timedelta(days=args.days)).isoformat().replace("+00:00", "Z")
    client = httpx.Client(
        headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=120
    )

    with client:
        q = (
            f"merchant_code=eq.{args.merchant}"
            if args.merchant.isdigit()
            else f"business_name=ilike.*{args.merchant}*"
        )
        found = client.get(
            f"{base}/rest/v1/merchants?select=id,business_name,merchant_code,status,"
            f"webhook_url,webhook_secret_encrypted,created_at&{q}"
        ).json()
        if not found:
            print(f"  no merchant matching {args.merchant!r}")
            return 1
        if len(found) > 1:
            print("  several matched - be more specific:")
            for m in found:
                print(f"    {m['business_name']} ({m['merchant_code']})")
            return 1

        m = found[0]
        mid = str(m["id"])
        print(f"\n  {m['business_name']}  ({m['merchant_code']})")
        print(f"  status {m['status']} · joined {str(m.get('created_at'))[:10]} · "
              f"window {args.days}d · as of {now.isoformat()[:19]}Z")
        signed = bool(m.get("webhook_secret_encrypted"))
        print(f"  webhook {'signed' if signed else 'UNSIGNED'} · {m.get('webhook_url') or '(none)'}")

        # --- payments ---------------------------------------------------
        cols = page(client, base, "collections",
                    "id,status,amount,created_at,updated_at,failure_reason",
                    f"&merchant_id=eq.{mid}&created_at=gte.{since}")
        ok = [c for c in cols if c["status"] == "successful"]
        open_ = [c for c in cols if c["status"] in ("pending", "processing")]
        expired = [c for c in cols if (c.get("failure_reason") or "") == "expired"]
        declined = [c for c in cols
                    if c["status"] == "failed" and (c.get("failure_reason") or "") != "expired"]

        print(f"\n  PAYMENTS   {len(cols)} started")
        print(f"    successful     {len(ok):>5}  {pct(len(ok), len(cols))}")
        print(f"    expired        {len(expired):>5}  {pct(len(expired), len(cols))}"
              f"   (customer never completed the prompt)")
        print(f"    declined       {len(declined):>5}  {pct(len(declined), len(cols))}")
        print(f"    still open     {len(open_):>5}")
        if ok:
            lat = sorted(secs_between(c["created_at"], c["updated_at"]) for c in ok)
            print(f"    settle time    median {lat[len(lat)//2]:.0f}s · "
                  f"p90 {lat[int(len(lat)*0.9)]:.0f}s   (successful only)")

        # --- money ------------------------------------------------------
        tx = page(client, base, "transactions",
                  "id,status,gross_amount,fee_amount,net_amount,collection_id",
                  f"&merchant_id=eq.{mid}&type=eq.collection&created_at=gte.{since}")
        good = [t for t in tx if t["status"] == "successful"]
        gross = sum(Decimal(str(t.get("gross_amount") or 0)) for t in good)
        fee = sum(Decimal(str(t.get("fee_amount") or 0)) for t in good)
        print(f"\n  MONEY      gross TZS {gross:,.2f} · your revenue TZS {fee:,.2f} · "
              f"to merchant TZS {gross - fee:,.2f}")

        linked = {str(t.get("collection_id")) for t in tx if t.get("collection_id")}
        orphans = [c for c in ok if str(c["id"]) not in linked]
        if orphans:
            print(f"    !! {len(orphans)} successful payment(s) with NO transaction "
                  f"- merchant NOT credited:")
            for c in orphans[:10]:
                print(f"       {c['created_at'][:19]}Z  TZS {c['amount']}  id={str(c['id'])[:8]}")

        # --- their endpoint ---------------------------------------------
        ev = page(client, base, "webhook_events",
                  "id,event_name,status,attempts,response_status_code,created_at,payload",
                  f"&merchant_id=eq.{mid}&created_at=gte.{since}")
        by = Counter(e["status"] for e in ev)
        print(f"\n  THEIR ENDPOINT   {len(ev)} events · delivered {by.get('delivered',0)} "
              f"({pct(by.get('delivered',0), len(ev))}) · failed {by.get('failed',0)} · "
              f"queued {by.get('retrying',0)+by.get('pending',0)}")
        codes = Counter(str(e.get("response_status_code"))
                        for e in ev if e["status"] != "delivered")
        if codes:
            print(f"    failure codes  {dict(codes)}")
        stuck = [e for e in ev if e["status"] == "failed" and e["event_name"] in MONEY_EVENTS]
        if stuck:
            print(f"    !! {len(stuck)} money event(s) they never received "
                  f"- customers paid and got nothing:")
            for e in stuck:
                d = (e.get("payload") or {}).get("data", e.get("payload") or {})
                ref = d.get("reference") or d.get("merchant_reference") or "-"
                eat = dt.datetime.fromisoformat(
                    e["created_at"].replace("Z", "+00:00")) + dt.timedelta(hours=3)
                print(f"       {eat.strftime('%d %b %H:%M')} EAT  {ref:<24} "
                      f"TZS {d.get('amount','?')}")

        # --- their API usage --------------------------------------------
        logs = page(client, base, "api_request_logs", "status_code,path,created_at",
                    f"&merchant_id=eq.{mid}&created_at=gte.{since}")
        if logs:
            k = Counter("5xx" if (l.get("status_code") or 0) >= 500
                        else "429" if l.get("status_code") == 429
                        else "4xx" if (l.get("status_code") or 0) >= 400
                        else "ok" for l in logs)
            print(f"\n  THEIR API CALLS  {len(logs)} · ok {k['ok']} · 4xx {k['4xx']} · "
                  f"rate-limited {k['429']} · our errors {k['5xx']}")
            if k["429"]:
                print("    note: they are hitting rate limits - review the per-key ceiling")

        # --- turned away before they started ------------------------------
        # A payment refused for being below the network minimum creates no
        # collection at all, so it is invisible in every count above. On
        # 23 October that hid about twelve customers for one merchant in a
        # single day, three of whom retried 16, 28 and 30 times because
        # their screen said "Pending" and never showed the reason.
        rejected = page(client, base, "audit_logs", "created_at,metadata",
                        f"&merchant_id=eq.{mid}&action=eq.payment.below_operator_minimum"
                        f"&created_at=gte.{since}")
        if rejected:
            total = sum(Decimal(str((r.get("metadata") or {}).get("amount") or 0)) for r in rejected)
            print(
                f"\n  TURNED AWAY   {len(rejected)} attempt(s) below the network "
                f"minimum - TZS {total:,.0f} attempted"
            )
            seen = Counter(
                (r.get("metadata") or {}).get("customer_phone_masked") or "unknown"
                for r in rejected
            )
            print(f"    distinct customers: {len(seen)}")
            for phone, tries in seen.most_common(6):
                note = "  <-- retried, almost certainly saw no reason why" if tries >= 5 else ""
                print(f"      {phone:<14} {tries:>3} attempt(s){note}")
            print(f"    networks: {dict(Counter((r.get('metadata') or {}).get('network') or '?' for r in rejected))}")

        # --- what to act on ---------------------------------------------
        print("\n  WATCH LIST")
        flags = []
        if not signed:
            flags.append("webhook is UNSIGNED - they cannot verify events are from you")
        if stuck:
            flags.append(f"{len(stuck)} money event(s) undelivered - customers owed service")
        if orphans:
            flags.append(f"{len(orphans)} payment(s) not credited to their wallet")
        if rejected:
            flags.append(
                f"{len(rejected)} payment(s) refused below the network minimum - "
                f"customers turned away, no collection created"
            )
        if cols and len(expired) / len(cols) > 0.4:
            flags.append(f"{pct(len(expired), len(cols))} of prompts expire - conversion problem")
        if by.get("failed", 0) and len(ev) and by["failed"] / len(ev) > 0.02:
            flags.append(f"endpoint failing {pct(by['failed'], len(ev))} of deliveries")
        for f in flags:
            print(f"    - {f}")
        if not flags:
            print("    nothing needing attention in this window")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
