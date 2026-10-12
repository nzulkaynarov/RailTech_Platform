# Ротация ключей и секретов

## Когда применять
Плановая ротация (раз в 6 месяцев), уход сотрудника с доступом к VPS/`.env`, подозрение на утечку.

## Диагностика
Где живёт секрет: только `.env` на стенде (и GitHub Secrets для CI/деплоя). В коде, образах
и логах секретов нет (gitleaks в CI, маскирование PII/ключей в логах).

## Действие
Общий порядок: новое значение в `.env` → `make up-prod` (пересоздаст контейнеры) → проверка.

| Секрет | Как ротировать | Эффект |
|---|---|---|
| `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` | новый ключ в консоли провайдера (с лимитом), `.env`, `make up-prod`, затем отозвать старый | без простоя |
| `LITELLM_MASTER_KEY` | новое значение, `make up-prod` (api/worker получат его тем же рестартом) | секунды |
| `JWT_SECRET` | `openssl rand -hex 32` → `.env` → `make up-prod` | все пользователи перелогиниваются |
| `AGENT_CONTEXT_KEY` | `openssl rand -hex 32` → `.env` → `make up-prod` | ходы в процессе на момент рестарта получат отказ MCP — повторятся при следующем сообщении |
| `TELEGRAM_WEBHOOK_SECRET` | новое значение → `make up-prod` (api ставит webhook заново) → `scripts/set_webhook.py` | секунды |
| Токен бота | @BotFather → `/revoke` → CRM «Подключения» → «Проверить и сохранить» (пароль админа); бот перезапускается без рестарта API. Без `SECRETS_KEY` — `TELEGRAM_BOT_TOKEN` в `.env` → `make up-prod` | старый токен перестаёт работать сразу |
| `SECRETS_KEY` | `openssl rand -hex 32` → `.env` → `make up-prod`, затем заново ввести токен бота в «Подключениях» (старый шифртекст не расшифруется — до этого бот работает на `TELEGRAM_BOT_TOKEN` из `.env`, если он задан) | бот без токена из БД до повторного ввода |
| `POSTGRES_PASSWORD` | ⚠️ `docker compose exec postgres psql -U $POSTGRES_USER -c "ALTER USER ... PASSWORD '...'"`, затем `.env`, `make up-prod` | минута простоя |
| `S3_ACCESS_KEY/SECRET` | ⚠️ меняются вместе с данными RustFS: новый ключ в `.env`, `make up-prod`; проверить скачивание документа | минута простоя |
| `DOCLING_API_KEY`, `LANGFUSE_*` | новое значение → `make up-prod` (Langfuse-ключи — создать в UI проекта) | без простоя |
| GitHub `VPS_SSH_KEY` | новый ключ в `~deploy/.ssh/authorized_keys`, secret в GitHub, удалить старый | — |

Пароли пользователей CRM: админ → «Сбросить пароль» (временный, смена при входе).

## Проверка
`make smoke-prod`; вход в CRM; сообщение боту → ответ; Langfuse получает трейсы; `scripts/set_webhook.py` без `last_error`.

## Эскалация
Владельцу системы: какой секрет, время ротации, результат smoke.
