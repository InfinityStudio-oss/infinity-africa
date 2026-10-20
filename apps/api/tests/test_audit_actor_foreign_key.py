"""An API key is not a Supabase Auth user, and audit_logs knows it.

Reported from production on 2026-10-20 (Sentry INFINITYPAY-API-15):

    APIError: insert or update on table "audit_logs" violates foreign key
    constraint "audit_logs_actor_id_fkey"

`audit_logs.actor_id` is `references auth.users (id)`, and its column
comment says as much. But when a caller authenticates with an API key,
`caller.actor_id` is the **api_keys row id** - that is how
app/auth/dependencies.py builds the actor - and twelve routers pass it
straight through as `actor_id=caller.actor_id`.

So any API-key call to an audited endpoint tried to write a uuid that is
not in auth.users, the foreign key refused it, and `write_audit_log`
raised. Not the best-effort variant: the raising one, deliberately used on
money paths. The disbursement or collection had already been created by
then, so the partner received a 500 for work that had in fact succeeded -
the worst possible outcome, because the obvious response to a 500 is to
retry.

**No test could have caught this.** The fake Supabase client enforces no
foreign keys, so every one of these paths was green. That is the recurring
shape of this project's production bugs, and it is why these tests assert
the *property that avoids the constraint* rather than trying to simulate
it: an actor that is not a user must never reach the actor_id column.

The identity is not lost - it moves to metadata, where it does not claim
to be an auth user, and actor_type still records what kind of actor it was.
"""

import uuid

import pytest

from app.services.audit import write_audit_log, write_audit_log_best_effort


def _rows(fake_client):
    return fake_client.table("audit_logs")._table.rows


def _write(fake_client, **kwargs):
    write_audit_log(
        fake_client,
        action="collection.status_refreshed",
        resource_type="collection",
        resource_id=uuid.uuid4(),
        **kwargs,
    )
    return _rows(fake_client)[-1]


# --- the bug ------------------------------------------------------------


def test_an_api_key_actor_never_reaches_the_actor_id_column(fake_client):
    """The exact production failure: this uuid is an api_keys row id, and
    the column is a foreign key to auth.users."""
    api_key_id = uuid.uuid4()

    row = _write(fake_client, actor_id=api_key_id, actor_type="api_key")

    assert row["actor_id"] is None


def test_the_api_key_identity_is_kept_in_metadata(fake_client):
    """Dropping the id would make the audit trail useless for exactly the
    callers most worth auditing."""
    api_key_id = uuid.uuid4()

    row = _write(fake_client, actor_id=api_key_id, actor_type="api_key")

    assert row["metadata"]["actor_reference"] == str(api_key_id)
    assert row["actor_type"] == "api_key"


def test_a_system_actor_is_handled_the_same_way(fake_client):
    system_id = uuid.uuid4()

    row = _write(fake_client, actor_id=system_id, actor_type="system")

    assert row["actor_id"] is None
    assert row["metadata"]["actor_reference"] == str(system_id)


def test_a_system_actor_with_no_id_is_unchanged(fake_client):
    """The common case for sweeps and callbacks - nothing to move."""
    row = _write(fake_client, actor_type="system")

    assert row["actor_id"] is None
    assert "actor_reference" not in row["metadata"]


# --- what must not change ----------------------------------------------


def test_a_real_user_still_populates_actor_id(fake_client):
    """The whole point of the column. Moving a genuine auth user into
    metadata would quietly empty the compliance trail."""
    user_id = uuid.uuid4()

    row = _write(fake_client, actor_id=user_id, actor_type="user")

    assert row["actor_id"] == str(user_id)
    assert "actor_reference" not in row["metadata"]


def test_a_user_actor_with_no_id_stays_null(fake_client):
    row = _write(fake_client, actor_type="user")

    assert row["actor_id"] is None


def test_existing_metadata_is_preserved_alongside_the_reference(fake_client):
    row = _write(
        fake_client,
        actor_id=uuid.uuid4(),
        actor_type="api_key",
        metadata={"status": "successful", "method": "STK_PUSH"},
    )

    assert row["metadata"]["status"] == "successful"
    assert row["metadata"]["method"] == "STK_PUSH"
    assert "actor_reference" in row["metadata"]


def test_a_caller_supplied_actor_reference_is_not_overwritten(fake_client):
    """setdefault, not assignment - a caller that already recorded one
    means it deliberately."""
    row = _write(
        fake_client,
        actor_id=uuid.uuid4(),
        actor_type="api_key",
        metadata={"actor_reference": "deliberate"},
    )

    assert row["metadata"]["actor_reference"] == "deliberate"


def test_the_callers_metadata_dict_is_not_mutated(fake_client):
    """The caller's dict is often a literal reused across a request; adding
    to it in place would leak the reference into unrelated records."""
    supplied: dict = {"status": "successful"}

    _write(fake_client, actor_id=uuid.uuid4(), actor_type="api_key", metadata=supplied)

    assert supplied == {"status": "successful"}


# --- the money paths that reported it ----------------------------------


@pytest.mark.parametrize(
    "action,resource_type",
    [
        ("collection.status_refreshed", "collection"),
        ("collection.created", "collection"),
        ("disbursement.requested", "disbursement"),
        ("invoice.created", "invoice"),
    ],
)
def test_money_path_audits_survive_an_api_key_caller(fake_client, action, resource_type):
    """These are the routers that pass caller.actor_id straight through.
    Each writes with the raising variant, so a refused insert becomes a 500
    *after* the money work has already been done."""
    write_audit_log(
        fake_client,
        action=action,
        resource_type=resource_type,
        resource_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        actor_type="api_key",
        merchant_id=uuid.uuid4(),
    )

    row = _rows(fake_client)[-1]
    assert row["actor_id"] is None
    assert row["action"] == action


def test_the_best_effort_variant_benefits_too(fake_client):
    write_audit_log_best_effort(
        fake_client,
        action="withdrawal.viewed",
        resource_type="disbursement",
        resource_id=uuid.uuid4(),
        actor_id=uuid.uuid4(),
        actor_type="api_key",
    )

    assert _rows(fake_client)[-1]["actor_id"] is None
