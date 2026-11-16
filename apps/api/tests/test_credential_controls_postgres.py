"""The three credential controls, proved against real Postgres with RLS
actually enforcing.

The security review asked whether a merchant can grant themselves payout
access. The rotation fix answered one route to it; it did not answer the
question, because the API is not the only way to write these rows.
`api_keys` carries an RLS policy that is `for all` - not `for select` -
to any caller holding MERCHANT_ADMIN or DEVELOPER on that merchant, with
no column restriction:

    create policy "merchant admins and developers can manage their api keys"
      on public.api_keys for all
      using (public.current_user_merchant_role(merchant_id) in (...))
      with check (public.current_user_merchant_role(merchant_id) in (...));

So a merchant's own dashboard JWT can UPDATE their own api_keys rows
directly through Supabase REST, never touching our API, and
`extra="forbid"` on a Pydantic model is irrelevant to that path. What has
to stop it is in the database and in authentication:

1. `api_keys_payout_requires_enablement` fires BEFORE INSERT OR UPDATE OF
   key_type, environment - so promoting a key to `payout` is refused
   unless a Super Admin has enabled that environment for the merchant.
2. `scopes` is NOT in that trigger's column list, so a direct write of
   payout scopes onto a `standard` key does land. Authentication is what
   makes it inert: verify_api_key intersects the stored scopes with the
   ones the key's type may hold.
3. RLS still pins the tenant, so none of this reaches another merchant.

Each test below drives the path a merchant actually has - `set role
authenticated` with their own JWT claims - rather than the service role,
because a test that runs as the owner proves nothing about RLS.

**On grants:** this cluster is built by our migrations, which do not grant
table privileges to `authenticated`; hosted Supabase does by default. The
fixture grants them explicitly so the policy and the trigger are the only
things left standing between the merchant and the row. That models the
hosted posture rather than assuming it away - and it is the pessimistic
assumption, which is the right one for a control test.
"""

import os
import uuid

import pytest

psycopg2 = pytest.importorskip("psycopg2", reason="psycopg2 not installed; credential controls not exercised")

DATABASE_URL = os.environ.get("TEST_PAYOUT_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="TEST_PAYOUT_DATABASE_URL is not set; the credential controls are NOT exercised in this run",
)


def _guard_against_a_real_database(url: str) -> None:
    lowered = url.lower()
    for marker in ("supabase.co", "supabase.com", "pooler."):
        if marker in lowered:
            pytest.fail(f"TEST_PAYOUT_DATABASE_URL points at {marker}. Use a disposable local database.")
    name = lowered.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    if "test" not in name:
        pytest.fail(
            f"TEST_PAYOUT_DATABASE_URL database name {name!r} does not contain 'test'. "
            "These tests grant privileges and write credential rows."
        )


@pytest.fixture(scope="module")
def admin():
    _guard_against_a_real_database(DATABASE_URL)
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("select to_regclass('public.api_keys')")
        if cur.fetchone()[0] is None:
            conn.close()
            pytest.fail("No api_keys table. Apply the full migration set first.")
        # Hosted Supabase grants these; our migrations do not. Granting
        # them here leaves the policy and the trigger as the only guards,
        # which is what these tests are about.
        cur.execute(
            "grant select, insert, update, delete on public.api_keys, "
            "public.merchant_payout_settings to authenticated"
        )
        cur.execute("grant usage on schema public to authenticated")
    yield conn
    conn.close()


@pytest.fixture
def merchant(admin):
    """A merchant, a MERCHANT_ADMIN who belongs to it, and one standard
    key of theirs."""
    suffix = uuid.uuid4().hex[:8]
    code = "27" + f"{uuid.uuid4().int % 1000000:06d}"
    with admin.cursor() as cur:
        cur.execute(
            "insert into public.merchants (business_name, contact_email, merchant_code) "
            "values (%s, %s, %s) returning id",
            (f"Cred Test {suffix}", f"cred-{suffix}@example.test", code),
        )
        merchant_id = cur.fetchone()[0]
        cur.execute(
            "insert into auth.users (email) values (%s) returning id",
            (f"admin-{suffix}@example.test",),
        )
        user_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.merchant_users (merchant_id, user_id, role, status) "
            "values (%s, %s, 'MERCHANT_ADMIN', 'active')",
            (merchant_id, user_id),
        )
        cur.execute(
            "insert into public.api_keys "
            "(merchant_id, name, environment, public_key, key_prefix, key_last4, hashed_key, "
            " scopes, status, key_type) "
            "values (%s, 'Test key', 'sandbox', %s, 'sk_test', 'ab12', %s, "
            " ARRAY['collections:write']::text[], 'active', 'standard') returning id",
            (merchant_id, f"pk_test_{suffix}", f"hash_{suffix}"),
        )
        key_id = cur.fetchone()[0]
    return merchant_id, user_id, key_id


def _as_merchant_user(conn, user_id):
    """Become that signed-in user: their JWT claims, and the role a
    Supabase REST request actually arrives as."""
    with conn.cursor() as cur:
        cur.execute(
            "select set_config('request.jwt.claims', %s, true)",
            ('{"sub": "%s", "role": "authenticated"}' % user_id,),
        )
        cur.execute("set local role authenticated")


def _attempt(admin, user_id, sql, params=()):
    """Run one statement as the merchant user, in its own transaction.

    Returns None on success, or the Postgres error. A separate
    transaction per attempt because a refusal aborts the one it is in.
    """
    conn = psycopg2.connect(DATABASE_URL)
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(
                "select set_config('request.jwt.claims', %s, true)",
                ('{"sub": "%s", "role": "authenticated"}' % user_id,),
            )
            cur.execute("set local role authenticated")
            cur.execute(sql, params)
            cur.execute("reset role")
        conn.commit()
        return None
    except psycopg2.Error as exc:
        conn.rollback()
        return exc
    finally:
        conn.close()


def _key(admin, key_id):
    with admin.cursor() as cur:
        cur.execute(
            "select key_type, scopes, environment, status from public.api_keys where id = %s",
            (key_id,),
        )
        row = cur.fetchone()
    return {"key_type": row[0], "scopes": row[1], "environment": row[2], "status": row[3]}


# --- the merchant really can reach the row (so the rest means something) -----


def test_the_rls_policy_does_let_a_merchant_admin_write_their_own_key(admin, merchant):
    """Establishes the premise before testing the controls.

    If this failed, every test below would pass for the wrong reason -
    they would be proving that the merchant cannot reach the table at
    all, rather than that the guards hold when they can.
    """
    merchant_id, user_id, key_id = merchant

    error = _attempt(
        admin, user_id, "update public.api_keys set name = 'renamed by merchant' where id = %s", (key_id,)
    )

    assert error is None, f"the merchant could not write their own key at all: {error}"
    with admin.cursor() as cur:
        cur.execute("select name from public.api_keys where id = %s", (key_id,))
        assert cur.fetchone()[0] == "renamed by merchant"


# --- control 1: a merchant cannot promote a key to payout --------------------


def test_a_merchant_cannot_promote_their_own_key_to_payout(admin, merchant):
    """The direct-write version of the escalation. No API, no rotation -
    just a merchant admin's own JWT against the table."""
    merchant_id, user_id, key_id = merchant

    error = _attempt(
        admin, user_id, "update public.api_keys set key_type = 'payout' where id = %s", (key_id,)
    )

    assert error is not None, "a merchant promoted their own key to payout"
    assert "PAYOUT_NOT_ENABLED" in str(error), str(error)
    assert _key(admin, key_id)["key_type"] == "standard"


def test_a_merchant_cannot_insert_a_payout_key_from_nothing(admin, merchant):
    """Promotion blocked, so the next thing to try is creating one."""
    merchant_id, user_id, _key_id = merchant
    suffix = uuid.uuid4().hex[:8]

    error = _attempt(
        admin,
        user_id,
        "insert into public.api_keys (merchant_id, name, environment, public_key, key_prefix, "
        " key_last4, hashed_key, scopes, status, key_type) "
        "values (%s, 'Self-granted', 'sandbox', %s, 'sk_test', 'zz99', %s, "
        " ARRAY['payouts:create']::text[], 'active', 'payout')",
        (merchant_id, f"pk_test_{suffix}", f"hash_{suffix}"),
    )

    assert error is not None, "a merchant minted themselves a payout key"
    assert "PAYOUT_NOT_ENABLED" in str(error), str(error)


def test_a_merchant_cannot_switch_a_payout_key_to_an_unenabled_environment(admin, merchant):
    """Sandbox granted, live not. The trigger watches `environment` as
    well as `key_type` for exactly this move."""
    merchant_id, user_id, key_id = merchant
    with admin.cursor() as cur:
        cur.execute(
            "insert into public.merchant_payout_settings "
            "(merchant_id, sandbox_enabled, live_enabled, version) "
            "values (%s, true, false, 1)",
            (merchant_id,),
        )
        cur.execute(
            "update public.api_keys set key_type = 'payout', "
            "scopes = ARRAY['payouts:create','payouts:read']::text[] where id = %s",
            (key_id,),
        )

    error = _attempt(
        admin, user_id, "update public.api_keys set environment = 'live' where id = %s", (key_id,)
    )

    assert error is not None, "a merchant moved their payout key to live"
    assert "PAYOUT_NOT_ENABLED" in str(error), str(error)
    assert _key(admin, key_id)["environment"] == "sandbox"


def test_the_promotion_succeeds_once_a_super_admin_has_enabled_it(admin, merchant):
    """The control is a gate, not a wall - otherwise it would be
    indistinguishable from the feature being broken."""
    merchant_id, user_id, key_id = merchant
    with admin.cursor() as cur:
        cur.execute(
            "insert into public.merchant_payout_settings "
            "(merchant_id, sandbox_enabled, live_enabled, version) "
            "values (%s, true, false, 1)",
            (merchant_id,),
        )

    error = _attempt(
        admin, user_id, "update public.api_keys set key_type = 'payout' where id = %s", (key_id,)
    )

    assert error is None, str(error)
    assert _key(admin, key_id)["key_type"] == "payout"


# --- control 2: a merchant cannot grant themselves payout settings ----------


def test_a_merchant_cannot_enable_their_own_payout_settings(admin, merchant):
    """The obvious way round the trigger: grant yourself the enablement
    the trigger checks for. merchant_payout_settings has RLS on and no
    policy at all, which is deny-all to everyone but the service role."""
    merchant_id, user_id, _key_id = merchant

    error = _attempt(
        admin,
        user_id,
        "insert into public.merchant_payout_settings "
        "(merchant_id, sandbox_enabled, live_enabled, version) "
        "values (%s, true, true, 1)",
        (merchant_id,),
    )

    assert error is not None, "a merchant granted themselves payout access"
    with admin.cursor() as cur:
        cur.execute(
            "select count(*) from public.merchant_payout_settings where merchant_id = %s",
            (merchant_id,),
        )
        assert cur.fetchone()[0] == 0


def test_a_merchant_cannot_unpause_themselves(admin, merchant):
    """Pause is the fast lever for a suspected leak. A merchant able to
    lift it would make it worthless."""
    merchant_id, user_id, _key_id = merchant
    with admin.cursor() as cur:
        cur.execute(
            "insert into public.merchant_payout_settings "
            "(merchant_id, sandbox_enabled, paused, paused_reason, version) "
            "values (%s, true, true, 'Suspected key leak', 1)",
            (merchant_id,),
        )

    error = _attempt(
        admin,
        user_id,
        "update public.merchant_payout_settings set paused = false where merchant_id = %s",
        (merchant_id,),
    )

    with admin.cursor() as cur:
        cur.execute(
            "select paused from public.merchant_payout_settings where merchant_id = %s",
            (merchant_id,),
        )
        still_paused = cur.fetchone()[0]
    assert still_paused is True, f"a merchant unpaused themselves (error was {error})"


def test_a_merchant_cannot_raise_their_own_daily_limit(admin, merchant):
    merchant_id, user_id, _key_id = merchant
    with admin.cursor() as cur:
        cur.execute(
            "insert into public.merchant_payout_settings "
            "(merchant_id, sandbox_enabled, daily_limit_tzs, version) "
            "values (%s, true, 50000.00, 1)",
            (merchant_id,),
        )

    _attempt(
        admin,
        user_id,
        "update public.merchant_payout_settings set daily_limit_tzs = 99999999.00 "
        "where merchant_id = %s",
        (merchant_id,),
    )

    with admin.cursor() as cur:
        cur.execute(
            "select daily_limit_tzs from public.merchant_payout_settings where merchant_id = %s",
            (merchant_id,),
        )
        assert cur.fetchone()[0] == 50000.00


# --- control 3: the scopes write lands, and authentication makes it inert ----


def test_a_direct_scopes_write_does_land_which_is_why_auth_must_narrow(admin, merchant):
    """The honest half of the story.

    `scopes` is not in the trigger's column list, so this write succeeds
    at the database layer. That is not a hole on its own - it is the
    reason the scope allowlist is enforced at authentication rather than
    only at creation. This test documents the state the narrowing has to
    cope with; test_api_key_field_protection.py proves it does.
    """
    merchant_id, user_id, key_id = merchant

    error = _attempt(
        admin,
        user_id,
        "update public.api_keys set scopes = ARRAY['payouts:create','payouts:read']::text[] "
        "where id = %s",
        (key_id,),
    )

    assert error is None, f"expected this to land at the DB layer: {error}"
    stored = _key(admin, key_id)
    assert "payouts:create" in stored["scopes"]
    assert stored["key_type"] == "standard", (
        "the key is still standard, so authentication will strip these scopes"
    )


# --- RLS still pins the tenant ----------------------------------------------


def test_a_merchant_cannot_touch_another_merchants_key(admin, merchant):
    merchant_id, user_id, _key_id = merchant
    suffix = uuid.uuid4().hex[:8]
    code = "27" + f"{uuid.uuid4().int % 1000000:06d}"
    with admin.cursor() as cur:
        cur.execute(
            "insert into public.merchants (business_name, contact_email, merchant_code) "
            "values (%s, %s, %s) returning id",
            (f"Other {suffix}", f"other-{suffix}@example.test", code),
        )
        other_id = cur.fetchone()[0]
        cur.execute(
            "insert into public.api_keys "
            "(merchant_id, name, environment, public_key, key_prefix, key_last4, hashed_key, "
            " scopes, status, key_type) "
            "values (%s, 'Their key', 'live', %s, 'sk_live', 'cd34', %s, "
            " ARRAY['collections:read']::text[], 'active', 'standard') returning id",
            (other_id, f"pk_live_{suffix}", f"hash_other_{suffix}"),
        )
        other_key_id = cur.fetchone()[0]

    _attempt(
        admin,
        user_id,
        "update public.api_keys set status = 'revoked' where id = %s",
        (other_key_id,),
    )

    assert _key(admin, other_key_id)["status"] == "active", "a merchant revoked another's key"


def test_a_merchant_cannot_read_another_merchants_keys(admin, merchant):
    merchant_id, user_id, _key_id = merchant
    conn = psycopg2.connect(DATABASE_URL)
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(
                "select set_config('request.jwt.claims', %s, true)",
                ('{"sub": "%s", "role": "authenticated"}' % user_id,),
            )
            cur.execute("set local role authenticated")
            cur.execute("select distinct merchant_id from public.api_keys")
            visible = {row[0] for row in cur.fetchall()}
            cur.execute("reset role")
        conn.rollback()
    finally:
        conn.close()

    assert visible <= {merchant_id}, f"other merchants' keys were visible: {visible - {merchant_id}}"
