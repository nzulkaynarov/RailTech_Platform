"""Вложения писем ERP/EDS по ссылке на объект хранилища (W18A-P1): источник, размер, sha256."""

import hashlib

import httpx
import pytest

from app.integrations.mail_attachments import AttachmentError, AttachmentRef, HttpAttachmentFetcher

PDF = b"%PDF-1.7 fake quote"
URL = "http://rustfs:9000/erp-temp/mail/abc/quote.pdf?X-Amz-Signature=00"


def ref(url: str = URL, content: bytes = PDF, **kw: object) -> AttachmentRef:
    base: dict[str, object] = {
        "url": url,
        "filename": "КП.pdf",
        "content_type": "application/pdf",
        "size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    return AttachmentRef(**{**base, **kw})  # type: ignore[arg-type]


def fetcher(handler: object, **kw: object) -> HttpAttachmentFetcher:
    return HttpAttachmentFetcher(
        ("http://rustfs:9000",),
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )


async def test_downloads_and_checks_size_and_sha256() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, content=PDF)

    assert await fetcher(handler).fetch(ref()) == PDF
    assert seen == [URL]


async def test_foreign_host_is_refused_without_a_request() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=PDF)

    with pytest.raises(AttachmentError) as info:
        await fetcher(handler).fetch(ref(url="http://169.254.169.254/latest/meta-data"))
    assert (info.value.reason, info.value.permanent) == ("attachment_foreign_host", True)
    assert calls == []


@pytest.mark.parametrize(
    ("status", "permanent"), [(403, True), (404, True), (410, True), (503, False), (500, False)]
)
async def test_expired_or_missing_is_permanent_server_errors_are_retried(
    status: int, permanent: bool
) -> None:
    with pytest.raises(AttachmentError) as info:
        await fetcher(lambda _: httpx.Response(status)).fetch(ref())
    assert (info.value.reason, info.value.permanent) == ("attachment_unavailable", permanent)


async def test_redirect_is_not_followed() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"Location": "http://evil.example/x"})

    with pytest.raises(AttachmentError) as info:
        await fetcher(handler).fetch(ref())
    assert info.value.permanent is False


async def test_network_error_is_retried() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(AttachmentError) as info:
        await fetcher(handler).fetch(ref())
    assert (info.value.reason, info.value.permanent) == ("attachment_unavailable", False)


async def test_tampered_or_oversized_content_is_refused() -> None:
    with pytest.raises(AttachmentError) as info:
        await fetcher(lambda _: httpx.Response(200, content=b"other")).fetch(ref())
    assert (info.value.reason, info.value.permanent) == ("attachment_mismatch", True)
    big = b"x" * 64
    with pytest.raises(AttachmentError) as info:
        await fetcher(lambda _: httpx.Response(200, content=big), max_bytes=32).fetch(
            ref(content=big, size=16)
        )
    assert info.value.reason == "attachment_too_large"


@pytest.mark.parametrize(
    "url", ["http://[::1/x.pdf", "http://rustfs:notaport/erp-temp/x.pdf", "http://rustfs:99999/x"]
)
async def test_unparsable_link_is_a_foreign_host_not_a_crash(url: str) -> None:
    """Ревью #322: адрес, который `urlsplit` не разбирает (ValueError), — отказ, а не исключение."""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, content=PDF)

    with pytest.raises(AttachmentError) as info:
        await fetcher(handler).fetch(ref(url=url))
    assert (info.value.reason, info.value.permanent) == ("attachment_foreign_host", True)
    assert calls == []
