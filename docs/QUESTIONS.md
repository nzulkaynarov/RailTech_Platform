# QUESTIONS — открытые вопросы владельцу

Формат: контекст → варианты → рекомендация. После ответа строка переезжает в `DECISIONS.md`.

Q-1…Q-9 решены — см. `DECISIONS.md`.

## Q-10 · Биллинг GitHub Actions (только владелец)

**Контекст.** Первый прогон workflow на `main` (run 38381096602) упал без единого шага: «The job was not started because recent account payments have failed or your spending limit needs to be increased». Это настройка аккаунта GitHub, агент её изменить не может. Пока так — CI на GitHub не работает, гейт мержа — `make ci-local`.

**Варианты.**
1. Settings → Billing & plans: исправить способ оплаты / поднять spending limit для Actions (минуты GitHub-hosted; для приватного репозитория на Free — 2000 мин/мес бесплатно после разблокировки).
2. Self-hosted раннер на Linux-машине вне прода (задать переменную репозитория `CI_RUNNER=self-hosted`). На macOS сервис-контейнеры (`services:`) не поддерживаются, поэтому Mac владельца не подходит без переделки workflow.

**Рекомендация.** Вариант 1 — быстрее и без обслуживания; после первого зелёного прогона включить защиту `main` с обязательной проверкой `ci-ok`.
