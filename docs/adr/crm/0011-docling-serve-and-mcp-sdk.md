# 0011. docling как сервис docling-serve; MCP-серверы на официальном SDK (`MCPServer`)

- Статус: accepted (2026-10-08, решение агента по поручению владельца)
- Дата: 2026-10-08
- Связано: SPEC §2 (Ингест документов, Инструменты агентов), §3.2, §4; PLAN Фаза 1; ADR-0007

## Контекст и проблема

1. **docling** тянет PyTorch и модели разметки PDF. На PyPI колёса torch для Linux собраны с CUDA (≈ 6 ГБ окружения); CPU-индекс PyTorch (`download.pytorch.org`) из среды разработки агента недоступен по сетевой политике, и lock-файл с ним не собрать. Тащить CUDA-torch в образ api/worker — неприемлемо (размер, время сборки, VPS без GPU).
2. **«FastMCP (Python SDK)»** в SPEC: в официальном SDK `mcp` 2.x класс FastMCP переименован в `MCPServer`; одноимённый пакет `fastmcp` (v4) — отдельный проект.

## Решение

1. **docling-serve** — официальный HTTP-сервис проекта docling, CPU-образ `ghcr.io/docling-project/docling-serve-cpu:v1.36.0` (модели внутри образа), отдельный сервис compose `docling` во внутренней сети, доступ по `X-Api-Key` (`DOCLING_API_KEY`). Worker отправляет файл в `POST /v1/convert/file` (`to_formats=json`) и получает DoclingDocument.
   - Чанкинг — в worker на `docling-core` (`HybridChunker`, markdown-таблицы через `ChunkingDocSerializer` + `MarkdownTableSerializer`), без torch.
   - Токены для размера чанка считаются офлайн-оценкой (`BaseTokenizer` docling-core): tiktoken при первом использовании скачивает словарь из интернета, а точный токенизатор провайдера embedding всё равно недоступен.
   - Перекрытие чанков 50 токенов из PLAN не используется: `HybridChunker` режет по структуре документа (заголовки, абзацы, таблицы) и добавляет путь заголовков к тексту для embedding — контекст на границах сохраняется без дублирования текста.
2. **MCP** — официальный SDK `mcp` 2.x, класс `MCPServer` (бывший FastMCP), транспорт streamable HTTP в stateless-режиме с JSON-ответами; клиент — `mcp.Client` + `streamable_http_client` с заголовком `X-Agent-Context`.

## Рассмотренные варианты

- docling в процессе worker с CUDA-torch — отклонено (размер); с CPU-torch — невозможно собрать lock в среде разработки.
- Свой парсер PDF/DOCX — противоречит SPEC §1.7.
- Пакет `fastmcp` v4 — сторонний проект поверх SDK; официальный SDK покрывает нужное.

## Последствия

- Хорошо: образ backend без torch (~0.4 ГБ окружения), docling обновляется заменой тега; конвертация изолирована и масштабируется отдельно.
- Плохо: ещё один сервис (~4.4 ГБ образ, ~1–2 ГБ RAM); первый запуск dev скачивает образ дольше.
- SPEC §2, §3.2 обновлены.

## Как проверяем

Integration: ингест с фейковым конвертером; dev (человек): `make kb-demo` → документы `done`, таблица в чанке — markdown; PDF с таблицей через `make kb-ingest`.
