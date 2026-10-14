"""Tests for core.validators — file upload validation."""

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from core.validators import (
    AVATAR_MAX_SIZE,
    DOCUMENT_MAX_SIZE,
    IMAGE_MAX_SIZE,
    assert_content_matches_extension,
    content_matches_extension,
    validate_avatar_upload,
    validate_document_upload,
    validate_image_upload,
)


class TestValidateImageUpload:
    """Tests for validate_image_upload."""

    def test_valid_jpeg(self):
        f = SimpleUploadedFile("test.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 100, content_type="image/jpeg")
        # Should not raise
        validate_image_upload(f)

    def test_valid_png(self):
        f = SimpleUploadedFile("test.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, content_type="image/png")
        validate_image_upload(f)

    def test_svg_rejected(self):
        # SVG removed for stored-XSS safety (audit H6) — must now be refused.
        f = SimpleUploadedFile("icon.svg", b"<svg></svg>", content_type="image/svg+xml")
        with pytest.raises(ValidationError):
            validate_image_upload(f)

    def test_invalid_extension(self):
        f = SimpleUploadedFile("test.exe", b"\x00" * 100, content_type="application/octet-stream")
        with pytest.raises(ValidationError, match="extension"):
            validate_image_upload(f)

    def test_invalid_content_type(self):
        f = SimpleUploadedFile("test.jpg", b"\x00" * 100, content_type="application/pdf")
        with pytest.raises(ValidationError, match="content type"):
            validate_image_upload(f)

    def test_exceeds_size_limit(self):
        f = SimpleUploadedFile("big.jpg", b"\x00" * (IMAGE_MAX_SIZE + 1), content_type="image/jpeg")
        with pytest.raises(ValidationError, match="file size"):
            validate_image_upload(f)

    def test_at_size_limit(self):
        f = SimpleUploadedFile("ok.jpg", b"\xff\xd8\xff" + b"\x00" * (IMAGE_MAX_SIZE - 3), content_type="image/jpeg")
        # Should not raise
        validate_image_upload(f)

    def test_rejects_content_type_spoof(self):
        # .png extension + allowed content_type but body is not a PNG → magic-byte check fires.
        f = SimpleUploadedFile("fake.png", b"GIF89a" + b"\x00" * 100, content_type="image/png")
        with pytest.raises(ValidationError, match="does not match"):
            validate_image_upload(f)

    def test_valid_webp(self):
        # Real WebP: RIFF + 4-byte size + "WEBP" form-type at bytes 8-11.
        body = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 64
        validate_image_upload(SimpleUploadedFile("pic.webp", body, content_type="image/webp"))

    def test_rejects_riff_non_webp_spoof(self):
        # SEC-08 adversarial finding: a RIFF container that is NOT WebP (WAV/AVI share "RIFF")
        # renamed .webp must be REJECTED — checking "RIFF" alone was the bypass.
        wav = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE" + b"\x00" * 64
        with pytest.raises(ValidationError, match="does not match"):
            validate_image_upload(SimpleUploadedFile("audio.webp", wav, content_type="image/webp"))


class TestValidateAvatarUpload:
    """Tests for validate_avatar_upload (2MB limit)."""

    def test_valid_small_avatar(self):
        f = SimpleUploadedFile("avatar.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, content_type="image/png")
        validate_avatar_upload(f)

    def test_exceeds_avatar_limit(self):
        f = SimpleUploadedFile("big.png", b"\x00" * (AVATAR_MAX_SIZE + 1), content_type="image/png")
        with pytest.raises(ValidationError, match="file size"):
            validate_avatar_upload(f)

    def test_invalid_extension(self):
        f = SimpleUploadedFile("avatar.pdf", b"\x00" * 100, content_type="application/pdf")
        with pytest.raises(ValidationError, match="extension"):
            validate_avatar_upload(f)


class TestValidateDocumentUpload:
    """Tests for validate_document_upload (20MB limit, accepts images + docs)."""

    def test_valid_pdf(self):
        f = SimpleUploadedFile("doc.pdf", b"%PDF-1.4" + b"\x00" * 100, content_type="application/pdf")
        validate_document_upload(f)

    def test_valid_xlsx(self):
        f = SimpleUploadedFile(
            "data.xlsx",
            b"PK\x03\x04" + b"\x00" * 100,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        validate_document_upload(f)

    def test_rejects_xlsx_spoof(self):
        # .xlsx but body is not a ZIP/OOXML container → rejected.
        f = SimpleUploadedFile(
            "fake.xlsx",
            b"not-a-zip" + b"\x00" * 100,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        with pytest.raises(ValidationError, match="does not match"):
            validate_document_upload(f)

    def test_rejects_pdf_spoof(self):
        f = SimpleUploadedFile("fake.pdf", b"MZ\x90\x00" + b"\x00" * 100, content_type="application/pdf")
        with pytest.raises(ValidationError, match="does not match"):
            validate_document_upload(f)

    def test_valid_csv(self):
        f = SimpleUploadedFile("data.csv", b"a,b,c\n1,2,3", content_type="text/csv")
        validate_document_upload(f)

    def test_valid_image_in_document(self):
        f = SimpleUploadedFile("photo.jpg", b"\xff\xd8\xff\xe0" + b"\x00" * 100, content_type="image/jpeg")
        validate_document_upload(f)

    def test_invalid_extension(self):
        f = SimpleUploadedFile("virus.exe", b"\x00" * 100, content_type="application/octet-stream")
        with pytest.raises(ValidationError, match="extension"):
            validate_document_upload(f)

    def test_exceeds_size_limit(self):
        f = SimpleUploadedFile("huge.pdf", b"\x00" * (DOCUMENT_MAX_SIZE + 1), content_type="application/pdf")
        with pytest.raises(ValidationError, match="file size"):
            validate_document_upload(f)


class TestContentMatchesExtension:
    """SEC-08 — the bytes-based magic-byte helpers used by streamed/LLM upload paths."""

    def test_matching_header_passes(self):
        assert content_matches_extension(b"%PDF-1.7 ...", ".pdf") is True
        assert content_matches_extension(b"PK\x03\x04....", "xlsx") is True  # dot-less ext ok
        assert content_matches_extension(b"\x89PNG\r\n\x1a\n", ".png") is True

    def test_spoofed_header_fails(self):
        assert content_matches_extension(b"MZ\x90\x00", ".pdf") is False  # PE/EXE posing as pdf
        assert content_matches_extension(b"<html>", ".xlsx") is False

    def test_webp_compound_signature(self):
        # RIFF + "WEBP" passes; RIFF + "WAVE"/"AVI " (other RIFF containers) must fail.
        assert content_matches_extension(b"RIFF\x00\x00\x00\x00WEBP....", ".webp") is True
        assert content_matches_extension(b"RIFF\x00\x00\x00\x00WAVE....", ".webp") is False
        assert content_matches_extension(b"RIFF\x00\x00\x00\x00AVI ....", "webp") is False

    def test_text_and_unknown_formats_pass(self):
        # No reliable signature → never blocks (csv/txt/tsv + unknown extensions).
        assert content_matches_extension(b"a,b,c\n1,2,3", ".csv") is True
        assert content_matches_extension(b"anything", ".txt") is True
        assert content_matches_extension(b"anything", "") is True

    def test_assert_helper_raises_on_spoof(self):
        # .pdf name but PNG bytes → ValidationError (keeps caller's own ext/size allowlist).
        f = SimpleUploadedFile("scan.pdf", b"\x89PNG\r\n\x1a\n" + b"\x00" * 50, content_type="application/pdf")
        with pytest.raises(ValidationError, match="does not match"):
            assert_content_matches_extension(f, "Company document")

    def test_assert_helper_passes_real_file_and_rewinds(self):
        f = SimpleUploadedFile("scan.pdf", b"%PDF-1.4 body", content_type="application/pdf")
        assert_content_matches_extension(f, "Company document")
        # Must not consume the stream — the caller still needs to store it.
        assert f.read().startswith(b"%PDF")


def test_export_neutralizes_formula_injection():
    """Audit H5: CSV/XLSX cells starting with =,+,-,@ are prefixed with ' so Excel/Sheets
    won't execute them."""
    from core.exporters import _normalize_value

    assert _normalize_value('=HYPERLINK("http://evil")') == '\'=HYPERLINK("http://evil")'
    assert _normalize_value("+1+1") == "'+1+1"
    assert _normalize_value("@SUM(A1)") == "'@SUM(A1)"
    assert _normalize_value("-2") == "'-2"
    assert _normalize_value("Normal Co") == "Normal Co"  # untouched
