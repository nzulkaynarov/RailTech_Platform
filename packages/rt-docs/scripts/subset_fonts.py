"""Пересборка вшитых шрифтов rt_docs/fonts из исходников Noto 2.015 (OFL-1.1, без Reserved Font Name).

    uv run python scripts/subset_fonts.py <каталог-с-исходными-ttf>

Исходники (hinted/ttf) — https://github.com/notofonts/notofonts.github.io/tree/main/fonts/{NotoSans,NotoSerif}/hinted/ttf;
SHA-256 ниже сверяется до подмножества. Подмножество: латиница с расширениями (узбекская латиница, ʻ U+02BB, ʼ U+02BC),
кириллица с дополнением (ў қ ғ ҳ), пунктуация, валюты, №, стрелки и знаки сравнения; без хинтинга (PDF он не нужен).
Зачем подмножество — 8 файлов ≈ 1,7 МБ вместо ≈ 5,5 МБ. Почему Noto — docs/architecture/rt-docs.md §4.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from fontTools import subset

UNICODES = (
    "U+0020-007E,U+00A0-024F,U+02B0-02FF,U+0300-036F,U+0400-052F,U+1E00-1EFF,U+2000-206F,U+20A0-20CF,"
    "U+2100-214F,U+2190-2199,U+2212,U+2215,U+2219,U+221E,U+2248,U+2260-2265,U+25CF,U+FEFF,U+FFFD"
)
SOURCES = {
    "NotoSans-Regular.ttf": "478c558ea716033cd60c03438f628dfa75694dcf6b5f6d505a2f05fd2b4f3823",
    "NotoSans-Bold.ttf": "1df075a380fc7cb898acf64c1f7b3b4dd780de3caa860178bf929de35817a913",
    "NotoSans-Italic.ttf": "467e3f89eeca4108bb8710a2b9e0cf2281ac56d5b0609211a83776d0505eecb5",
    "NotoSans-BoldItalic.ttf": "1b602a9d6353be42c91df097a4857b69fa2696f26703d7a33b54a15d87c2622c",
    "NotoSerif-Regular.ttf": "19e72cd8d595fae5bd74a5206f5d938512e1183d4fed7abb1ec1be1d7efa5f88",
    "NotoSerif-Bold.ttf": "96656aa5cec8f1d6fd0e804c1fad397e1a1cfa082e6642124e0bda68cd8363ce",
    "NotoSerif-Italic.ttf": "749e80e313ef711f9373c6cce17c72297ef05490b3dcda7967d1d5d90bf1183f",
    "NotoSerif-BoldItalic.ttf": "c710c5b9cf354ae46e7a10472a08019b28220fafeb5887a482a76856f8f6fc0b",
}
TARGET = Path(__file__).resolve().parent.parent / "rt_docs" / "fonts"


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    src = Path(argv[0])
    for name, digest in SOURCES.items():
        data = (src / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            print(f"{name}: SHA-256 не совпадает с Noto 2.015")
            return 1
        subset.main(
            [
                str(src / name),
                f"--unicodes={UNICODES}",
                "--layout-features=*",
                "--no-hinting",
                "--name-IDs=*",
                "--name-languages=*",
                "--notdef-outline",
                f"--output-file={TARGET / name}",
            ]
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
