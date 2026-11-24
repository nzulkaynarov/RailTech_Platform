"""Пересборка вшитых шрифтов rt_docs/fonts из исходников (SIL OFL 1.1, без Reserved Font Name).

    uv run python scripts/subset_fonts.py <каталог-с-исходными-ttf>

Каталог может содержать часть исходников — пересобираются те, что лежат в нём; SHA-256 сверяется до подмножества.

- Inter 4.1 — https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip, `extras/ttf/`; основной шрифт
  документа (стандарт документов §3, решение владельца 2026-11-15).
- JetBrains Mono 2.304 — https://github.com/JetBrains/JetBrainsMono/releases/download/v2.304/JetBrainsMono-2.304.zip,
  `fonts/ttf/`; коды: номер документа, ИНН, МФО, счёт, артикул. В нём нет `ʻ` и `Ҳҳ` — CSS ставит Inter запасным.
- Noto Serif 2.015 (hinted/ttf) — https://github.com/notofonts/notofonts.github.io/tree/main/fonts/NotoSerif/hinted/ttf;
  «с засечками» бланка для договоров и писем госорганам.

Подмножество: латиница с расширениями (узбекская латиница, Ö Ğ Ş Ç, ʼ U+02BC), кириллица с дополнением (ў қ ғ ҳ),
пунктуация, валюты, №, стрелки и знаки сравнения; без хинтинга (PDF он не нужен).
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
    "Inter-Regular.ttf": "40d692fce188e4471e2b3cba937be967878f631ad3ebbbdcd587687c7ebe0c82",
    "Inter-Italic.ttf": "bbc051dd204b5019a1aa0bc0ae2aa8a05ab13e7a3f979fa357631dc7feb6833a",
    "Inter-SemiBold.ttf": "78a843fade9d4612a5567302fb595b56976eb5fcebf4fea5a5912d638bafcde3",
    "Inter-Bold.ttf": "288316099b1e0a47a4716d159098005eef7c0066921f34e3200393dbdb01947f",
    "Inter-BoldItalic.ttf": "948405a16cdc62701da5f4005ed068ca5f4d27061d98f7974ccfc37831d9581d",
    "JetBrainsMono-Regular.ttf": "a0bf60ef0f83c5ed4d7a75d45838548b1f6873372dfac88f71804491898d138f",
    "JetBrainsMono-SemiBold.ttf": "1b3bfa1ed5665a4ce3f9feb68d2d4e40e70bf8b4b7d9a3edd418f321b4e166a0",
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
    present = {name: digest for name, digest in SOURCES.items() if (src / name).is_file()}
    if not present:
        print(f"в {src} нет ни одного исходника из списка")
        return 1
    for name, digest in present.items():
        data = (src / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            print(f"{name}: SHA-256 не совпадает с выпуском из описания")
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
