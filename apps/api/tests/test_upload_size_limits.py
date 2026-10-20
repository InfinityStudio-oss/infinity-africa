"""Every upload path must be bounded.

Onboarding did this correctly from the start: a bounded read, a size
ceiling, and a magic-byte check against the declared content type. The two
other paths that write to Storage did not.

The one that matters is the public dispute form. `/v1/public/disputes/report`
takes no authentication - a customer reporting a problem has no account -
accepts any number of attachments, and read each one with an unbounded
`await file.read()`. The dispute-evidence bucket carries no
file_size_limit of its own either (confirmed live on 2026-10-20: all three
buckets are private, none has a size or MIME limit set), so nothing
anywhere bounded it. Five requests a minute with no login was enough to
exhaust the container's memory or run up storage cost.

`content_type` is also only a client-set header here, so the MIME
allowlist decides what we *label* the object, not what it contains. That
is a separate gap from size and is noted rather than fixed in these tests.

Nothing here uploads anything: the Storage call is stubbed, because the
assertion is about the request being refused before it gets that far.
"""

import uuid

import pytest
from fastapi import UploadFile
from starlette.datastructures import Headers

from app.core.errors import ValidationAPIError
from app.services import disputes_service, document_requests_service


def _upload(content: bytes, *, name: str = "evidence.pdf", mime: str = "application/pdf"):
    import io

    return UploadFile(
        filename=name,
        file=io.BytesIO(content),
        headers=Headers({"content-type": mime}),
    )


class _Storage:
    """Records uploads so a test can prove none happened."""

    def __init__(self):
        self.uploads: list[str] = []

    def from_(self, _bucket):
        return self

    def upload(self, path, _content, _options):
        self.uploads.append(path)


class _Client:
    def __init__(self):
        self.storage = _Storage()


UNDER = b"%PDF-1.4" + b"x" * 1024
OVER = b"%PDF-1.4" + b"x" * (10 * 1024 * 1024 + 1)


# --- the public dispute form -------------------------------------------


@pytest.mark.asyncio
async def test_an_oversized_evidence_file_is_refused(anyio_backend=None):
    client = _Client()

    with pytest.raises(ValidationAPIError) as excinfo:
        await disputes_service._upload_evidence(
            client, dispute_id=uuid.uuid4(), files=[_upload(OVER)]
        )

    assert "smaller than" in str(excinfo.value).lower()
    assert client.storage.uploads == [], "an oversized file reached Storage"


@pytest.mark.asyncio
async def test_a_normal_evidence_file_is_still_accepted():
    """The bound must not break the thing it protects: a real customer
    attaching a receipt has to keep working."""
    client = _Client()

    uploaded = await disputes_service._upload_evidence(
        client, dispute_id=uuid.uuid4(), files=[_upload(UNDER)]
    )

    assert len(uploaded) == 1
    assert len(client.storage.uploads) == 1


@pytest.mark.asyncio
async def test_a_file_exactly_at_the_limit_is_accepted():
    """Off-by-one check: the bounded read asks for limit+1 bytes, so a file
    of exactly the limit must not be mistaken for an oversized one."""
    client = _Client()
    exact = b"%PDF-1.4" + b"x" * (10 * 1024 * 1024 - len(b"%PDF-1.4"))
    assert len(exact) == 10 * 1024 * 1024

    uploaded = await disputes_service._upload_evidence(
        client, dispute_id=uuid.uuid4(), files=[_upload(exact)]
    )

    assert len(uploaded) == 1


@pytest.mark.asyncio
async def test_too_many_evidence_files_are_refused():
    """A per-file ceiling alone is not a bound on the request: twenty files
    just under the limit is still two hundred megabytes."""
    client = _Client()
    files = [_upload(UNDER, name=f"e{i}.pdf") for i in range(6)]

    with pytest.raises(ValidationAPIError):
        await disputes_service._upload_evidence(client, dispute_id=uuid.uuid4(), files=files)

    assert client.storage.uploads == []


@pytest.mark.asyncio
async def test_the_file_count_limit_allows_the_documented_maximum():
    client = _Client()
    files = [_upload(UNDER, name=f"e{i}.pdf") for i in range(5)]

    uploaded = await disputes_service._upload_evidence(
        client, dispute_id=uuid.uuid4(), files=files
    )

    assert len(uploaded) == 5


@pytest.mark.asyncio
async def test_a_disallowed_mime_type_is_still_refused():
    """Pre-existing behaviour, asserted so the size work above cannot have
    quietly displaced it."""
    client = _Client()

    with pytest.raises(ValidationAPIError):
        await disputes_service._upload_evidence(
            client,
            dispute_id=uuid.uuid4(),
            files=[_upload(UNDER, name="x.exe", mime="application/x-msdownload")],
        )


@pytest.mark.asyncio
async def test_one_oversized_file_refuses_the_whole_submission():
    """Partial acceptance would leave a dispute with some evidence attached
    and an error returned, which is worse than refusing cleanly."""
    client = _Client()

    with pytest.raises(ValidationAPIError):
        await disputes_service._upload_evidence(
            client,
            dispute_id=uuid.uuid4(),
            files=[_upload(UNDER, name="ok.pdf"), _upload(OVER, name="huge.pdf")],
        )


# --- merchant document requests ----------------------------------------


@pytest.mark.asyncio
async def test_an_oversized_requested_document_is_refused():
    client = _Client()

    with pytest.raises(ValidationAPIError) as excinfo:
        await document_requests_service.register_document_request_file(
            client,
            request_id=uuid.uuid4(),
            merchant_id=uuid.uuid4(),
            document_label="Bank statement",
            file=_upload(OVER),
            uploaded_by=uuid.uuid4(),
        )

    assert "smaller than" in str(excinfo.value).lower()
    assert client.storage.uploads == []


def test_both_paths_share_the_onboarding_ceiling():
    """A merchant should not meet one limit during onboarding and a
    different one when asked for the same document later."""
    from app.services.onboarding import _MAX_DOCUMENT_BYTES as onboarding_limit

    assert document_requests_service._MAX_DOCUMENT_BYTES == onboarding_limit
    assert disputes_service._MAX_EVIDENCE_BYTES == onboarding_limit
