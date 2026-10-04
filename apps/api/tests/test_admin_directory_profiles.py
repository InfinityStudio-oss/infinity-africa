"""Looking up display names must not cost one round trip per row.

Supabase Auth has no "get these N users" call, so a name costs a request
per user. batch_user_profiles read as a batch helper but was a dict
comprehension calling the single-user lookup in a loop — so every Super
Admin list page paid one sequential network round trip per row it
displayed, and the Business Users page (up to 100 rows) took seconds to
open.

These pin the two things that matter: the lookups overlap, and one bad
user still cannot break the page.
"""

import time
import types

import pytest

from app.services.admin_directory import batch_user_profiles, best_effort_user_profile


def _fake_client(latency: float = 0.0, fail_ids: set[str] | None = None):
    failing = fail_ids or set()

    class Admin:
        # Instance attribute, set in _fake_client below — a class-level
        # list would be shared between tests.
        calls: list[str]

        def get_user_by_id(self, user_id):
            Admin.calls.append(user_id)
            if latency:
                time.sleep(latency)
            if user_id in failing:
                raise RuntimeError("no such user")
            return types.SimpleNamespace(
                user=types.SimpleNamespace(
                    user_metadata={"full_name": f"Name {user_id}"},
                    email=f"{user_id}@example.tz",
                    last_sign_in_at=None,
                )
            )

    Admin.calls = []
    client = types.SimpleNamespace(auth=types.SimpleNamespace(admin=Admin()))
    return client, Admin


def test_every_requested_profile_comes_back():
    client, _ = _fake_client()
    ids = {f"user-{i}" for i in range(25)}

    profiles = batch_user_profiles(client, ids)

    assert set(profiles) == ids
    assert all(profiles[i]["email"] == f"{i}@example.tz" for i in ids)


def test_each_profile_is_matched_to_its_own_user():
    """The pool returns results in completion order; zipping them back onto
    the wrong ids would put one merchant's name against another's row."""
    client, _ = _fake_client()
    ids = {f"user-{i}" for i in range(40)}

    profiles = batch_user_profiles(client, ids)

    for user_id, profile in profiles.items():
        assert profile["full_name"] == f"Name {user_id}"
        assert profile["email"] == f"{user_id}@example.tz"


def test_the_lookups_overlap_instead_of_queueing():
    """The regression this exists for. Thirty users at 50ms each is 1.5s
    in sequence; overlapped it is a small fraction of that. The threshold
    is loose on purpose — this asserts "concurrent", not a specific
    worker count, so tuning the pool does not break it."""
    client, _ = _fake_client(latency=0.05)
    ids = {f"user-{i}" for i in range(30)}

    started = time.perf_counter()
    batch_user_profiles(client, ids)
    elapsed = time.perf_counter() - started

    sequential = 30 * 0.05
    assert elapsed < sequential / 3, f"{elapsed:.2f}s — lookups are still effectively sequential"


def test_one_unresolvable_user_does_not_break_the_page():
    """A deleted account is a cosmetic gap, not a reason to fail an admin
    list. It must also not take the rest of the pool down with it."""
    client, _ = _fake_client(fail_ids={"user-3", "user-7"})
    ids = {f"user-{i}" for i in range(10)}

    profiles = batch_user_profiles(client, ids)

    assert set(profiles) == ids
    assert profiles["user-3"] == {"full_name": None, "email": None, "last_sign_in_at": None}
    assert profiles["user-7"]["full_name"] is None
    assert profiles["user-1"]["email"] == "user-1@example.tz"


def test_no_users_makes_no_calls():
    client, admin = _fake_client()
    assert batch_user_profiles(client, set()) == {}
    assert admin.calls == []


def test_a_single_user_is_fetched_directly():
    """Not worth a thread pool, and keeps the common one-row path the same
    shape it has always been."""
    client, admin = _fake_client()
    profiles = batch_user_profiles(client, {"user-1"})
    assert profiles["user-1"]["email"] == "user-1@example.tz"
    assert admin.calls == ["user-1"]


def test_each_user_is_fetched_exactly_once():
    """Concurrency must not turn into duplicate requests against an API we
    do not own."""
    client, admin = _fake_client()
    ids = {f"user-{i}" for i in range(15)}

    batch_user_profiles(client, ids)

    assert sorted(admin.calls) == sorted(ids)


@pytest.mark.parametrize("falsy", [None, ""])
def test_blank_ids_are_skipped(falsy):
    client, admin = _fake_client()
    profiles = batch_user_profiles(client, {falsy, "user-1"})
    assert set(profiles) == {"user-1"}
    assert admin.calls == ["user-1"]


def test_the_single_user_helper_still_degrades_quietly():
    client, _ = _fake_client(fail_ids={"gone"})
    assert best_effort_user_profile(client, "gone") == {
        "full_name": None,
        "email": None,
        "last_sign_in_at": None,
    }
