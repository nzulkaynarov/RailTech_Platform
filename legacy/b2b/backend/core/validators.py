"""
File upload validators for RailTech B2B platform.

Provides validation for images, avatars, and documents with extension,
content-type, and file size checks.
"""

import os

from django.core.exceptions import ValidationError

ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"}
ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
}

ALLOWED_DOCUMENT_EXTENSIONS = ALLOWED_IMAGE_EXTENSIONS | {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt"}
ALLOWED_DOCUMENT_CONTENT_TYPES = ALLOWED_IMAGE_CONTENT_TYPES | {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/csv",
    "text/plain",
}

IMAGE_MAX_SIZE = 5 * 1024 * 1024  # 5 MB
AVATAR_MAX_SIZE = 2 * 1024 * 1024  # 2 MB
DOCUMENT_MAX_SIZE = 20 * 1024 * 1024  # 20 MB

# Magic-byte signatures by extension. The client-supplied content_type is
# spoofable, so for binary formats we additionally verify the file header.
# Text formats (.svg, .csv, .txt) have no reliable signature and are skipped.
_MAGIC_SIGNATURES = {
    ".pdf": [b"%PDF"],
    ".png": [b"\x89PNG\r\n\x1a\n"],
    ".gif": [b"GIF87a", b"GIF89a"],
    ".jpg": [b"\xff\xd8\xff"],
    ".jpeg": [b"\xff\xd8\xff"],
    ".webp": [b"RIFF"],  # bytes 0-3; "WEBP" lives at 8-11
    # OOXML (xlsx/docx) and legacy OLE2 (xls/doc) containers
    ".xlsx": [b"PK\x03\x04"],
    ".docx": [b"PK\x03\x04"],
    ".xls": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],
    ".doc": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],
}


def _check_magic_bytes(file, ext, label):
    """Verify the file header matches its extension. No-op for text formats."""
    signatures = _MAGIC_SIGNATURES.get(ext)
    if not signatures:
        return
    try:
        file.seek(0)
        header = file.read(16)
    finally:
        file.seek(0)
    if not any(header.startswith(sig) for sig in signatures):
        raise ValidationError(f"{label}: file content does not match its '{ext}' extension (possible spoofing).")


def _validate_file(file, allowed_extensions, allowed_content_types, max_size, label="File"):
    """Common validation logic for uploaded files."""
    ext = os.path.splitext(file.name)[1].lower()
    if ext not in allowed_extensions:
        raise ValidationError(
            f"{label}: extension '{ext}' is not allowed. " f"Allowed: {', '.join(sorted(allowed_extensions))}"
        )

    content_type = getattr(file, "content_type", None)
    if content_type and content_type not in allowed_content_types:
        raise ValidationError(f"{label}: content type '{content_type}' is not allowed.")

    if file.size > max_size:
        max_mb = max_size / (1024 * 1024)
        raise ValidationError(f"{label}: file size {file.size} bytes exceeds " f"the maximum of {max_mb:.0f} MB.")

    _check_magic_bytes(file, ext, label)


def validate_image_upload(file):
    """Validate an image upload: extensions (jpg,jpeg,png,gif,webp,svg), content-type, 5MB limit."""
    _validate_file(
        file,
        allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
        allowed_content_types=ALLOWED_IMAGE_CONTENT_TYPES,
        max_size=IMAGE_MAX_SIZE,
        label="Image",
    )


def validate_avatar_upload(file):
    """Validate an avatar upload: same image extensions, 2MB limit."""
    _validate_file(
        file,
        allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
        allowed_content_types=ALLOWED_IMAGE_CONTENT_TYPES,
        max_size=AVATAR_MAX_SIZE,
        label="Avatar",
    )


def validate_document_upload(file):
    """Validate a document upload: images + pdf,doc,docx,xls,xlsx,csv,txt, 20MB limit."""
    _validate_file(
        file,
        allowed_extensions=ALLOWED_DOCUMENT_EXTENSIONS,
        allowed_content_types=ALLOWED_DOCUMENT_CONTENT_TYPES,
        max_size=DOCUMENT_MAX_SIZE,
        label="Document",
    )
