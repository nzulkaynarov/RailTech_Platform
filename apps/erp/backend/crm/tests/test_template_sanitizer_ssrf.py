"""T3 regression: document-body sanitizer must not let a remote <img src> survive.

WeasyPrint's default url_fetcher performs a server-side GET of any remote `src` at PDF
render time, and the render box sits on the private LAN to the DB-VPS — so an author-chosen
`<img src="http://10.0.0.2/">` / cloud-metadata URL would be a blind SSRF. Only inline base64
rasters (which carry no fetch) are allowed. The letterhead logo is a company FileField rendered
outside this sanitizer and is unaffected.
"""

import pytest

from crm.services.document_placeholders import sanitize_template_html


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data/",
        "https://10.0.0.2:5432/",
        "http://127.0.0.1/",
        "//evil.example/x.png",
        "/media/whatever.png",
        "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
    ],
)
def test_remote_or_svg_img_src_is_dropped(url):
    cleaned = sanitize_template_html(f'<p>x</p><img src="{url}">')
    assert "169.254" not in cleaned
    assert "10.0.0.2" not in cleaned
    assert "127.0.0.1" not in cleaned
    assert "evil.example" not in cleaned
    assert "svg" not in cleaned.lower()
    # The paragraph text survives — only the unsafe src (and thus the empty img) is stripped.
    assert "<p>x</p>" in cleaned


def test_inline_base64_raster_img_survives():
    data_uri = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNgAAAAAgAB"
    cleaned = sanitize_template_html(f'<img src="{data_uri}">')
    assert data_uri in cleaned
