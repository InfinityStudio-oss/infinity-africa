import sys

import pytest

from app.core.rate_limit import _limiter as rate_limiter
from app.database import session as session_module
from tests import fakes as fakes_module
from tests.fakes import FakeSupabaseClient


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """app/core/rate_limit.py's limiter is a module-level singleton shared
    across the whole test process (same as it would be across requests to
    one real running app) — without resetting it, any test file whose
    tests collectively call a rate-limited endpoint (e.g. POST
    /v1/disbursements/mobile-money, limited to 10/min/IP) more than its
    limit across the *whole session* starts getting real 429s later in
    the run, nothing to do with that specific test. TestClient requests
    have no real client IP, so every test in the whole suite shares one
    "unknown" bucket per scope unless this resets between tests."""
    rate_limiter._hits.clear()
    yield
    rate_limiter._hits.clear()


@pytest.fixture
def fake_client(monkeypatch) -> FakeSupabaseClient:
    """A fresh in-memory Supabase client, patched into every already-imported
    module that did `from app.database.session import get_supabase_admin` —
    which is all of app/auth, app/routers, app/services. Sweeping every
    module means new routers/services need no test-side changes to pick it
    up automatically.
    """
    # The fake's created_at is monotonic (see fakes._monotonic_now), and
    # its high-water mark is module state. Left alone it carries across
    # the whole session, so a later test's rows can be stamped ahead of
    # the real clock and anything comparing them against datetime.now()
    # sees rows in the future. Per-test reset keeps the monotonicity
    # where it is needed - within one test - without coupling tests.
    fakes_module._LAST_NOW.clear()

    client = FakeSupabaseClient()
    original = session_module.get_supabase_admin

    for module in list(sys.modules.values()):
        if module is not None and getattr(module, "get_supabase_admin", None) is original:
            monkeypatch.setattr(module, "get_supabase_admin", lambda: client)

    return client
