# Automatic Withdrawal Controls

How a Super Admin turns automatic withdrawal processing on, changes its
limits, and turns it off. For the merchant's side of a withdrawal see
[`docs/WITHDRAWAL_FLOW.md`](./WITHDRAWAL_FLOW.md); for approval and Selcom
sequencing see
[`docs/withdrawal-pricing-and-approval.md`](./withdrawal-pricing-and-approval.md).

This controls the **processing of withdrawal requests a merchant has
already made**. It never creates a withdrawal, and there is no scheduled
sweep of anyone's balance.

## Where it is

**Super Admin → Withdrawal Monitoring**, in the "Automatic Withdrawal
Controls" card above the withdrawal list.

## The state it ships in

Off. Applying the migration does not switch any installation on, and the
default stays off until somebody deliberately changes it.

## Precedence — which setting wins

Four things can say "no" and any one of them is enough. Resolved in one
place, `apps/api/app/services/withdrawal_policy.py`, and read on every
withdrawal:

| Order | Setting | Where | Default | Effect |
|---|---|---|---|---|
| 1 | `REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS` | Railway | `true` | **Emergency manual-only override.** While `true`, nothing is automatic, whatever the policy says. |
| 2 | `AUTO_WITHDRAWALS_ENABLED` | Railway | `false` | The deployment's permission for automation to exist. Must be `true`. |
| 3 | `withdrawal_automation_policy.enabled` | Database, Super Admin page | `false` | The routine ON/OFF switch. |
| 4 | `AUTO_WITHDRAWAL_MAX_AMOUNT_TZS`, `AUTO_WITHDRAWAL_DAILY_LIMIT_TZS` | Railway | 500,000 / 1,000,000 | **Hard ceilings.** The effective limit is `min(policy, env)`. |

So **both Railway flags must be set before the portal switch does
anything.** That is deliberate — it means a single mis-set variable
cannot enable real-money automation, and it means there is a way to force
manual approval that does not depend on the database being reachable.

When a deployment setting is blocking the switch, the page says so in
plain language instead of showing a control that would do nothing.

**Anything unreadable means manual approval.** A missing policy row, a
malformed amount, a database that cannot be reached — all of them resolve
to automation off, and the withdrawal is recorded with
`AUTO_POLICY_UNAVAILABLE` so a fault is distinguishable from a decision.

## What automation never skips

Automatic processing is a decision about *who approves*, not about which
checks run. Every one of these still applies, in both modes:

- The merchant is verified and active
- Merchant ownership and permissions
- The emailed withdrawal OTP — nothing is created until the code verifies
- Fraud checks and open high-risk alert holds
- Sufficient available funds, re-checked atomically when money moves
- The per-request minimum and maximum, and the hard rolling 24h limit
- Destination validation and provider restrictions
- The existing ledger, reconciliation, idempotency and duplicate-dispatch
  protection

An eligible withdrawal takes the **same payout path** a Super Admin's
manual approval takes. There is no separate, less-tested automatic payout
code.

## The per-request ceiling is inclusive

- Amount **≤** the configured maximum: may process automatically
- Amount **>** the configured maximum: requires manual approval

So with the maximum set to 500,000, a withdrawal of exactly 500,000
processes automatically and 500,001 waits for a human. The page states
this with a worked example built from whatever is typed in the field,
because "500" and "500,000" are a keystroke apart and mean very different
things.

The threshold applies to the **requested payout amount**. The balance
check still has to cover the full wallet debit, fees included — a
withdrawal inside the automatic limit is still refused if the wallet
cannot fund it.

## The rolling 24-hour limit

A per-merchant cap on how much this platform will process automatically
in any rolling 24 hours, measured backwards from the moment of each
decision. Not a calendar day, so there is no midnight at which an
allowance resets.

It is derived from the merchant's own withdrawals, not stored on the
policy, so **switching the policy off and on does not hand anyone a fresh
allowance**, and neither does editing the limits.

In-flight requests count. Two withdrawals submitted at the same instant
cannot each pass against the same remaining allowance: the decision runs
inside a per-merchant Postgres advisory lock
(`finalize_withdrawal_limits`), and a request that has been created but
not yet decided is counted conservatively. The earlier of two racing
requests wins; the later one falls back to manual approval rather than
both being refused.

## How to enable it

1. In Railway, set `AUTO_WITHDRAWALS_ENABLED=true` and
   `REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS=false`. Confirm
   `AUTO_WITHDRAWAL_MAX_AMOUNT_TZS` and `AUTO_WITHDRAWAL_DAILY_LIMIT_TZS`
   are the ceilings you want, because they cap whatever the portal asks
   for.
2. Open **Super Admin → Withdrawal Monitoring**. The card should no
   longer show a deployment-override notice.
3. Set the two limits. Both are in TZS, to at most 2 decimal places. The
   per-request maximum must be at least the platform withdrawal minimum
   (1,000 TZS) — a lower ceiling could never match a withdrawal, and is
   refused with a message saying so.
4. Switch **Automatic processing** on.
5. Press **Review and save**, read the summary of the effective limits,
   then **Confirm and save**.

Enabling, and any increase to either limit, requires that explicit
confirmation. The backend enforces it, not just the page.

## How to change the limits

Same card, same confirmation — but only when a change *widens* what can
happen unattended. **Lowering a limit saves in one click.**

A lowered limit binds the very next withdrawal. No deploy, no restart.

## How to turn it off

Switch **Automatic processing** off and press **Save**. One click, no
confirmation step, no provider request involved.

What that does and does not do:

- **Does:** every payout authorization taken after the save goes to
  manual approval.
- **Does not:** cancel, reverse or refund a payout already submitted to
  Selcom. Those continue through the existing reconciliation path, and
  nothing in the response claims otherwise. A payout already in flight
  cannot be guaranteed cancellable, so it is not presented as if it were.
- **Does not:** change any withdrawal already waiting for manual
  approval. They were already waiting.

### Faster still

If the portal is unavailable, or you want automation off independently of
the database, set `REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS=true` in
Railway. That overrides the policy row.

## Turning it ON does not drain the queue

Withdrawals already sitting in manual review stay in manual review. Their
automation decision was taken and recorded when they were created, and
enabling the policy does not re-run it. Automation applies to requests
made after it is on.

## What gets recorded

Every policy change writes an audit row — `withdrawal_automation_policy.updated`
— with the authenticated administrator, the timestamp, the previous and
new version, the previous and new enabled state and limits, what the
deployment ceilings made of them, and a correlation ID. The administrator
is taken from the verified session; the request body cannot name one.

Every withdrawal records how it was decided:

| Column | Meaning |
|---|---|
| `auto_approved` | True if no human approved it. `approved_by` stays null — no human is credited for a decision no human took. |
| `auto_decision_code` | `AUTO_ELIGIBLE`, `AUTO_POLICY_DISABLED`, `AUTO_AMOUNT_LIMIT_EXCEEDED`, `AUTO_ROLLING_LIMIT_EXCEEDED`, `AUTO_POLICY_UNAVAILABLE`, `AUTO_RISK_REVIEW_REQUIRED`, `DAILY_LIMIT_EXCEEDED` |
| `auto_decision_reason` | The same thing in a sentence |
| `auto_policy_version` | Which version of the policy decided it |
| `auto_decided_at` | When — not the same instant as `initiated_at` or `approved_at` |

The reason codes carry no fraud detail. A merchant blocked by a risk hold
is told their withdrawal is under review, never why.

The withdrawal list shows the automatic-versus-manual badge and, for an
automatic payout, the policy version that authorized it.

## Eligibility is not approval

An amount being inside the automatic limits does not mean a pending
withdrawal will be paid. The pending queue is shown separately and is the
only thing that says what is actually waiting. Nothing on the controls
card should be read as a promise about a particular request.

## Rollback

In order of speed, all of which restore manual approval:

1. **Seconds, no deploy:** switch it off in the portal, or
   `update public.withdrawal_automation_policy set enabled = false;`
2. **Deployment:** set `REQUIRE_ADMIN_APPROVAL_FOR_ALL_WITHDRAWALS=true`
   in Railway.
3. **Code:** roll the API back. The migration keeps the original
   5-argument `finalize_withdrawal_limits` as a wrapper for exactly this
   reason, so an older API build keeps working against the new schema.

**Do not drop the table or the new `disbursements` columns as part of a
rollback.** They are the record of which policy authorized each payout.
No rollback deletes a financial record, a reservation or an audit row.

## Deployment order

1. Apply the migration
   `supabase/migrations/20261031010000_withdrawal_automation_policy.sql`.
   It is additive and safe to apply before the API: it creates the policy
   row disabled, adds three nullable columns, and leaves the old function
   signature working.
2. Deploy the API.
3. Deploy the web app.
4. Only then set the Railway variables, if you intend to enable
   automation at all.

Applying the migration on its own changes no behaviour. Every withdrawal
keeps going to manual approval until all four layers agree.
