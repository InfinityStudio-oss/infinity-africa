"""An in-memory stand-in for the supabase-py client, covering the subset of
the fluent query builder app/services and app/routers actually use:
select/insert/update/delete, .eq()/.is_()/.in_(), .order(), .range(),
.maybe_single(), count="exact". Good enough to exercise real router/service
code end-to-end in tests without a real Supabase project.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal


class _Result:
    def __init__(self, data, count=None):
        self.data = data
        self.count = count


class _FakeQuery:
    def __init__(self, table: "_FakeTable", op: str, payload=None):
        self._table = table
        self._op = op
        self._payload = payload
        self._filters: list[tuple[str, str, object]] = []
        self._order_col: str | None = None
        self._order_desc = False
        self._range_start: int | None = None
        self._range_end: int | None = None
        self._limit: int | None = None
        self._single: str | None = None

    def eq(self, column, value):
        self._filters.append(("eq", column, value))
        return self

    def ilike(self, column, pattern):
        self._filters.append(("ilike", column, pattern))
        return self

    def neq(self, column, value):
        self._filters.append(("neq", column, value))
        return self

    def is_(self, column, value):
        self._filters.append(("is", column, value))
        return self

    def in_(self, column, values):
        self._filters.append(("in", column, list(values)))
        return self

    def gte(self, column, value):
        self._filters.append(("gte", column, value))
        return self

    def gt(self, column, value):
        self._filters.append(("gt", column, value))
        return self

    def lte(self, column, value):
        self._filters.append(("lte", column, value))
        return self

    def lt(self, column, value):
        self._filters.append(("lt", column, value))
        return self

    def order(self, column, desc=False):
        self._order_col = column
        self._order_desc = desc
        return self

    def range(self, start, end):
        self._range_start = start
        self._range_end = end
        return self

    def limit(self, count):
        self._limit = count
        return self

    def maybe_single(self):
        self._single = "maybe_single"
        return self

    def single(self):
        self._single = "single"
        return self

    @staticmethod
    def _compare(row_value, value):
        """Numeric comparison when possible (amounts stored as numeric
        strings), else lexicographic (ISO8601 timestamps sort correctly as
        strings). Returns -1/0/1, or None if row_value is missing."""
        if row_value is None:
            return None
        try:
            a, b = float(row_value), float(value)
        except (TypeError, ValueError):
            a, b = str(row_value), str(value)
        return -1 if a < b else (1 if a > b else 0)

    @staticmethod
    def _ilike_matches(row_value, pattern: str) -> bool:
        """Mirrors Postgres ILIKE: `%`/`_` are wildcards, `\\` escapes the
        next character — the same default escape rules real Postgres
        uses, so callers that escape a literal string before passing it
        in (app/services/pay_by_link.py's cross-table slug check) get an
        exact, case-insensitive comparison here too."""
        if row_value is None:
            return False

        regex_parts = []
        i = 0
        while i < len(pattern):
            ch = pattern[i]
            if ch == "\\" and i + 1 < len(pattern):
                regex_parts.append(re.escape(pattern[i + 1]))
                i += 2
                continue
            if ch == "%":
                regex_parts.append(".*")
            elif ch == "_":
                regex_parts.append(".")
            else:
                regex_parts.append(re.escape(ch))
            i += 1
        return re.fullmatch("".join(regex_parts), str(row_value), re.IGNORECASE) is not None

    def _matches(self, row: dict) -> bool:
        for kind, column, value in self._filters:
            if kind == "eq" and str(row.get(column)) != str(value):
                return False
            if kind == "neq" and str(row.get(column)) == str(value):
                return False
            if kind == "ilike" and not self._ilike_matches(row.get(column), value):
                return False
            if kind == "is" and value == "null" and row.get(column) is not None:
                return False
            if kind == "in" and str(row.get(column)) not in [str(v) for v in value]:
                return False
            if kind in ("gte", "gt", "lte", "lt"):
                cmp = self._compare(row.get(column), value)
                if cmp is None:
                    return False
                if kind == "gte" and cmp < 0:
                    return False
                if kind == "gt" and cmp <= 0:
                    return False
                if kind == "lte" and cmp > 0:
                    return False
                if kind == "lt" and cmp >= 0:
                    return False
        return True

    def execute(self) -> _Result:
        if self._op == "select":
            rows = [row for row in self._table.rows if self._matches(row)]
            if self._order_col:
                rows = sorted(
                    rows, key=lambda r: r.get(self._order_col) or "", reverse=self._order_desc
                )
            total = len(rows)
            if self._range_start is not None:
                rows = rows[self._range_start : self._range_end + 1]
            elif self._limit is not None:
                rows = rows[: self._limit]
            if self._single:
                return _Result(dict(rows[0]) if rows else None)
            return _Result([dict(r) for r in rows], count=total)

        if self._op == "insert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            return _Result([self._table.insert(p) for p in payloads])

        if self._op == "update":
            matched = [row for row in self._table.rows if self._matches(row)]
            for row in matched:
                row.update(self._payload)
                row["updated_at"] = datetime.now(timezone.utc).isoformat()
            return _Result([dict(r) for r in matched])

        if self._op == "delete":
            matched = [row for row in self._table.rows if self._matches(row)]
            self._table.rows = [row for row in self._table.rows if row not in matched]
            return _Result([dict(r) for r in matched])

        raise NotImplementedError(self._op)


class _FakeTable:
    def __init__(self, name: str):
        self.name = name
        self.rows: list[dict] = []

    def insert(self, payload: dict) -> dict:
        row = dict(payload)
        row.setdefault("id", str(uuid.uuid4()))
        now = datetime.now(timezone.utc).isoformat()
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        if self.name == "invoice_items":
            # Mirrors invoice_items.line_total, a Postgres
            # `generated always as (quantity * unit_price) stored` column —
            # never supplied by the caller, always derived.
            row["line_total"] = str(Decimal(str(row["quantity"])) * Decimal(str(row["unit_price"])))
        self.rows.append(row)
        return row


class _FakeTableHandle:
    def __init__(self, table: _FakeTable):
        self._table = table

    def select(self, columns: str = "*", count: str | None = None) -> _FakeQuery:
        return _FakeQuery(self._table, "select")

    def insert(self, payload) -> _FakeQuery:
        return _FakeQuery(self._table, "insert", payload)

    def update(self, payload: dict) -> _FakeQuery:
        return _FakeQuery(self._table, "update", payload)

    def delete(self) -> _FakeQuery:
        return _FakeQuery(self._table, "delete")


class _FakeRpcCall:
    def __init__(self, client: "FakeSupabaseClient", fn_name: str, params: dict):
        self._client = client
        self._fn_name = fn_name
        self._params = params

    def execute(self) -> _Result:
        if self._fn_name == "post_ledger_entries":
            return self._client._post_ledger_entries(self._params.get("p_entries") or [])
        if self._fn_name == "finalize_withdrawal_limits":
            return self._client._finalize_withdrawal_limits(self._params)
        raise NotImplementedError(self._fn_name)


class _FakeStorageBucket:
    """In-memory stand-in for a supabase-py storage bucket proxy — covers
    .upload()/.create_signed_url(), the only two calls app/services/
    onboarding.py makes."""

    def __init__(self, objects: dict[str, bytes], bucket_id: str):
        self._objects = objects
        self._bucket_id = bucket_id

    def upload(self, path: str, file, file_options=None):
        self._objects[f"{self._bucket_id}/{path}"] = file
        return {"path": path, "fullPath": f"{self._bucket_id}/{path}"}

    def create_signed_url(self, path: str, expires_in: int, options=None) -> dict:
        url = f"https://fake.storage.test/{self._bucket_id}/{path}?expires_in={expires_in}"
        return {"signedURL": url, "signedUrl": url}


class _FakeStorage:
    def __init__(self, objects: dict[str, bytes]):
        self._objects = objects

    def from_(self, bucket_id: str) -> _FakeStorageBucket:
        return _FakeStorageBucket(self._objects, bucket_id)


class _FakeAuthAdminUser:
    """Mirrors the subset of supabase-py's gotrue User object
    app/services/admin_directory.py actually reads: .email and
    .user_metadata (for "full_name")."""

    def __init__(
        self,
        user_id: str,
        *,
        email: str | None,
        full_name: str | None,
        email_confirmed_at: str | None = None,
    ):
        self.id = user_id
        self.email = email
        self.user_metadata = {"full_name": full_name} if full_name else {}
        self.email_confirmed_at = email_confirmed_at


class _FakeGetUserResult:
    def __init__(self, user: _FakeAuthAdminUser):
        self.user = user


class _FakeGenerateLinkProperties:
    def __init__(self, action_link: str):
        self.action_link = action_link


class _FakeGenerateLinkResult:
    def __init__(self, user: _FakeAuthAdminUser, action_link: str):
        self.user = user
        self.properties = _FakeGenerateLinkProperties(action_link)


class _FakeAuthAdmin:
    def __init__(self):
        self._users: dict[str, _FakeAuthAdminUser] = {}

    def seed_user(
        self,
        user_id: str,
        *,
        email: str | None = None,
        full_name: str | None = None,
        email_confirmed_at: str | None = None,
    ) -> None:
        self._users[str(user_id)] = _FakeAuthAdminUser(
            str(user_id), email=email, full_name=full_name, email_confirmed_at=email_confirmed_at
        )

    def create_user(self, attributes: dict) -> _FakeGetUserResult:
        """Mirrors supabase_auth's admin create_user for
        app/services/onboarding.py::signup_merchant: rejects a duplicate
        email the way real Supabase Auth does, otherwise creates a user
        with user_metadata.full_name and honours email_confirm."""
        email = attributes.get("email")
        if email and any(user.email == email for user in self._users.values()):
            raise Exception(f"A user with email {email} already registered")  # noqa: TRY002
        user_id = str(uuid.uuid4())
        full_name = (attributes.get("user_metadata") or {}).get("full_name")
        confirmed_at = "2026-01-01T00:00:00+00:00" if attributes.get("email_confirm") else None
        self.seed_user(user_id, email=email, full_name=full_name, email_confirmed_at=confirmed_at)
        return _FakeGetUserResult(self._users[user_id])

    def get_user_by_id(self, user_id: str) -> _FakeGetUserResult:
        user = self._users.get(str(user_id))
        if user is None:
            # Mirrors a real Supabase Auth admin 404 — services/admin_directory.py
            # catches this (and anything else) and degrades to None/None.
            raise Exception(f"User {user_id} not found")  # noqa: TRY002
        return _FakeGetUserResult(user)

    def invite_user_by_email(self, email: str, options: dict | None = None) -> _FakeGetUserResult:
        """Mirrors the real Supabase Auth admin API closely enough for
        app/routers/merchant_portal.py::create_my_merchant_user: rejects an
        email already used by a seeded/invited user (real Supabase Auth
        errors on a duplicate email the same way), otherwise creates a new
        user with user_metadata.full_name from options["data"]["full_name"].
        """
        if any(user.email == email for user in self._users.values()):
            raise Exception(f"A user with email {email} already exists")  # noqa: TRY002
        user_id = str(uuid.uuid4())
        full_name = ((options or {}).get("data") or {}).get("full_name")
        self.seed_user(user_id, email=email, full_name=full_name)
        return _FakeGetUserResult(self._users[user_id])

    def generate_link(self, params: dict) -> "_FakeGenerateLinkResult":
        """Mirrors supabase_auth's admin generate_link closely enough for
        app/services/email.py's staff-invite and password-reset flows:
        never sends Supabase's own email (that's the whole point of using
        it over invite_user_by_email/reset_password_for_email), just
        returns an action_link. type="invite" creates a new user (same
        duplicate-email rejection as invite_user_by_email above);
        type="recovery" requires an *existing* user and raises if none
        matches — the real API's behavior, which
        send_password_reset_email relies on to silently no-op for an
        unregistered email (account enumeration prevention)."""
        link_type = params.get("type")
        email = params["email"]
        options = params.get("options") or {}
        redirect_to = options.get("redirect_to", "")
        token = uuid.uuid4().hex

        if link_type == "invite":
            if any(user.email == email for user in self._users.values()):
                raise Exception(f"A user with email {email} already exists")  # noqa: TRY002
            user_id = str(uuid.uuid4())
            full_name = (options.get("data") or {}).get("full_name")
            self.seed_user(user_id, email=email, full_name=full_name)
            user = self._users[user_id]
        elif link_type in ("recovery", "signup"):
            # "signup" (email-verification link for the combined signup
            # flow) and "recovery" both require an *existing* user and
            # raise if none matches — the real API's behaviour.
            user = next((u for u in self._users.values() if u.email == email), None)
            if user is None:
                raise Exception(f"User {email} not found")  # noqa: TRY002
        else:
            raise NotImplementedError(f"generate_link type={link_type}")

        action_link = f"https://fake.supabase.test/auth/v1/verify?type={link_type}&token={token}&redirect_to={redirect_to}"
        return _FakeGenerateLinkResult(user, action_link)


class _FakeAuth:
    def __init__(self):
        self.admin = _FakeAuthAdmin()


class FakeSupabaseClient:
    def __init__(self):
        self._tables: dict[str, _FakeTable] = {}
        self._storage_objects: dict[str, bytes] = {}
        self.storage = _FakeStorage(self._storage_objects)
        self.auth = _FakeAuth()

    def table(self, name: str) -> _FakeTableHandle:
        if name not in self._tables:
            self._tables[name] = _FakeTable(name)
        return _FakeTableHandle(self._tables[name])

    def seed(self, table: str, row: dict) -> dict:
        """Directly insert a row, bypassing the query builder — for test setup."""
        return self.table(table)._table.insert(row)

    def seed_auth_user(self, user_id, *, email: str | None = None, full_name: str | None = None) -> None:
        self.auth.admin.seed_user(str(user_id), email=email, full_name=full_name)

    def rpc(self, fn_name: str, params: dict | None = None) -> _FakeRpcCall:
        return _FakeRpcCall(self, fn_name, params or {})

    def _finalize_withdrawal_limits(self, params: dict) -> _Result:
        """Mirrors supabase/migrations/20260922030000_finalize_withdrawal_limits.sql:
        enforces the rolling 24h hard daily limit and decides
        auto-withdrawal eligibility for a just-inserted disbursement,
        returning {"outcome": rejected|auto|manual, "reason": ...} and
        writing status/auto_approved/auto_decision_reason onto the row
        exactly as the real function does.

        The real function does all of this while holding a per-merchant
        advisory lock, which is what makes it race-proof; this in-memory
        mirror is single-threaded, so it reproduces the *decisions* (and
        the (initiated_at, id) "count only rows initiated strictly before
        this one" ordering that makes two simultaneous requests resolve to
        one winner rather than blocking each other) but not the locking
        itself. Tests that care about the ordering rule seed the competing
        rows directly — see tests/test_withdrawal_automation.py.
        """
        table = self.table("disbursements")._table
        row = next((r for r in table.rows if r["id"] == params["p_disbursement_id"]), None)
        if row is None:
            raise Exception(f"DISBURSEMENT_NOT_FOUND: {params['p_disbursement_id']}")  # noqa: TRY002

        daily_limit = Decimal(str(params["p_daily_limit"]))
        auto_max = Decimal(str(params["p_auto_max"]))
        auto_daily_limit = Decimal(str(params["p_auto_daily_limit"]))
        automation_enabled = bool(params["p_automation_enabled"])

        amount = Decimal(str(row["amount"]))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        def _earlier_rows(*, auto_only: bool) -> Decimal:
            total = Decimal(0)
            for other in table.rows:
                if other["id"] == row["id"] or other["merchant_id"] != row["merchant_id"]:
                    continue
                if other["status"] in ("REJECTED", "FAILED"):
                    continue
                # Mirrors the SQL's "(auto_approved or auto_decision_reason
                # is null)": an earlier row that is still undecided is
                # counted conservatively, because lock order is not
                # (initiated_at, id) order and it may yet become auto.
                if auto_only and not (other.get("auto_approved") or not other.get("auto_decision_reason")):
                    continue
                initiated = other.get("initiated_at")
                if not initiated or datetime.fromisoformat(initiated) < cutoff:
                    continue
                # Strictly-before ordering on (initiated_at, id), same as
                # the real function's row-comparison predicate.
                if (initiated, str(other["id"])) >= (row["initiated_at"], str(row["id"])):
                    continue
                total += Decimal(str(other["amount"]))
            return total

        requested_today = _earlier_rows(auto_only=False)
        if requested_today + amount > daily_limit:
            reason = (
                f"Rejected: would exceed the daily withdrawal limit of {daily_limit} TZS "
                f"(already requested in the last 24 hours: {requested_today} TZS)."
            )
            row["status"] = "REJECTED"
            row["auto_decision_reason"] = reason
            return _Result({"outcome": "rejected", "reason": reason, "already_requested_today": str(requested_today)})

        if not automation_enabled:
            reason = "Manual approval required: withdrawal automation is not enabled."
        elif amount > auto_max:
            reason = (
                f"Manual approval required: exceeds the {auto_max} TZS "
                "per-transaction limit for automatic processing."
            )
        else:
            auto_today = _earlier_rows(auto_only=True)
            if auto_today + amount > auto_daily_limit:
                reason = (
                    f"Manual approval required: would exceed the {auto_daily_limit} TZS "
                    f"daily limit for automatic processing (already auto-processed today: {auto_today} TZS)."
                )
            else:
                reason = "Eligible: verified merchant, no open high-risk alerts, within auto-withdrawal limits."
                row["auto_approved"] = True
                row["auto_decision_reason"] = reason
                return _Result({"outcome": "auto", "reason": reason})

        row["auto_decision_reason"] = reason
        return _Result({"outcome": "manual", "reason": reason})

    def _post_ledger_entries(self, entries: list[dict]) -> _Result:
        """Mirrors supabase/migrations/20260814130002_post_ledger_entries_function.sql,
        20260814140001_post_ledger_entries_balance_check.sql, and
        20260828020000_post_ledger_entries_balance_snapshot.sql: inserts
        each entry (with its own balance_before/after snapshot) and updates
        its account's cached balance, using the same asset/expense-vs-
        liability/equity/revenue sign convention, and rejects the *whole*
        batch — nothing inserted, nothing updated — if it would take a
        merchant_wallet balance negative.

        Two-phase (validate every resulting balance, and capture each
        entry's before/after snapshot, before mutating anything) to mirror
        the real function's atomicity: a Postgres exception partway through
        rolls back the entire transaction, not just the entry that tripped
        it. Entries are walked in order so an account touched twice in the
        same batch sees the first entry's effect reflected in the second's
        balance_before — exactly like the real function's sequential loop.
        """
        accounts_table = self.table("ledger_accounts")._table

        running_balances: dict[str, Decimal] = {}
        snapshots: list[tuple[Decimal | None, Decimal | None]] = []
        for entry in entries:
            account = next((a for a in accounts_table.rows if a["id"] == entry["ledger_account_id"]), None)
            if account is None:
                snapshots.append((None, None))
                continue
            account_id = account["id"]
            current = running_balances.get(account_id, Decimal(str(account.get("balance") or "0")))
            amount = Decimal(str(entry["amount"]))
            increases_on_debit = account.get("account_type") in ("asset", "expense")
            is_debit = entry["direction"] == "debit"
            delta = amount if (is_debit == increases_on_debit) else -amount
            new_balance = current + delta
            if account.get("purpose") == "merchant_wallet" and new_balance < 0:
                raise Exception(  # noqa: TRY002 - mirrors a raw postgrest/Postgres error, see services/ledger.py
                    f"INSUFFICIENT_BALANCE: wallet {account_id} balance {current} "
                    f"cannot cover a {entry['direction']} of {amount} (would be {new_balance})"
                )
            running_balances[account_id] = new_balance
            snapshots.append((current, new_balance))

        entries_table = self.table("ledger_entries")._table
        inserted = []
        for entry, (balance_before, balance_after) in zip(entries, snapshots, strict=True):
            payload = dict(entry)
            payload["balance_before"] = str(balance_before) if balance_before is not None else None
            payload["balance_after"] = str(balance_after) if balance_after is not None else None
            row = entries_table.insert(payload)
            account = next((a for a in accounts_table.rows if a["id"] == entry["ledger_account_id"]), None)
            if account is not None and account["id"] in running_balances:
                account["balance"] = str(running_balances[account["id"]])
            inserted.append(row)

        return _Result(inserted)
