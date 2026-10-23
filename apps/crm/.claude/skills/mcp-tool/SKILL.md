---
name: mcp-tool
description: Добавить инструмент в MCP-сервер (kb-mcp, crm-mcp, docs-mcp на FastMCP из пакета mcp) с HMAC-контекстом X-Agent-Context, негативными тестами и обновлением таблицы SPEC §7.1.
---

# Инструмент MCP

Инварианты: `SPEC §1.5`, `§7.1`, ADR-0008, ADR-0011. Инструмент **никогда** не принимает `lead_id`/`client_id` аргументом — только из проверенного заголовка `X-Agent-Context` (`app/security/agent_context.py`: `base64url(json).base64url(hmac_sha256)`, TTL 60 с).

## Шаги

1. Проверь, что инструмент есть в таблице `SPEC §7.1` и в текущей фазе `docs/history/crm/PLAN.md`. Нет — вопрос человеку (`docs/QUESTIONS.md`).
2. Сверь API FastMCP с установленной версией: `cd backend && uv run python -c "import mcp, importlib.metadata as m; print(m.version('mcp'))"` и документацией (WebFetch). Не выдумывай декораторы/параметры.
3. Реализация в `backend/app/mcp/<kb|crm|docs>_server.py`, общее — `app/mcp/common.py`, запуск — `app/mcp/servers.py`:
   - входная схема — Pydantic-модель, описание полей для модели;
   - контекст (`lead_id`, `client_id`, `mode`) — из зависимости проверки HMAC; ошибка подписи/срока → отказ без деталей;
   - доступ к данным — через сервис/репозиторий; для данных клиента SQL-фильтр по `client_id` из контекста обязателен;
   - логи structlog без PII (`security/pii.py`).
4. Клиент агента — `app/agents/mcp_client.py`; профиль инструментов по режиму (prospect/customer) — там же.
5. Тесты:
   - unit: схема, маппинг ошибок;
   - негативные: без заголовка, поддельная подпись, просроченный контекст, попытка передать идентификатор аргументом (схема его не принимает), чужой `client_id` (integration);
   - integration: реальный Postgres (одноразовый контейнер — скилл `stand-verify`).
6. Обнови таблицу `SPEC §7.1` (если изменилась сигнатура — сначала одобрение) и golden-кейс с `expect.tool_calls_any` (`eval-case`).
7. На стенде MCP-контейнеры не перечитывают код: `docker compose … restart crm-mcp kb-mcp docs-mcp worker` (см. `stand-verify`).
8. `make check`; в PR — шаг «Проверить на dev» с вопросом в боте, который вызывает инструмент, и ожидаемым трейсом в Langfuse.
