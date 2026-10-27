"""An attempt to act on someone else's merchant should be visible.

`authorize_merchant_action` has always refused these. What it did not do
was tell anyone, so the clean signal for an insecure-direct-object-
reference attempt - a credential that authenticated perfectly, then
reached for a merchant it has no claim to - left no trace an operator
would ever see.

It is now reported, with two deliberate limits:

**Only a complete absence of membership.** Holding the wrong *role*
inside a merchant you legitimately belong to is an everyday permissions
miss - staff hitting an admin-only screen - and alerting on it would bury
the case that matters.

**Deduplicated per actor and target.** An integrator looping over ids
with the wrong key raises one alert, not one per request. A *different*
target from the same actor is still news, which is the property that
keeps this useful against someone walking ids.

Above all: the alert must never change the authorization outcome. The 403
is raised whether or not anyone could be told about it.
"""

import uuid

import pytest
from fastapi import HTTPException

import app.auth.dependencies as deps
from app.auth.dependencies import authorize_merchant_action
from app.schemas.auth import AuthenticatedCaller, AuthenticatedUser


@pytest.fixture
def alerts(monkeypatch, fake_client):
    """Every security alert raised, without sending anything."""
    seen: list[dict] = []
    monkeypatch.setattr(deps, "get_supabase_admin", lambda: fake_client)
    monkeypatch.setattr(deps, "notify_security_event", lambda _client, **kw: seen.append(kw) or True)
    return seen


def _api_key_caller(merchant_id, key_id=None):
    return AuthenticatedCaller(
        actor_type="api_key",
        actor_id=key_id or uuid.uuid4(),
        merchant_id=merchant_id,
        user=None,
    )


def _user_caller(user_id=None, email="staff@example.com"):
    return AuthenticatedCaller(
        actor_type="user",
        actor_id=user_id or uuid.uuid4(),
        merchant_id=None,
        user=AuthenticatedUser(id=user_id or uuid.uuid4(), email=email),
    )


# --- the signal ---------------------------------------------------------


def test_a_key_reaching_for_another_merchant_is_reported(alerts):
    """The case this exists for: the key is valid, the merchant is not its
    own. Nothing was wrong with the credential — something walked an id."""
    mine, theirs = uuid.uuid4(), uuid.uuid4()

    with pytest.raises(HTTPException) as exc:
        authorize_merchant_action(_api_key_caller(mine), theirs)

    assert exc.value.status_code == 403
    assert len(alerts) == 1
    assert alerts[0]["event"] == "merchant.cross_access_denied"


def test_the_alert_names_both_merchants(alerts):
    """Held and attempted — enough to tell a looping integrator from
    someone walking ids."""
    mine, theirs = uuid.uuid4(), uuid.uuid4()

    with pytest.raises(HTTPException):
        authorize_merchant_action(_api_key_caller(mine), theirs)

    extra = alerts[0]["extra"]
    assert extra["Merchant held"] == str(mine)
    assert extra["Merchant attempted"] == str(theirs)
    assert extra["Actor type"] == "api_key"


def test_a_user_with_no_membership_is_reported(alerts, monkeypatch):
    monkeypatch.setattr(deps, "get_merchant_membership", lambda _m, _u: None)
    monkeypatch.setattr(deps, "is_super_admin", lambda _u: False)

    with pytest.raises(HTTPException):
        authorize_merchant_action(_user_caller(), uuid.uuid4())

    assert len(alerts) == 1
    assert alerts[0]["extra"]["Actor type"] == "user"


# --- what must not fire -------------------------------------------------


def test_a_key_acting_on_its_own_merchant_raises_nothing(alerts):
    mine = uuid.uuid4()

    authorize_merchant_action(_api_key_caller(mine), mine)

    assert alerts == []


def test_a_super_admin_raises_nothing(alerts, monkeypatch):
    monkeypatch.setattr(deps, "is_super_admin", lambda _u: True)

    authorize_merchant_action(_user_caller(), uuid.uuid4())

    assert alerts == []


def test_the_wrong_role_inside_your_own_merchant_is_not_an_alert(alerts, monkeypatch):
    """Everyday permissions miss, not an intrusion signal. Alerting on it
    would bury the case that matters."""
    from app.schemas.enums import UserRole

    class _Membership:
        role = UserRole.MERCHANT_STAFF

    monkeypatch.setattr(deps, "get_merchant_membership", lambda _m, _u: _Membership())
    monkeypatch.setattr(deps, "is_super_admin", lambda _u: False)

    with pytest.raises(HTTPException) as exc:
        authorize_merchant_action(_user_caller(), uuid.uuid4(), UserRole.MERCHANT_ADMIN)

    assert exc.value.status_code == 403
    assert alerts == []


# --- deduplication ------------------------------------------------------


def test_the_dedupe_key_is_per_actor_and_target(alerts):
    """One looping integrator must not become a hundred emails, while a
    different target from the same actor stays visible."""
    key_id, mine = uuid.uuid4(), uuid.uuid4()
    first, second = uuid.uuid4(), uuid.uuid4()

    for target in (first, second):
        with pytest.raises(HTTPException):
            authorize_merchant_action(_api_key_caller(mine, key_id), target)

    keys = [a["dedupe_key"] for a in alerts]
    assert keys == [f"{key_id}:{first}", f"{key_id}:{second}"]
    assert len(set(keys)) == 2


# --- the guarantee ------------------------------------------------------


def test_a_failing_alert_still_denies_access(monkeypatch, fake_client):
    """The property that matters most. An authorization decision has been
    made; a notification about it must never change, delay or 500 it."""
    monkeypatch.setattr(deps, "get_supabase_admin", lambda: fake_client)

    def _explode(*_a, **_k):
        raise RuntimeError("alert store unavailable")

    monkeypatch.setattr(deps, "notify_security_event", _explode)

    with pytest.raises(HTTPException) as exc:
        authorize_merchant_action(_api_key_caller(uuid.uuid4()), uuid.uuid4())

    assert exc.value.status_code == 403


def test_the_alert_carries_no_key_material_or_customer_data(alerts):
    """Whatever ends up in a mailbox must be useless to whoever reads it
    later."""
    mine, theirs = uuid.uuid4(), uuid.uuid4()

    with pytest.raises(HTTPException):
        authorize_merchant_action(_api_key_caller(mine), theirs)

    rendered = str(alerts[0])
    for forbidden in ("sk_live", "sk_test", "Authorization", "Bearer", "password", "+255"):
        assert forbidden not in rendered
