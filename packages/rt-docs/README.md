# rt-docs

Документы на бланке (ADR-0020): тело JSON (`packages/contracts/documents`) → HTML → PDF (WeasyPrint), DOCX, «Подогнать»,
форматтеры ru/uz/en, миграция HTML-шаблонов ERP. Шрифты Noto (OFL-1.1) вшиты — `rt_docs/fonts/OFL.txt`.

API, эталоны и подключение — [docs/architecture/rt-docs.md](../../docs/architecture/rt-docs.md).

```bash
make install     # uv sync --frozen
make test-unit   # тесты без рендера PDF
make check       # ruff, mypy --strict, все тесты с эталонными PDF в контейнере (pango, harfbuzz; сеть выключена)
```
