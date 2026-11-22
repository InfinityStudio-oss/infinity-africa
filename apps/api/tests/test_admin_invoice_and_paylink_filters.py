"""The Super Admin Invoices and Pay by Link filters.

Both screens had a search box and a status dropdown, and the Invoices
one also had an unlabelled date input. None of them had a handler: the
controls moved nothing. That is worse than having no filters, because
the list underneath looked like a result.

The interesting part is that "business" is not a column on either
table. The business name lives on merchants, so a search for one has to
resolve through there - and the whole search travels as a single
comma-separated PostgREST or_() expression, which a term containing a
comma would quietly rewrite.

Pinned here:

1. Each promised column is actually searched - including the business
   name and code, which are not on these tables.
2. A term that matches nothing returns nothing; an EMPTY term is not a
   filter for nothing.
3. Punctuation in a term is searched for, not executed as query syntax.
4. "All statuses" is not the same as a status, and for Pay by Link "All"
   is not is_active=false - that would hide every working page.
5. Invoice due dates are Tanzanian days, inclusive.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from tests.factories import (
    TEST_JWT_SECRET,
    auth_headers,
    create_merchant,
    make_super_admin,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", TEST_JWT_SECRET)
    monkeypatch.setenv("REQUIRE_SUPER_ADMIN_MFA", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _headers(fake_client):
    user_id = uuid.uuid4()
    make_super_admin(fake_client, user_id)
    return auth_headers(user_id, aal="aal2")


def _invoice(fake_client, merchant_id, *, number, status="SENT", due_date="2026-11-30", **extra):
    row = {
        "id": str(uuid.uuid4()),
        "merchant_id": str(merchant_id),
        "invoice_number": number,
        "total_amount": "5000",
        "status": status,
        "due_date": due_date,
        "created_at": "2026-11-01T09:00:00+00:00",
        **extra,
    }
    return fake_client.seed("invoices", row)


def _pay_link(fake_client, merchant_id, *, slug, display_name="A Shop", is_active=True):
    return fake_client.seed(
        "merchant_pay_links",
        {
            "id": str(uuid.uuid4()),
            "merchant_id": str(merchant_id),
            "slug": slug,
            "display_name": display_name,
            "is_active": is_active,
            "created_at": "2026-11-01T09:00:00+00:00",
        },
    )


def _numbers(response):
    return {row["invoice_number"] for row in response.json()["data"]}


def _slugs(response):
    return {row["slug"] for row in response.json()["data"]}


# --- invoices: the search box -------------------------------------------------


def test_an_invoice_is_found_by_its_number(fake_client):
    headers = _headers(fake_client)
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    _invoice(fake_client, merchant_id, number="INV-2026-0042")
    _invoice(fake_client, merchant_id, number="INV-2026-0099")

    response = client.get("/v1/admin/invoices?search=0042", headers=headers)

    assert response.status_code == 200
    assert _numbers(response) == {"INV-2026-0042"}


def test_an_invoice_is_found_by_its_customer(fake_client):
    headers = _headers(fake_client)
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    _invoice(fake_client, merchant_id, number="INV-1", customer_name="Grace Mwakalinga")
    _invoice(fake_client, merchant_id, number="INV-2", customer_name="Juma Traders")

    assert _numbers(client.get("/v1/admin/invoices?search=Mwakalinga", headers=headers)) == {"INV-1"}


def test_an_invoice_is_found_by_the_customers_phone(fake_client):
    headers = _headers(fake_client)
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    _invoice(fake_client, merchant_id, number="INV-1", customer_phone="255762474101")
    _invoice(fake_client, merchant_id, number="INV-2", customer_phone="255700111222")

    assert _numbers(client.get("/v1/admin/invoices?search=474101", headers=headers)) == {"INV-1"}


def test_an_invoice_is_found_by_the_business_name(fake_client):
    """The one that needs a second table.

    business_name is on merchants, not on invoices, so a search for it
    has to resolve merchant ids first. The search box promised this and
    was wired to nothing at all.
    """
    headers = _headers(fake_client)
    wanted = uuid.UUID(create_merchant(fake_client, business_name="Kilimanjaro Cafe")["id"])
    other = uuid.UUID(create_merchant(fake_client, business_name="Dar Hardware")["id"])
    _invoice(fake_client, wanted, number="INV-CAFE")
    _invoice(fake_client, other, number="INV-HARDWARE")

    response = client.get("/v1/admin/invoices?search=Kilimanjaro", headers=headers)

    assert response.status_code == 200
    assert _numbers(response) == {"INV-CAFE"}


def test_an_invoice_is_found_by_the_merchant_code(fake_client):
    # The operator holding a code off a receipt and the one who knows
    # the trading name are the same person on a different day.
    headers = _headers(fake_client)
    merchant = create_merchant(fake_client, business_name="Kilimanjaro Cafe")
    _invoice(fake_client, uuid.UUID(merchant["id"]), number="INV-CAFE")
    other = uuid.UUID(create_merchant(fake_client, business_name="Dar Hardware")["id"])
    _invoice(fake_client, other, number="INV-HARDWARE")

    response = client.get(
        f"/v1/admin/invoices?search={merchant['merchant_code']}", headers=headers
    )

    assert _numbers(response) == {"INV-CAFE"}


def test_a_search_matching_nothing_returns_nothing(fake_client):
    headers = _headers(fake_client)
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    _invoice(fake_client, merchant_id, number="INV-1")

    response = client.get("/v1/admin/invoices?search=ZZZ-NOT-A-THING", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"] == []


def test_an_empty_search_is_not_a_filter(fake_client):
    # An empty box must not filter for nothing. Both the bare parameter
    # and a whitespace-only one.
    headers = _headers(fake_client)
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    _invoice(fake_client, merchant_id, number="INV-1")
    _invoice(fake_client, merchant_id, number="INV-2")

    for query in ("?search=", "?search=%20%20", ""):
        response = client.get(f"/v1/admin/invoices{query}", headers=headers)
        assert _numbers(response) == {"INV-1", "INV-2"}, f"{query!r} dropped rows"


def test_a_comma_in_the_search_term_is_searched_for_not_executed(fake_client):
    """The subtle one.

    The whole search travels as one comma-separated or_() expression, so
    an unsanitised comma does not search for a comma - it adds a branch
    and changes which rows come back, with nothing to say so.
    """
    headers = _headers(fake_client)
    wanted = uuid.UUID(create_merchant(fake_client, business_name="Kilimanjaro Cafe Ltd")["id"])
    other = uuid.UUID(create_merchant(fake_client, business_name="Dar Hardware")["id"])
    _invoice(fake_client, wanted, number="INV-CAFE")
    _invoice(fake_client, other, number="INV-HARDWARE")

    response = client.get("/v1/admin/invoices?search=Kilimanjaro, Cafe", headers=headers)

    assert response.status_code == 200
    # Not a 500, and not everything. The comma became a space, so this
    # is still a search for that business.
    assert _numbers(response) == {"INV-CAFE"}


def test_brackets_in_the_search_term_do_not_break_the_query(fake_client):
    headers = _headers(fake_client)
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    _invoice(fake_client, merchant_id, number="INV-1")

    response = client.get("/v1/admin/invoices?search=%28oops%29", headers=headers)

    assert response.status_code == 200


# --- invoices: status and due date --------------------------------------------


def test_filtering_invoices_by_status(fake_client):
    headers = _headers(fake_client)
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    _invoice(fake_client, merchant_id, number="INV-PAID", status="PAID")
    _invoice(fake_client, merchant_id, number="INV-OVERDUE", status="OVERDUE")

    assert _numbers(client.get("/v1/admin/invoices?status=OVERDUE", headers=headers)) == {
        "INV-OVERDUE"
    }


def test_an_unknown_invoice_status_is_rejected(fake_client):
    headers = _headers(fake_client)

    response = client.get("/v1/admin/invoices?status=ALMOST_PAID", headers=headers)

    # 422, not an empty list: "nothing matched" and "that is not a
    # status" are different answers.
    assert response.status_code == 422


def test_due_before_is_inclusive_of_the_named_day(fake_client):
    """"Due on or before the 30th" includes the 30th.

    No timezone care is needed here, unlike every created_at filter on
    this router: invoices.due_date is a DATE, so there is no time of day
    to be three hours out by. Worth stating because the first version of
    this filter anchored it to Dar es Salaam anyway, which was reasoning
    applied to the wrong column type.
    """
    headers = _headers(fake_client)
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    _invoice(fake_client, merchant_id, number="DUE-ON-THE-30TH", due_date="2026-11-30")
    _invoice(fake_client, merchant_id, number="DUE-ON-THE-29TH", due_date="2026-11-29")
    _invoice(fake_client, merchant_id, number="DUE-IN-DECEMBER", due_date="2026-12-05")

    response = client.get("/v1/admin/invoices?due_before=2026-11-30", headers=headers)

    assert response.status_code == 200
    assert _numbers(response) == {"DUE-ON-THE-30TH", "DUE-ON-THE-29TH"}


def test_an_unparseable_due_date_names_the_field(fake_client):
    headers = _headers(fake_client)

    response = client.get("/v1/admin/invoices?due_before=whenever", headers=headers)

    assert response.status_code == 422
    assert "due_before" in response.text


def test_the_invoice_filters_combine(fake_client):
    headers = _headers(fake_client)
    merchant_id = uuid.UUID(create_merchant(fake_client, business_name="Kilimanjaro Cafe")["id"])
    _invoice(
        fake_client, merchant_id, number="WANTED", status="OVERDUE", due_date="2026-11-30"
    )
    _invoice(
        fake_client, merchant_id, number="WRONG-STATUS", status="PAID", due_date="2026-11-30"
    )
    _invoice(
        fake_client, merchant_id, number="WRONG-DATE", status="OVERDUE", due_date="2026-12-20"
    )

    response = client.get(
        "/v1/admin/invoices?search=Kilimanjaro&status=OVERDUE&due_before=2026-11-30", headers=headers
    )

    assert _numbers(response) == {"WANTED"}


# --- pay by link --------------------------------------------------------------


def test_a_pay_link_is_found_by_its_slug(fake_client):
    headers = _headers(fake_client)
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    _pay_link(fake_client, merchant_id, slug="benny-wifi")
    _pay_link(fake_client, merchant_id, slug="dar-hardware")

    assert _slugs(client.get("/v1/admin/pay-by-link?search=benny", headers=headers)) == {
        "benny-wifi"
    }


def test_a_pay_link_is_found_by_its_display_name(fake_client):
    headers = _headers(fake_client)
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    _pay_link(fake_client, merchant_id, slug="a", display_name="Benny WiFi Hotspot")
    _pay_link(fake_client, merchant_id, slug="b", display_name="Dar Hardware")

    assert _slugs(client.get("/v1/admin/pay-by-link?search=Hotspot", headers=headers)) == {"a"}


def test_a_pay_link_is_found_by_the_business_name(fake_client):
    headers = _headers(fake_client)
    wanted = uuid.UUID(create_merchant(fake_client, business_name="Kilimanjaro Cafe")["id"])
    other = uuid.UUID(create_merchant(fake_client, business_name="Dar Hardware")["id"])
    _pay_link(fake_client, wanted, slug="cafe-page", display_name="Order Here")
    _pay_link(fake_client, other, slug="hardware-page", display_name="Order Here")

    response = client.get("/v1/admin/pay-by-link?search=Kilimanjaro", headers=headers)

    assert response.status_code == 200
    assert _slugs(response) == {"cafe-page"}


def test_all_statuses_is_not_the_same_as_disabled(fake_client):
    """The mistake this would be easy to make.

    "All" must send no is_active at all. Sending false would hide every
    working Pay by Link page on the platform and look like a feature
    that had stopped working.
    """
    headers = _headers(fake_client)
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    _pay_link(fake_client, merchant_id, slug="live-one", is_active=True)
    _pay_link(fake_client, merchant_id, slug="dead-one", is_active=False)

    assert _slugs(client.get("/v1/admin/pay-by-link", headers=headers)) == {"live-one", "dead-one"}
    assert _slugs(client.get("/v1/admin/pay-by-link?is_active=true", headers=headers)) == {
        "live-one"
    }
    assert _slugs(client.get("/v1/admin/pay-by-link?is_active=false", headers=headers)) == {
        "dead-one"
    }


def test_the_pay_link_filters_combine(fake_client):
    headers = _headers(fake_client)
    merchant_id = uuid.UUID(create_merchant(fake_client, business_name="Kilimanjaro Cafe")["id"])
    _pay_link(fake_client, merchant_id, slug="wanted", is_active=True)
    _pay_link(fake_client, merchant_id, slug="wanted-but-off", is_active=False)

    response = client.get(
        "/v1/admin/pay-by-link?search=Kilimanjaro&is_active=true", headers=headers
    )

    assert _slugs(response) == {"wanted"}


def test_an_empty_pay_link_search_is_not_a_filter(fake_client):
    headers = _headers(fake_client)
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    _pay_link(fake_client, merchant_id, slug="a")
    _pay_link(fake_client, merchant_id, slug="b")

    assert _slugs(client.get("/v1/admin/pay-by-link?search=", headers=headers)) == {"a", "b"}


def test_a_search_cannot_be_reached_without_super_admin(fake_client):
    # The filters are new surface on an admin-only screen; they must not
    # have opened it up.
    merchant_id = uuid.UUID(create_merchant(fake_client)["id"])
    _pay_link(fake_client, merchant_id, slug="a")

    assert client.get("/v1/admin/pay-by-link?search=a").status_code in (401, 403)
    assert client.get("/v1/admin/invoices?search=a").status_code in (401, 403)
