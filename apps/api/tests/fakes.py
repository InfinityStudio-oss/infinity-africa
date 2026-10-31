"""An in-memory stand-in for the supabase-py client, covering the subset of
the fluent query builder app/services and app/routers actually use:
select/insert/update/delete, .eq()/.is_()/.in_(), .order(), .range(),
.maybe_single(), count="exact". Good enough to exercise real router/service
code end-to-end in tests without a real Supabase project.
"""

import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

POSTGREST_DEFAULT_PAGE = 1000


# Rendered characters allowed inside one `.in_(...)`. The real limit is on
# the whole URL; this is the share of it an id list can take before the
# request stops being answerable.
_IN_LIST_CHAR_BUDGET = 25_000


def _url_too_long_error(table: str, column: str, count: int, rendered: int):
    """What the server in front of PostgREST really does with an `.in_()`
    list long enough to blow the URL limit: a 400 whose body is the plain
    text "Bad Request", which postgrest-py reports as "JSON could not be
    generated"."""
    from postgrest.exceptions import APIError

    return APIError(
        {
            "message": "JSON could not be generated",
            "code": 400,
            "hint": "Refer to full message for details",
            "details": (
                f"Fake client: .in_({column!r}, ...) on {table!r} rendered {count} values "
                f"into ~{rendered} characters of URL, past the ~25,000 a real request "
                f"survives. Batch it - see app/services/crud.py::fetch_in_chunks."
            ),
        }
    )


def _multiple_rows_error(table: str, mode: str, count: int):
    """What PostgREST really does when `.single()`/`.maybe_single()` match
    more than one row — it refuses, rather than picking one.

    The fake used to return `rows[0]`, so a query that matched several
    rows looked fine here and failed in production. That is not
    hypothetical: payout retry reverses a withdrawal's transaction and
    reserves a new one, both on the same disbursement_id, and
    _find_transaction_for_disbursement asked for `.maybe_single()`. Every
    test passed; two real withdrawals were left stuck PROCESSING and
    could not be refreshed at all.

    The message mirrors what the application actually sees, which is the
    detail that makes this worth replicating faithfully. postgrest-py's
    maybe_single() catches the PGRST116 error, checks it for "contains 0
    rows", does not match, falls through and raises a bare
    APIError("Missing response") — discarding the real cause. So
    "Missing response" in a traceback means "a single-row query hit an
    error that was not zero rows", and in practice that means too many.
    """
    from postgrest.exceptions import APIError

    if mode == "maybe_single":
        return APIError(
            {
                "message": "Missing response",
                "code": "204",
                "hint": "Please check traceback of the code",
                "details": (
                    f"Fake client: .maybe_single() on {table!r} matched {count} rows. "
                    "Real PostgREST answers PGRST116 and postgrest-py reports it as "
                    "this. Filter to one row, or use .order(...).limit(1)."
                ),
            }
        )
    return APIError(
        {
            "message": "JSON object requested, multiple (or no) rows returned",
            "code": "PGRST116",
            "hint": None,
            "details": f"The result contains {count} rows",
        }
    )


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
        values = list(values)
        # `.in_()` is rendered into the URL, so the real constraint is the
        # rendered *length*, not the count - which is why this measures
        # characters and a list of short status strings never trips it.
        #
        # Measured against production on 2026-10-13: 675 uuids
        # (25,054 characters of URL) are accepted, 676 (25,091) come back
        # 400 with a plain-text "Bad Request" body. postgrest-py cannot
        # parse that as an error document, so the application sees
        # `APIError: JSON could not be generated` - an error naming
        # neither the table nor the cause.
        #
        # The fake used to accept any length, which is why a merchant's
        # Wallet Ledger could 500 in production on a query that every
        # test here passed. Same lesson as the multi-row .single() rule
        # above and the 1000-row page cap: wherever this fake is more
        # forgiving than PostgREST, a real bug looks fine.
        rendered = sum(len(str(v)) + 1 for v in values)
        if rendered > _IN_LIST_CHAR_BUDGET:
            raise _url_too_long_error(self._table.name, column, len(values), rendered)
        self._filters.append(("in", column, values))
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

    @staticmethod
    def _value_for(row: dict, column: str):
        """A column's value, including PostgREST's `payload->>key` path.

        Real PostgREST can filter on a field *inside* a json column, which
        is how a webhook event is matched back to its collection
        (`payload->>collection_id`) - webhook_events has no collection_id
        column of its own.

        This fake used to resolve any such column to None, so a filter on
        one matched nothing and the test built on it passed for entirely
        the wrong reason: not "the right rows came back" but "no rows did".
        Same lesson as the multi-row .single() rule and the .in_() length
        cap - wherever this fake is more permissive than PostgREST, a bug
        ships green.
        """
        if "->>" in column:
            container_name, _, field = column.partition("->>")
            container = row.get(container_name.strip())
            if isinstance(container, dict):
                return container.get(field.strip())
            return None
        return row.get(column)

    def _matches(self, row: dict) -> bool:
        for kind, column, value in self._filters:
            if kind == "eq" and str(self._value_for(row, column)) != str(value):
                return False
            if kind == "neq" and str(self._value_for(row, column)) == str(value):
                return False
            if kind == "ilike" and not self._ilike_matches(self._value_for(row, column), value):
                return False
            if kind == "is" and value == "null" and self._value_for(row, column) is not None:
                return False
            if kind == "in" and str(self._value_for(row, column)) not in [str(v) for v in value]:
                return False
            if kind in ("gte", "gt", "lte", "lt"):
                cmp = self._compare(self._value_for(row, column), value)
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
            else:
                # PostgREST answers an unbounded select with one page and
                # says nothing about the rest. Without this cap the fake
                # returned every row, so a dashboard that summed a whole
                # table passed here and silently read zero in production
                # once the table outgrew a page - which is exactly how
                # Collections Today reached TZS 0.00. See
                # tests/test_overview_pagination.py.
                rows = rows[:POSTGREST_DEFAULT_PAGE]
            if self._single:
                if len(rows) > 1:
                    raise _multiple_rows_error(self._table.name, self._single, len(rows))
                return _Result(dict(rows[0]) if rows else None)
            return _Result([dict(r) for r in rows], count=total)

        if self._op == "insert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            return _Result([self._table.insert(p) for p in payloads])

        if self._op == "update":
            matched = [row for row in self._table.rows if self._matches(row)]
            for row in matched:
                _assert_wire_safe(self._table.name, self._payload)
                row.update(self._payload)
                row["updated_at"] = datetime.now(timezone.utc).isoformat()
            return _Result([dict(r) for r in matched])

        if self._op == "delete":
            matched = [row for row in self._table.rows if self._matches(row)]
            self._table.rows = [row for row in self._table.rows if row not in matched]
            return _Result([dict(r) for r in matched])

        raise NotImplementedError(self._op)


def _assert_wire_safe(table_name: str, payload) -> None:
    """Rejects anything a real PostgREST write could not send.

    supabase-py serialises the body with json.dumps, so a uuid.UUID,
    Decimal, datetime or enum reaches production as a TypeError even though
    this in-memory store would happily keep the object as-is. That gap let a
    withdrawal-OTP bug (uuid.UUID passed where a str id was expected) pass
    the whole suite and fail on the first real request, after the email had
    already gone out. Failing here keeps that class of bug in the tests.
    """
    for column, value in (payload or {}).items():
        try:
            json.dumps(value)
        except TypeError:
            raise TypeError(
                f"{table_name}.{column} is {type(value).__name__}, which PostgREST cannot "
                f"serialise — pass a JSON-native value (str/int/bool/None/list/dict)."
            ) from None


class _FakeTable:
    def __init__(self, name: str):
        self.name = name
        self.rows: list[dict] = []

    def insert(self, payload: dict) -> dict:
        _assert_wire_safe(self.name, payload)
        row = dict(payload)
        row.setdefault("id", str(uuid.uuid4()))
        now = datetime.now(timezone.utc).isoformat()
        row.setdefault("created_at", now)
        row.setdefault("updated_at", now)
        if self.name == "sms_messages":
            # Two real constraints from
            # 20261017090000_merchant_sms_notifications.sql. Without them
            # the duplicate-protection tests would pass against a store
            # that cannot duplicate anything, which is the same trap the
            # CHECK-constraint gap left in this fake before: green here,
            # broken in production.
            #
            # 1. the partial unique index on
            #    (collection_id, merchant_id, purpose) for alerts, which
            #    is what stops a Selcom callback and the reconciliation
            #    sweep both alerting on one collection.
            if row.get("purpose") == "collection_alert" and row.get("collection_id"):
                clash = any(
                    r.get("purpose") == "collection_alert"
                    and r.get("collection_id") == row["collection_id"]
                    and r.get("merchant_id") == row.get("merchant_id")
                    for r in self.rows
                )
                if clash:
                    raise Exception(  # noqa: TRY002
                        "duplicate key value violates unique constraint "
                        "sms_messages_one_alert_per_collection"
                    )
            # 2. the unique idempotency key.
            if row.get("idempotency_key") and any(
                r.get("idempotency_key") == row["idempotency_key"] for r in self.rows
            ):
                raise Exception(  # noqa: TRY002
                    "duplicate key value violates unique constraint "
                    "sms_messages_idempotency_key_key"
                )
            # next_attempt_at is `not null default now()` in the migration.
            row.setdefault("next_attempt_at", now)
            row.setdefault("attempts", 0)
        if self.name in ("collections", "transactions"):
            # Partial unique indexes on provider_reference
            # (20260814090009_collections.sql, 20260814090011_transactions.sql),
            # both `where provider_reference is not null`.
            #
            # Without these the fake cannot show what production does when
            # Selcom repeats a reference, and
            # insert_collection_tolerating_repeated_reference never reaches
            # its fallback - so a test proves the de-duplication works while
            # never once exercising it.
            #
            # That gap hid a real bug (INFINITYPAY-API-14): the collection
            # insert tolerated a repeated reference while the linked
            # transactions insert recomputed the value and violated its own
            # index, leaving a processing collection with no transaction.
            #
            # The raised error carries `.code` and the index name because
            # that is exactly what is_duplicate_provider_reference() matches
            # on; a bare Exception would be re-raised as an unknown failure.
            ref = (row.get("provider_reference") or "").strip()
            if ref and any((r.get("provider_reference") or "") == ref for r in self.rows):
                index = f"{self.name}_provider_reference_key"
                error = Exception(  # noqa: TRY002
                    f'duplicate key value violates unique constraint "{index}"'
                )
                error.code = "23505"
                error.message = f'duplicate key value violates unique constraint "{index}"'
                raise error
        if self.name == "audit_logs":
            # audit_logs.actor_id is `references auth.users (id)`
            # (20260814090015_audit_logs.sql). This fake enforces no foreign
            # keys, which is precisely how a real bug survived twelve call
            # sites and reached production on 2026-10-20:
            #
            #   APIError: insert or update on table "audit_logs" violates
            #   foreign key constraint "audit_logs_actor_id_fkey"
            #
            # An API-key caller is not a Supabase Auth user - caller.actor_id
            # is the api_keys row id - so every audited money path called
            # with an API key raised *after* doing the work, turning a
            # successful collection or disbursement into a 500.
            #
            # Enforcing the whole foreign key here would mean every test that
            # invents a user uuid had to register an auth user first, which
            # would be churn for no safety. This enforces the part that
            # actually broke and that no legitimate caller needs: an actor
            # that is not a user has no business in a column that means "the
            # auth user who did this".
            if row.get("actor_type") not in (None, "user") and row.get("actor_id") is not None:
                raise Exception(  # noqa: TRY002
                    "insert or update on table \"audit_logs\" violates foreign key "
                    "constraint \"audit_logs_actor_id_fkey\" "
                    f"(actor_type={row.get('actor_type')!r} is not a Supabase Auth user; "
                    "pass actor_id=None and record the identity in metadata)"
                )
        if self.name == "sms_provider_events":
            # event_id is unique in the migration, and that uniqueness is
            # the entire deduplication mechanism for provider callbacks -
            # the provider retries the same event at 1min, 5min, 30min,
            # 2h and 12h. Without it here, the dedupe test would pass
            # against a store that cannot reject anything.
            if any(r.get("event_id") == row.get("event_id") for r in self.rows):
                raise Exception(  # noqa: TRY002
                    "duplicate key value violates unique constraint "
                    "sms_provider_events_event_id_key"
                )
        if self.name in ("collections", "disbursements"):
            # `not null default now()` in
            # 20261017160000_reconciliation_next_check.sql. Without this
            # every seeded row would be missing the column the sweeps
            # filter on, and the due-only queries would silently match
            # nothing - which reads exactly like "the sweep found no
            # work" rather than like a broken test.
            row.setdefault("next_check_at", now)
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
        if self._fn_name == "admin_overview_money":
            return self._client._admin_overview_money(self._params)
        if self._fn_name == "update_withdrawal_automation_policy":
            return self._client._update_withdrawal_automation_policy(self._params)
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
    app/services/admin_directory.py actually reads: .email,
    .user_metadata (for "full_name") and .last_sign_in_at."""

    def __init__(
        self,
        user_id: str,
        *,
        email: str | None,
        full_name: str | None,
        email_confirmed_at: str | None = None,
        last_sign_in_at: str | None = None,
    ):
        self.id = user_id
        self.email = email
        self.user_metadata = {"full_name": full_name} if full_name else {}
        self.email_confirmed_at = email_confirmed_at
        # None means "never signed in", which is a real and important
        # state for a backup admin account, not merely missing data.
        self.last_sign_in_at = last_sign_in_at


class _FakeGetUserResult:
    def __init__(self, user: _FakeAuthAdminUser):
        self.user = user


class _FakeGenerateLinkProperties:
    def __init__(self, action_link: str, hashed_token: str, email_otp: str):
        self.action_link = action_link
        # Emailed as a typed fallback beside the link, so the reset still
        # works when something in transit mangles the URL.
        self.email_otp = email_otp
        # The real generate_link returns this alongside action_link, and
        # app/services/email.py::_recovery_link_for prefers it — a query
        # parameter survives the redirects that silently eat action_link's
        # URL fragment. Omitting it here would let that code path go
        # untested while the fallback quietly carried every test.
        self.hashed_token = hashed_token


class _FakeGenerateLinkResult:
    def __init__(self, user: _FakeAuthAdminUser, action_link: str, hashed_token: str, email_otp: str):
        self.user = user
        self.properties = _FakeGenerateLinkProperties(action_link, hashed_token, email_otp)


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
        last_sign_in_at: str | None = None,
    ) -> None:
        self._users[str(user_id)] = _FakeAuthAdminUser(
            str(user_id),
            email=email,
            full_name=full_name,
            email_confirmed_at=email_confirmed_at,
            last_sign_in_at=last_sign_in_at,
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

    def update_user_by_id(self, user_id: str, attributes: dict) -> _FakeGetUserResult:
        """Mirrors supabase_auth's admin update_user_by_id for
        app/services/merchant_email_correction.py.

        Two real behaviours matter and both are here: a 404 for an unknown
        user, and refusing an email that already belongs to somebody else
        - which is the one case where the email correction must not go
        ahead, because two merchants would end up fighting over one login.
        """
        user = self._users.get(str(user_id))
        if user is None:
            raise Exception(f"User {user_id} not found")  # noqa: TRY002
        email = attributes.get("email")
        if email is not None:
            if any(u.email == email and u.id != str(user_id) for u in self._users.values()):
                raise Exception(f"A user with email {email} already registered")  # noqa: TRY002
            user.email = email
            # email_confirm absent or False leaves the new address
            # unverified, exactly as the real API does - the behaviour the
            # correction flow depends on.
            user.email_confirmed_at = (
                "2026-01-01T00:00:00+00:00" if attributes.get("email_confirm") else None
            )
        return _FakeGetUserResult(user)

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
        elif link_type in ("recovery", "signup", "magiclink"):
            # "signup" (email-verification link for the combined signup
            # flow), "magiclink" (the link sent when a Super Admin
            # corrects a mistyped signup address - there is no password to
            # pass, so it cannot be a "signup" link) and "recovery" all
            # require an *existing* user and raise if none matches — the
            # real API's behaviour.
            user = next((u for u in self._users.values() if u.email == email), None)
            if user is None:
                raise Exception(f"User {email} not found")  # noqa: TRY002
        else:
            raise NotImplementedError(f"generate_link type={link_type}")

        action_link = f"https://fake.supabase.test/auth/v1/verify?type={link_type}&token={token}&redirect_to={redirect_to}"
        return _FakeGenerateLinkResult(user, action_link, hashed_token=f"pkce_{token}", email_otp="123456")


class _FakeAuth:
    def __init__(self):
        self.admin = _FakeAuthAdmin()


class FakeSupabaseClient:
    def __init__(self):
        self._tables: dict[str, _FakeTable] = {}
        self._storage_objects: dict[str, bytes] = {}
        self.storage = _FakeStorage(self._storage_objects)
        self.auth = _FakeAuth()
        self._seed_withdrawal_automation_policy()

    def _seed_withdrawal_automation_policy(self) -> None:
        """One disabled policy row, exactly as migration 20261031010000
        creates it.

        Seeded in the constructor rather than by each test because the
        state that matters is the default: every test starts from "every
        withdrawal needs a human", and a test that wants automation has to
        say so. A fake with no row at all would instead exercise the
        AUTO_POLICY_UNAVAILABLE fallback everywhere, which is a different
        thing and would hide the difference between "off" and "unreadable".
        """
        self.seed(
            "withdrawal_automation_policy",
            {
                "id": True,
                "enabled": False,
                "max_amount_tzs": "500000.00",
                "merchant_rolling_24h_limit_tzs": "1000000.00",
                "version": 1,
                "updated_at": None,
                "updated_by": None,
            },
        )

    def enable_withdrawal_automation_policy(
        self, *, max_amount_tzs: str = "500000.00", rolling_24h_limit_tzs: str = "1000000.00"
    ) -> dict:
        """Turn the database half of withdrawal automation on.

        Automation needs BOTH the deployment flags and this policy row (see
        app/services/withdrawal_policy.py for the precedence), so a test
        that sets only the environment variables gets manual approval -
        correctly. This is the other half.
        """
        rows = self.table("withdrawal_automation_policy")._table.rows
        rows[0].update(
            {
                "enabled": True,
                "max_amount_tzs": max_amount_tzs,
                "merchant_rolling_24h_limit_tzs": rolling_24h_limit_tzs,
            }
        )
        return rows[0]

    def break_withdrawal_automation_policy(self) -> None:
        """Leave the policy unreadable, to exercise the fail-closed path.

        Removing the row is the closest in-memory equivalent of the row
        being absent, several rows existing, or a read erroring - all of
        which load_stored_policy collapses to the same answer.
        """
        self.table("withdrawal_automation_policy")._table.rows.clear()

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

    def _update_withdrawal_automation_policy(self, params: dict) -> _Result:
        """Mirrors supabase/migrations/20261031040000.

        The point of the real function is that the policy write and its
        audit row are ONE transaction, so this writes both too — and a
        test that makes the audit insert fail must see the policy
        unchanged, which is the behaviour the separate-requests version
        could not offer.
        """
        rows = self.table("withdrawal_automation_policy")._table.rows
        row = next(iter(rows), None)
        if row is None:
            return _Result({"outcome": "unavailable"})

        if row.get("version") != params["p_expected_version"]:
            return _Result(
                {
                    "outcome": "conflict",
                    "current_version": row.get("version"),
                    "current_enabled": row.get("enabled"),
                    "current_max_amount_tzs": str(row.get("max_amount_tzs")),
                    "current_rolling_24h_limit_tzs": str(row.get("merchant_rolling_24h_limit_tzs")),
                }
            )

        before = dict(row)
        money = Decimal("0.01")
        after = {
            "enabled": bool(params["p_enabled"]),
            "max_amount_tzs": str(Decimal(str(params["p_max_amount"])).quantize(money)),
            "merchant_rolling_24h_limit_tzs": str(
                Decimal(str(params["p_rolling_limit"])).quantize(money)
            ),
            "version": before["version"] + 1,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": params["p_actor_id"],
        }

        # Written before the policy is mutated, so that a failure here
        # leaves the policy alone — one transaction, as the real function
        # has. A test can make this raise by seeding an audit_logs
        # constraint the fake enforces.
        self.table("audit_logs")._table.insert(
            {
                "actor_id": params["p_actor_id"],
                "actor_type": "user",
                "action": "withdrawal_automation_policy.updated",
                "resource_type": "withdrawal_automation_policy",
                "ip_address": params.get("p_ip"),
                "user_agent": params.get("p_user_agent"),
                "metadata": {
                    "correlation_id": params.get("p_correlation_id"),
                    "confirmed": bool(params.get("p_confirmed")),
                    "previous": {
                        "version": before["version"],
                        "enabled": before["enabled"],
                        "max_amount_tzs": str(
                            Decimal(str(before["max_amount_tzs"])).quantize(Decimal("0.01"))
                        ),
                        "merchant_rolling_24h_limit_tzs": str(
                            Decimal(str(before["merchant_rolling_24h_limit_tzs"])).quantize(
                                Decimal("0.01")
                            )
                        ),
                        "automation_active": bool(params.get("p_deployment_allows"))
                        and bool(before["enabled"]),
                    },
                    "new": {
                        "version": after["version"],
                        "enabled": after["enabled"],
                        "max_amount_tzs": after["max_amount_tzs"],
                        "merchant_rolling_24h_limit_tzs": after["merchant_rolling_24h_limit_tzs"],
                        "automation_active": bool(params.get("p_deployment_allows"))
                        and after["enabled"],
                    },
                    "effective": {
                        "max_amount_tzs": str(
                            min(
                                Decimal(str(params.get("p_deployment_max") or 0)),
                                Decimal(after["max_amount_tzs"]),
                            ).quantize(money)
                        ),
                        "rolling_24h_limit_tzs": str(
                            min(
                                Decimal(str(params.get("p_deployment_rolling") or 0)),
                                Decimal(after["merchant_rolling_24h_limit_tzs"]),
                            ).quantize(money)
                        ),
                    },
                },
            }
        )

        row.update(after)
        return _Result(
            {
                "outcome": "ok",
                "version": after["version"],
                "enabled": after["enabled"],
                "max_amount_tzs": after["max_amount_tzs"],
                "merchant_rolling_24h_limit_tzs": after["merchant_rolling_24h_limit_tzs"],
                "updated_at": after["updated_at"],
                "previous_version": before["version"],
                "previous_enabled": before["enabled"],
            }
        )

    def _admin_overview_money(self, params: dict) -> _Result:
        """Mirrors supabase/migrations/20261031030000_admin_overview_money.sql.

        Six sums over two tables: successful collection transactions by
        gross_amount, and credit entries on the single platform_revenue
        ledger account — each for today, this month, and all time.

        Returns every amount as a STRING, exactly as the real function
        does. That is not cosmetic: the function casts to text so a
        numeric(14,2) does not come back through a JSON number as a
        float, and a fake that handed back Decimals would hide a caller
        that had forgotten to parse.
        """
        day_start = params.get("p_day_start")
        month_start = params.get("p_month_start")

        revenue_account_id = next(
            (
                a["id"]
                for a in self.table("ledger_accounts")._table.rows
                if a.get("purpose") == "platform_revenue" and not a.get("merchant_id")
            ),
            None,
        )

        def total(rows, field: str, since: str | None) -> Decimal:
            running = Decimal(0)
            for row in rows:
                created = row.get("created_at")
                if since is not None and (not created or str(created) < str(since)):
                    continue
                running += Decimal(str(row.get(field) or 0))
            return running

        collections = [
            t
            for t in self.table("transactions")._table.rows
            if t.get("type") == "collection" and t.get("status") == "successful"
        ]
        revenue = [
            e
            for e in self.table("ledger_entries")._table.rows
            if revenue_account_id
            and str(e.get("ledger_account_id")) == str(revenue_account_id)
            # Credits only. Reversals are debits and are deliberately not
            # subtracted — see the migration header.
            and e.get("direction") == "credit"
        ]

        return _Result(
            {
                "collections_today": str(total(collections, "gross_amount", day_start)),
                "collections_this_month": str(total(collections, "gross_amount", month_start)),
                "collections_total": str(total(collections, "gross_amount", None)),
                "revenue_today": str(total(revenue, "amount", day_start)),
                "revenue_this_month": str(total(revenue, "amount", month_start)),
                "revenue_total": str(total(revenue, "amount", None)),
            }
        )

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

        # DEPLOYMENT ceiling and permission. Since 20261031040000 the
        # function no longer trusts a caller's view of the live policy:
        # it reads the row itself, in the transaction that authorises the
        # payout, and combines the two with AND and LEAST so runtime can
        # only tighten. p_policy_version is accepted and ignored for the
        # same reason - the version that matters is the one on the row
        # this transaction locked.
        deployment_max = Decimal(str(params["p_auto_max"]))
        deployment_rolling = Decimal(str(params["p_auto_daily_limit"]))
        deployment_allows = bool(params["p_automation_enabled"])

        policy = next(iter(self.table("withdrawal_automation_policy")._table.rows), None)
        if policy is None:
            automation_enabled = False
            auto_max = Decimal(0)
            auto_daily_limit = Decimal(0)
            policy_version = None
        else:
            automation_enabled = deployment_allows and bool(policy.get("enabled"))
            auto_max = min(deployment_max, Decimal(str(policy.get("max_amount_tzs") or 0)))
            auto_daily_limit = min(
                deployment_rolling,
                Decimal(str(policy.get("merchant_rolling_24h_limit_tzs") or 0)),
            )
            policy_version = policy.get("version")

        if auto_max <= 0 or auto_daily_limit <= 0:
            automation_enabled = False

        def _decide(outcome: str, reason: str, code: str, **extra) -> _Result:
            """Writes the decision columns the real function writes, so a
            test can assert on the code and the policy version rather than
            parsing an English sentence."""
            row["auto_decision_reason"] = reason
            row["auto_decision_code"] = code
            row["auto_policy_version"] = policy_version
            row["auto_decided_at"] = datetime.now(timezone.utc).isoformat()
            return _Result({"outcome": outcome, "reason": reason, "code": code, **extra})

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
            return _decide(
                "rejected", reason, "DAILY_LIMIT_EXCEEDED", already_requested_today=str(requested_today)
            )

        if not automation_enabled:
            if policy_version is None:
                reason = "Manual approval required: the automation policy could not be read."
                code = "AUTO_POLICY_UNAVAILABLE"
            else:
                reason = "Manual approval required: withdrawal automation is not enabled."
                code = "AUTO_POLICY_DISABLED"
        elif amount > auto_max:
            # `>` and not `>=`: the ceiling is inclusive, so a withdrawal
            # for exactly the maximum is eligible.
            reason = (
                f"Manual approval required: exceeds the {auto_max} TZS "
                "per-transaction limit for automatic processing."
            )
            code = "AUTO_AMOUNT_LIMIT_EXCEEDED"
        else:
            auto_today = _earlier_rows(auto_only=True)
            if auto_today + amount > auto_daily_limit:
                reason = (
                    f"Manual approval required: would exceed the {auto_daily_limit} TZS "
                    f"daily limit for automatic processing (already auto-processed today: {auto_today} TZS)."
                )
                code = "AUTO_ROLLING_LIMIT_EXCEEDED"
            else:
                reason = "Eligible: verified merchant, no open high-risk alerts, within auto-withdrawal limits."
                row["auto_approved"] = True
                return _decide("auto", reason, "AUTO_ELIGIBLE")

        return _decide("manual", reason, code)

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
