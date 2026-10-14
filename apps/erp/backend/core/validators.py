"""
File upload validators for RailTech B2B platform.

Provides validation for images, avatars, and documents with extension,
content-type, and file size checks.
"""

import os
import re

from django.core.exceptions import ValidationError

# A #RGB / #RRGGBB colour. Used to validate the seller's brand accent_color BEFORE it is
# interpolated into a <style> block in the PDF templates — an unvalidated value is CSS
# injection → WeasyPrint SSRF/LFI on render (audit #9).
HEX_COLOR_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def is_hex_color(value) -> bool:
    """True if `value` is a safe #RGB / #RRGGBB colour literal (nothing else may reach CSS)."""
    return bool(value and HEX_COLOR_RE.match(str(value).strip()))


# SVG removed (audit H6): SVGs carry inline <script>/onload, have no magic-byte signature,
# and are served same-origin as image/svg+xml → stored XSS. Raster formats only.
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
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
    # OOXML (xlsx/docx) and legacy OLE2 (xls/doc) containers
    ".xlsx": [b"PK\x03\x04"],
    ".docx": [b"PK\x03\x04"],
    ".xls": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],
    ".doc": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],
    # NOTE: .webp is NOT here — it's a RIFF container (bytes 0-3 "RIFF") whose PREFIX is
    # shared by WAV and AVI. Matching "RIFF" alone would let a .webp-named WAV/AVI through
    # (SEC-08 adversarial finding). WebP is checked specially in `_matches_signature`:
    # "RIFF" at 0-3 AND the "WEBP" form-type at bytes 8-11.
}


def _matches_signature(header: bytes, ext: str) -> bool:
    """True if `header` matches the magic signature for `ext`.

    WebP needs a COMPOUND check (RIFF prefix + "WEBP" form-type) because "RIFF" alone also
    matches WAV/AVI. Extensions with no known signature (text: csv/txt/tsv, or unknown) return
    True — there is nothing reliable to verify.
    """
    if ext == ".webp":
        return header[:4] == b"RIFF" and header[8:12] == b"WEBP"
    signatures = _MAGIC_SIGNATURES.get(ext)
    if not signatures:
        return True
    return any((header or b"").startswith(sig) for sig in signatures)


def _has_signature(ext: str) -> bool:
    return ext == ".webp" or ext in _MAGIC_SIGNATURES


def _check_magic_bytes(file, ext, label):
    """Verify the file header matches its extension. No-op for text formats."""
    if not _has_signature(ext):
        return
    try:
        file.seek(0)
        header = file.read(16)
    finally:
        file.seek(0)
    if not _matches_signature(header, ext):
        raise ValidationError(f"{label}: file content does not match its '{ext}' extension (possible spoofing).")


def content_matches_extension(header: bytes, ext: str) -> bool:
    """True if `header` (a file's first bytes) matches the magic signature for `ext`.

    Bytes-based sibling of `_check_magic_bytes` for callers that already hold the content
    (streamed uploads sent straight to a task / the LLM, where the Django file object may be
    exhausted). Text / unknown formats have no reliable signature → always True.
    """
    ext = (ext or "").lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    return _matches_signature(header, ext)


def assert_content_matches_extension(file, label="File"):
    """Magic-byte-only guard on a Django UploadedFile — content must match its extension.

    For callers that keep their OWN extension/size allowlist (stricter than
    `validate_document_upload`) but still need anti-spoofing. Raises ValidationError.
    """
    ext = os.path.splitext(file.name)[1].lower()
    _check_magic_bytes(file, ext, label)


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
