"""Tests for core.validators — file upload validation."""

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from core.validators import (
    AVATAR_MAX_SIZE,
    DOCUMENT_MAX_SIZE,
    IMAGE_MAX_SIZE,
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
        f = SimpleUploadedFile("test.png", b"\x89PNG" + b"\x00" * 100, content_type="image/png")
        validate_image_upload(f)

    def test_valid_svg(self):
        f = SimpleUploadedFile("icon.svg", b"<svg></svg>", content_type="image/svg+xml")
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
        f = SimpleUploadedFile("ok.jpg", b"\x00" * IMAGE_MAX_SIZE, content_type="image/jpeg")
        # Should not raise
        validate_image_upload(f)


class TestValidateAvatarUpload:
    """Tests for validate_avatar_upload (2MB limit)."""

    def test_valid_small_avatar(self):
        f = SimpleUploadedFile("avatar.png", b"\x89PNG" + b"\x00" * 100, content_type="image/png")
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
            b"\x00" * 100,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
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
