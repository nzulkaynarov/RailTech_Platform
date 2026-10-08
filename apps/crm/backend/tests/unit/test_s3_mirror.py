from pathlib import Path

import pytest

from app.cli.s3_mirror import local_path


@pytest.mark.parametrize(
    ("key", "expected"),
    [("a.pdf", "b/a.pdf"), ("kb/2026/x.md", "b/kb/2026/x.md")],
)
def test_local_path(key: str, expected: str) -> None:
    assert local_path(Path("/r"), "b", key) == Path("/r") / expected


@pytest.mark.parametrize("key", ["", "/etc/passwd", "../x", "a/../../x", "a/./b", "a//b"])
def test_local_path_rejects_unsafe_keys(key: str) -> None:
    with pytest.raises(ValueError, match="unsafe"):
        local_path(Path("/r"), "b", key)
