"""Onboarding document upload.

The allowlist was already here, but it trusted `content_type` — a header
the client sets and can simply lie about — and the stored extension came
from the uploaded filename. There was also no size ceiling on a read that
pulls the whole file into memory.
"""

import io
import uuid

import pytest
from fastapi import UploadFile

from app.core.errors import ValidationAPIError
from app.schemas.enums import DocumentType
from app.services.onboarding import _MAX_DOCUMENT_BYTES, register_onboarding_document

PDF = b"%PDF-1.4\n" + b"x" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 200
JPEG = b"\xff\xd8\xff\xe0" + b"x" * 200


def _upload(content: bytes, *, filename: str, content_type: str) -> UploadFile:
    return UploadFile(file=io.BytesIO(content), filename=filename, headers={"content-type": content_type})


async def _register(fake_client, upload: UploadFile):
    return await register_onboarding_document(
        fake_client,
        merchant_id=uuid.uuid4(),
        document_type=DocumentType.TIN_CERTIFICATE,
        file=upload,
        uploaded_by=uuid.uuid4(),
    )


# --- the declared type must match the actual bytes ------------------------


@pytest.mark.asyncio
async def test_an_executable_claiming_to_be_a_png_is_refused(fake_client):
    """content_type is chosen by the uploader. The file's own first bytes
    are not, so they are what decide."""
    upload = _upload(b"MZ\x90\x00executable", filename="id.png", content_type="image/png")

    with pytest.raises(ValidationAPIError) as exc:
        await _register(fake_client, upload)

    assert "does not look like" in str(exc.value)


@pytest.mark.asyncio
async def test_html_claiming_to_be_a_pdf_is_refused(fake_client):
    upload = _upload(b"<html><script>alert(1)</script>", filename="x.pdf", content_type="application/pdf")

    with pytest.raises(ValidationAPIError):
        await _register(fake_client, upload)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content,content_type", [(PDF, "application/pdf"), (PNG, "image/png"), (JPEG, "image/jpeg")]
)
async def test_a_genuine_file_of_each_allowed_type_is_accepted(content, content_type, fake_client):
    row = await _register(fake_client, _upload(content, filename="doc", content_type=content_type))

    assert row["upload_status"] == "UPLOADED"


@pytest.mark.asyncio
async def test_a_disallowed_type_is_refused_before_anything_is_read(fake_client):
    upload = _upload(b"MZ\x90\x00", filename="x.exe", content_type="application/x-msdownload")

    with pytest.raises(ValidationAPIError) as exc:
        await _register(fake_client, upload)

    assert "PDF, JPG, or PNG" in str(exc.value)


# --- size ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_oversized_upload_is_refused(fake_client):
    """The read pulls the file into memory, so without a ceiling one
    request can exhaust the container for every merchant."""
    oversized = b"%PDF-1.4\n" + b"x" * (_MAX_DOCUMENT_BYTES + 1000)
    upload = _upload(oversized, filename="big.pdf", content_type="application/pdf")

    with pytest.raises(ValidationAPIError) as exc:
        await _register(fake_client, upload)

    assert "smaller than" in str(exc.value)


@pytest.mark.asyncio
async def test_an_empty_upload_is_refused(fake_client):
    with pytest.raises(ValidationAPIError) as exc:
        await _register(fake_client, _upload(b"", filename="x.pdf", content_type="application/pdf"))

    assert "empty" in str(exc.value)


# --- the stored path is ours, not theirs ----------------------------------


@pytest.mark.asyncio
async def test_the_stored_extension_comes_from_the_verified_type(fake_client):
    """A file called "id.pdf.exe" must not be stored as .exe. The extension
    is derived from the type we verified, never from the filename."""
    row = await _register(
        fake_client, _upload(PDF, filename="id.pdf.exe", content_type="application/pdf")
    )

    assert row["file_path"].endswith(".pdf")
    assert ".exe" not in row["file_path"]


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["../../etc/passwd", "..\\..\\win.ini", "a/b/c.png", "....//x.png"])
async def test_a_traversal_filename_cannot_shape_the_storage_path(filename, fake_client):
    merchant_id = uuid.uuid4()

    row = await register_onboarding_document(
        fake_client,
        merchant_id=merchant_id,
        document_type=DocumentType.TIN_CERTIFICATE,
        file=_upload(PNG, filename=filename, content_type="image/png"),
        uploaded_by=uuid.uuid4(),
    )

    assert row["file_path"] == f"{merchant_id}/{DocumentType.TIN_CERTIFICATE.value}.png"
    assert ".." not in row["file_path"]


@pytest.mark.asyncio
async def test_the_original_filename_is_still_recorded_for_support(fake_client):
    """Kept as data for whoever reviews the document — it just has no say
    in where the file lands."""
    row = await _register(fake_client, _upload(PDF, filename="my scan.pdf", content_type="application/pdf"))

    assert row["original_filename"] == "my scan.pdf"
