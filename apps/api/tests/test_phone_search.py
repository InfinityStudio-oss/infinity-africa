"""Finding a payment by the customer's phone number.

This is the question support is asked all day: "this person says they
paid - did it go through?" The operator has a phone number and nothing
else.

What these tests are really defending is the difference between "no
results" and "no filter". A phone search that matches nothing must
return NOTHING. If an unmatched number instead fell back to showing
every transaction, an operator would read the newest unrelated row as
the customer's payment and tell them money arrived when it did not.
That is a wrong answer about someone's money, delivered confidently,
which is worse than no search at all - so the empty case is pinned on
all four surfaces, and mutation-tested below.

Pinned here:

1. A number is found however it was typed: 0762474101, 255762474101,
   +255 762 474 101, or just the last six digits.
2. A number that matches nothing returns nothing, never everything.
3. A merchant cannot find another merchant's customers this way.
4. Tails are ANCHORED, so the same typed number means the same thing on
   the merchant screen and the Super Admin screen.
5. Something too short to be a phone is not treated as one.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.phone_search import (
    MIN_PARTIAL_DIGITS,
    canonical_or_suffix,
    collection_ids_for_phone,
    looks_like_phone,
)
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    create_transaction,
    make_merchant_member,
    make_super_admin,
)

client = TestClient(app)

# The number under test, in every shape a person might type it.
STORED = "255762474101"
AS_LOCAL = "0762474101"
AS_SPACED = "+255 762 474 101"
AS_TAIL = "474101"

# A number that exists nowhere.
ABSENT = "255700000999"


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("REQUIRE_SUPER_ADMIN_MFA", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _merchant(fake_client):
    return uuid.UUID(create_merchant(fake_client)["id"])


def _merchant_headers(fake_client, merchant_id):
    user_id = uuid.uuid4()
    make_merchant_member(fake_client, merchant_id, user_id, "MERCHANT_ADMIN")
    return auth_headers(user_id)


def _admin_headers(fake_client):
    user_id = uuid.uuid4()
    make_super_admin(fake_client, user_id)
    return auth_headers(user_id, aal="aal2")


def _collection(fake_client, merchant_id, *, phone, reference=None):
    row = {
        "id": str(uuid.uuid4()),
        "merchant_id": str(merchant_id),
        "reference": f"COL-TEST-{uuid.uuid4().hex[:8].upper()}",
        "amount": "1000",
        "currency": "TZS",
        "status": "successful",
        "method": "USSD_PUSH",
        "source": "DASHBOARD_REQUEST",
        "customer_phone": phone,
        "customer_name": None,
        "customer_email": None,
        "merchant_reference": reference,
        "metadata": {},
        "initiated_at": "2026-11-22T10:00:00+00:00",
        "created_at": "2026-11-22T10:00:00+00:00",
        "updated_at": "2026-11-22T10:00:00+00:00",
    }
    return fake_client.seed("collections", row)


def _transaction(fake_client, merchant_id, *, collection_id):
    # The shared factory, so these rows carry everything the response
    # models read. A hand-rolled row that is missing a column fails at
    # serialisation and says nothing about the search.
    return create_transaction(fake_client, merchant_id, collection_id=collection_id)


def _ids(response, key="id"):
    """The ids in a list response, read from a NAMED key.

    Not guessed. The merchant transaction response carries both `id` and
    `collection_id`, so a helper that tried several key names in turn
    quietly compared collection ids against transaction ids and the test
    failed while the code under test was right.
    """
    return {row[key] for row in response.json()["data"]}


# --- the term parser ---------------------------------------------------------


@pytest.mark.parametrize(
    "term",
    [STORED, AS_LOCAL, AS_SPACED, AS_TAIL, "762474101", "0762 474 101"],
)
def test_a_typed_number_is_recognised_as_a_phone(term):
    assert looks_like_phone(term) is True


@pytest.mark.parametrize("term", ["TXN-20261122-ABC123", "PO-4A03D6BE", "", "   ", "abc"])
def test_a_reference_is_not_mistaken_for_a_phone(term):
    assert looks_like_phone(term) is False


def test_something_too_short_is_not_a_phone():
    # Deliberate floor. Three digits would match a large fraction of the
    # table and scan all of it to find them, so a short term belongs to
    # the reference search instead.
    assert looks_like_phone("4101") is False
    assert looks_like_phone("1" * (MIN_PARTIAL_DIGITS - 1)) is False
    assert looks_like_phone("1" * MIN_PARTIAL_DIGITS) is True


@pytest.mark.parametrize("term", [STORED, AS_LOCAL, AS_SPACED, "762474101"])
def test_a_whole_number_normalises_to_the_stored_form(term):
    exact, suffix = canonical_or_suffix(term)
    assert exact == STORED, f"{term!r} should normalise to the stored form"
    assert suffix is None


def test_a_partial_number_becomes_a_suffix():
    exact, suffix = canonical_or_suffix(AS_TAIL)
    assert exact is None
    assert suffix == AS_TAIL


def test_a_term_below_the_floor_is_neither():
    assert canonical_or_suffix("4101") == (None, None)


# --- the collection lookup ---------------------------------------------------


@pytest.mark.parametrize("term", [STORED, AS_LOCAL, AS_SPACED, AS_TAIL])
def test_the_collection_is_found_however_the_number_was_typed(fake_client, term):
    merchant_id = _merchant(fake_client)
    collection = _collection(fake_client, merchant_id, phone=STORED)

    found = collection_ids_for_phone(fake_client, term=term)

    assert found == [collection["id"]], f"{term!r} did not find the collection"


def test_an_unknown_number_finds_nothing_rather_than_everything(fake_client):
    merchant_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, phone=STORED)

    assert collection_ids_for_phone(fake_client, term=ABSENT) == []


def test_scoping_to_a_merchant_excludes_another_merchants_customer(fake_client):
    mine = _merchant(fake_client)
    theirs = _merchant(fake_client)
    _collection(fake_client, theirs, phone=STORED)

    assert collection_ids_for_phone(fake_client, term=STORED, merchant_id=mine) == []


def test_a_tail_is_anchored_to_the_end_of_the_number(fake_client):
    """`%878545` not `%878545%`.

    255878545123 contains the digits 878545 in the MIDDLE. It is a
    different person's number and must not be returned, or the same
    search would mean different things depending on which screen it was
    typed into.
    """
    merchant_id = _merchant(fake_client)
    ends_with = _collection(fake_client, merchant_id, phone="255762878545")
    _collection(fake_client, merchant_id, phone="255878545123")

    found = collection_ids_for_phone(fake_client, term="878545")

    assert found == [ends_with["id"]]


# --- the merchant dashboard --------------------------------------------------


@pytest.mark.parametrize("term", [STORED, AS_LOCAL, AS_SPACED, AS_TAIL])
def test_a_merchant_finds_their_collection_by_phone(fake_client, term):
    merchant_id = _merchant(fake_client)
    headers = _merchant_headers(fake_client, merchant_id)
    collection = _collection(fake_client, merchant_id, phone=STORED)
    _collection(fake_client, merchant_id, phone="255700111222")

    response = client.get(f"/v1/merchant/collections?search={term}", headers=headers)

    assert response.status_code == 200
    assert _ids(response) == {collection["id"]}


def test_a_merchant_searching_an_unknown_number_sees_no_collections(fake_client):
    merchant_id = _merchant(fake_client)
    headers = _merchant_headers(fake_client, merchant_id)
    _collection(fake_client, merchant_id, phone=STORED)

    response = client.get(f"/v1/merchant/collections?search={ABSENT}", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_a_merchant_cannot_find_another_merchants_collection(fake_client):
    mine = _merchant(fake_client)
    theirs = _merchant(fake_client)
    headers = _merchant_headers(fake_client, mine)
    _collection(fake_client, theirs, phone=STORED)

    response = client.get(f"/v1/merchant/collections?search={STORED}", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_a_merchant_can_still_search_by_reference(fake_client):
    # The phone path must not have eaten the reference path.
    merchant_id = _merchant(fake_client)
    headers = _merchant_headers(fake_client, merchant_id)
    collection = _collection(fake_client, merchant_id, phone=STORED, reference="ORDER-77")
    _collection(fake_client, merchant_id, phone="255700111222", reference="ORDER-88")

    response = client.get("/v1/merchant/collections?search=ORDER-77", headers=headers)

    assert response.status_code == 200
    assert _ids(response) == {collection["id"]}


@pytest.mark.parametrize("term", [STORED, AS_LOCAL, AS_SPACED, AS_TAIL])
def test_a_merchant_finds_the_transaction_by_phone(fake_client, term):
    """Transactions carry no phone of their own.

    The number lives on the collection, so this only works by resolving
    the collections that number paid for and then restricting to their
    transactions.
    """
    merchant_id = _merchant(fake_client)
    headers = _merchant_headers(fake_client, merchant_id)
    collection = _collection(fake_client, merchant_id, phone=STORED)
    transaction = _transaction(fake_client, merchant_id, collection_id=collection["id"])
    other = _collection(fake_client, merchant_id, phone="255700111222")
    _transaction(fake_client, merchant_id, collection_id=other["id"])

    response = client.get(f"/v1/merchant/transactions?search={term}", headers=headers)

    assert response.status_code == 200
    assert _ids(response) == {transaction["id"]}


def test_a_merchant_searching_an_unknown_number_sees_no_transactions(fake_client):
    """The mutation that matters.

    If the empty id list were skipped instead of applied, this returns
    the merchant's whole transaction history and the operator reads the
    top row as the customer's payment.
    """
    merchant_id = _merchant(fake_client)
    headers = _merchant_headers(fake_client, merchant_id)
    collection = _collection(fake_client, merchant_id, phone=STORED)
    _transaction(fake_client, merchant_id, collection_id=collection["id"])

    response = client.get(f"/v1/merchant/transactions?search={ABSENT}", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"] == []


# --- Super Admin -------------------------------------------------------------


@pytest.mark.parametrize("term", [STORED, AS_LOCAL, AS_SPACED, AS_TAIL])
def test_super_admin_finds_the_collection_by_phone(fake_client, term):
    headers = _admin_headers(fake_client)
    merchant_id = _merchant(fake_client)
    collection = _collection(fake_client, merchant_id, phone=STORED)
    _collection(fake_client, merchant_id, phone="255700111222")

    response = client.get(f"/v1/admin/collections?customer_phone={term}", headers=headers)

    assert response.status_code == 200
    assert _ids(response, "collection_id") == {collection["id"]}


def test_super_admin_searching_an_unknown_number_sees_no_collections(fake_client):
    headers = _admin_headers(fake_client)
    merchant_id = _merchant(fake_client)
    _collection(fake_client, merchant_id, phone=STORED)

    response = client.get(f"/v1/admin/collections?customer_phone={ABSENT}", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_super_admin_sees_across_merchants(fake_client):
    # The point of the Super Admin view: the number is searched platform
    # wide, because the operator does not know which merchant was paid.
    headers = _admin_headers(fake_client)
    first = _merchant(fake_client)
    second = _merchant(fake_client)
    a = _collection(fake_client, first, phone=STORED)
    b = _collection(fake_client, second, phone=STORED)

    response = client.get(f"/v1/admin/collections?customer_phone={STORED}", headers=headers)

    assert response.status_code == 200
    assert _ids(response, "collection_id") == {a["id"], b["id"]}


@pytest.mark.parametrize("term", [STORED, AS_LOCAL, AS_SPACED, AS_TAIL])
def test_super_admin_finds_the_transaction_by_phone(fake_client, term):
    headers = _admin_headers(fake_client)
    merchant_id = _merchant(fake_client)
    collection = _collection(fake_client, merchant_id, phone=STORED)
    transaction = _transaction(fake_client, merchant_id, collection_id=collection["id"])
    other = _collection(fake_client, merchant_id, phone="255700111222")
    _transaction(fake_client, merchant_id, collection_id=other["id"])

    response = client.get(f"/v1/admin/transactions?customer_phone={term}", headers=headers)

    assert response.status_code == 200
    assert _ids(response, "transaction_id") == {transaction["id"]}


def test_super_admin_searching_an_unknown_number_sees_no_transactions(fake_client):
    headers = _admin_headers(fake_client)
    merchant_id = _merchant(fake_client)
    collection = _collection(fake_client, merchant_id, phone=STORED)
    _transaction(fake_client, merchant_id, collection_id=collection["id"])

    response = client.get(f"/v1/admin/transactions?customer_phone={ABSENT}", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_super_admin_term_below_the_floor_matches_nothing(fake_client):
    """Too short to mean anything, so it must not quietly drop the filter.

    Dropping it would answer a 4-digit search with every transaction on
    the platform.
    """
    headers = _admin_headers(fake_client)
    merchant_id = _merchant(fake_client)
    collection = _collection(fake_client, merchant_id, phone=STORED)
    _transaction(fake_client, merchant_id, collection_id=collection["id"])

    for path in ("collections", "transactions"):
        response = client.get(f"/v1/admin/{path}?customer_phone=4101", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"] == [], f"/v1/admin/{path} dropped a too-short filter"


# --- the tail is anchored on the SCREENS, not just in the helper -------------
#
# These exist because mutation-testing found the gap: making the tail a
# substring instead of a suffix broke nothing, since the only anchoring
# test called the helper directly and never went through an endpoint.
# A decoy whose number merely CONTAINS the tail is what catches it.

TAIL = "878545"
ENDS_WITH_TAIL = "255762878545"
CONTAINS_TAIL = "255878545123"


def test_a_merchant_searching_a_tail_does_not_match_it_mid_number(fake_client):
    merchant_id = _merchant(fake_client)
    headers = _merchant_headers(fake_client, merchant_id)
    wanted = _collection(fake_client, merchant_id, phone=ENDS_WITH_TAIL)
    _collection(fake_client, merchant_id, phone=CONTAINS_TAIL)

    response = client.get(f"/v1/merchant/collections?search={TAIL}", headers=headers)

    assert response.status_code == 200
    assert _ids(response) == {wanted["id"]}


def test_super_admin_searching_a_tail_does_not_match_it_mid_number(fake_client):
    headers = _admin_headers(fake_client)
    merchant_id = _merchant(fake_client)
    wanted = _collection(fake_client, merchant_id, phone=ENDS_WITH_TAIL)
    _collection(fake_client, merchant_id, phone=CONTAINS_TAIL)

    response = client.get(f"/v1/admin/collections?customer_phone={TAIL}", headers=headers)

    assert response.status_code == 200
    assert _ids(response, "collection_id") == {wanted["id"]}


def test_a_tail_means_the_same_thing_on_both_screens(fake_client):
    """The point of anchoring both sides the same way.

    An operator and a merchant looking at the same number must not see
    different answers, or one of them is wrong and neither knows which.
    """
    headers_admin = _admin_headers(fake_client)
    merchant_id = _merchant(fake_client)
    headers_merchant = _merchant_headers(fake_client, merchant_id)
    _collection(fake_client, merchant_id, phone=ENDS_WITH_TAIL)
    _collection(fake_client, merchant_id, phone=CONTAINS_TAIL)

    mine = client.get(f"/v1/merchant/collections?search={TAIL}", headers=headers_merchant)
    theirs = client.get(f"/v1/admin/collections?customer_phone={TAIL}", headers=headers_admin)

    assert _ids(mine) == _ids(theirs, "collection_id")


def test_super_admin_searching_a_tail_on_transactions_is_anchored(fake_client):
    headers = _admin_headers(fake_client)
    merchant_id = _merchant(fake_client)
    wanted_collection = _collection(fake_client, merchant_id, phone=ENDS_WITH_TAIL)
    wanted = _transaction(fake_client, merchant_id, collection_id=wanted_collection["id"])
    decoy = _collection(fake_client, merchant_id, phone=CONTAINS_TAIL)
    _transaction(fake_client, merchant_id, collection_id=decoy["id"])

    response = client.get(f"/v1/admin/transactions?customer_phone={TAIL}", headers=headers)

    assert response.status_code == 200
    assert _ids(response, "transaction_id") == {wanted["id"]}


def test_a_merchant_searching_a_tail_on_transactions_is_anchored(fake_client):
    merchant_id = _merchant(fake_client)
    headers = _merchant_headers(fake_client, merchant_id)
    wanted_collection = _collection(fake_client, merchant_id, phone=ENDS_WITH_TAIL)
    wanted = _transaction(fake_client, merchant_id, collection_id=wanted_collection["id"])
    decoy = _collection(fake_client, merchant_id, phone=CONTAINS_TAIL)
    _transaction(fake_client, merchant_id, collection_id=decoy["id"])

    response = client.get(f"/v1/merchant/transactions?search={TAIL}", headers=headers)

    assert response.status_code == 200
    assert _ids(response) == {wanted["id"]}
