# Runbook: шина rt_bus в ERP — события не доходят, DLQ, повтор, метрики (B3)

Контракт — `docs/architecture/CONTRACTS.md` §9 (конверт, доставка, подпись, повтор), §9.7 (ERP на шине); устройство и API библиотеки —
`docs/architecture/rt-bus.md`; решение — ADR-0014. Заменяет `webhooks.md` для стороны ERP. Для CRM — runbook шины CRM (B4).

Как идут события ERP → CRM: сервис ERP пишет строку в `rt_bus_outbox` в транзакции изменения → Celery-задача `rt_bus.pump`
(сразу после коммита — «пробуждение» через `transaction.on_commit`; Beat каждые 5 с остаётся страховкой) раскладывает outbox по подписчикам (`rt_bus_delivery`, строка на подписчика)
и отправляет подписанный `POST <endpoint>/bus/v1/events` → при отказе повтор через 30 с, 2 мин, 10 мин, 1 ч, 6 ч, 24 ч (± 20 %),
затем `dead`. В обратную сторону: `POST /bus/v1/events` в `erp-backend` → `rt_bus_inbox` → задача `rt_bus.process_inbox` →
обработчик проекции (клиент и контакт CRM).

## Симптом → где смотреть

| Симптом | Где смотреть | Что значит |
|---|---|---|
| Клиент не получил сообщение бота о КП/счёте, в ленте лида нет записи | `manage.py bus_retry --list --subscriber crm` (админка: «rt_bus → Delivery», фильтр по подписчику и статусу; названия моделей — по библиотеке) | `pending` с растущими `attempts` — CRM отвечает ошибкой, идут повторы; `dead` — отказ без повтора или повторы кончились; строки нет вовсе — компания не сопоставлена с клиентом CRM (`CrmClientMapping`), события для неё не публикуются |
| Все доставки подписчика сразу `dead`, `last_status_code` 404 (или 410) | та же выборка | **Неверный `endpoint`** подписчика или не развёрнутый приёмник: 404/410 шина считает «повтор не поможет» и отправляет в DLQ сразу. Лечение — ниже, «Неверный адрес подписчика» |
| `pending`, `attempts = 0`, `next_attempt_at` через ~5 мин | то же | Нет секрета пары (`RT_BUS_SECRET_ERP_CRM` не задан, сопряжения и `ERP_WEBHOOK_SECRET` нет) или подписчика нет в `subscriptions.yaml`: доставка откладывается без засчитанной попытки, неподписанной не уходит |
| `pending` вообще не сдвигаются, в `rt_bus_outbox` растёт хвост `dispatched_at IS NULL` | `docker compose … logs erp-worker erp-beat` | не работает `rt_bus.pump`: лежит Celery-воркер, Beat или Redis; шина сама не теряет событие — после запуска воркера всё уйдёт |
| `dead` с ошибкой `SECRET_EXPIRED` | журнал доставок | Код акцепта протух в кэше (CRM была недоступна дольше 20 минут или Redis ERP перезапускали) **либо кэш был недоступен в момент доставки** — библиотека не откладывает доставку до возвращения кэша (журнал вебхуков делал это, S0-2). «Повторить» не оживит: клиент запрашивает новый код в Cabinet. Если кэш лежит в момент *запроса* кода — запрос отвечает 503 `SERVICE_TEMPORARILY_UNAVAILABLE`, код не выпускается и события нет |
| Подписчик на паузе (`SubscriberState.paused_until`) | админка: «rt_bus → Subscriber state» | 5 повторяемых ошибок подряд → пауза 5 мин, потом одна пробная доставка; остальные подписчики идут |
| Входящее событие CRM в статусе `failed` | «rt_bus → Inbox» (`status = failed`, поле `error`) | обработчик проекции падал 4 раза (30 с, 2 мин, 10 мин); после исправления причины — «Повторить обработку» |
| Входящее в статусе `skipped` | «rt_bus → Inbox» | ERP на этот тип не подписана или версия выше поддерживаемой — не ошибка; в `projection_status` журнала — `skipped_unknown_client`: клиента CRM ещё нет в ERP (передача `POST /clients/handoff` не состоялась) |
| Контакт удалён в CRM, но «всё ещё есть» в ERP | карточка контакта / `Contact.archived_at` | Контакт не удаляется, а архивируется: запись, сделки и коды акцепта остаются (след акцепта КП), вход в Cabinet и приглашение закрыты. Вернуть можно только новым снимком из CRM (`contact.updated` позже удаления) |
| E-mail контакта в ERP стал пустым или другим | `Contact.email`, лог `rt_bus_projection` | E-mail — поле CRM: снимок заменяет его целиком. Следствие для Cabinet: вход по ссылке на e-mail работает только по адресу, который сейчас в CRM; если в CRM адрес стёрт, контакт заходит лишь через Telegram. Исправлять адрес нужно в CRM |
| Правка названия или ИНН клиента в ERP/Cabinet отвечает `REQUISITES_MANAGED_BY_CRM` | — | Название и ИНН компании, связанной с CRM, ведёт CRM; меняйте их там, ERP применит снимок `client.updated` |
| CRM шлёт события, ERP отвечает 401 | логи `erp-backend`: `rt_bus_receive_rejected` (причина без значений секрета) | подпись не сошлась: секреты пары расходятся (`RT_BUS_SECRET_CRM_ERP` / секрет вебхуков сопряжения), метка вне окна 300 с (часы серверов), `X-RT-Publisher` не совпал с `source` |

## Неверный адрес подписчика (404/410 → dead)

1. Убедитесь по журналу: у всех `dead` подписчика `last_status_code` 404/410, `attempts = 1`.
2. Исправьте адрес: строка `endpoint` в `packages/contracts/bus/subscriptions.yaml` (образ) либо переменная `RT_BUS_ENDPOINT_CRM`
   в `.env.prod` / `.env` стенда (она главнее); перезапуск воркеров не нужен для файла подписок (перечитывается по времени
   изменения), для переменной окружения — `docker compose … up -d erp-worker erp-beat erp-backend`.
3. Повторите все `dead` подписчика: `docker compose … exec erp-backend python manage.py bus_retry --all-dead --subscriber crm`
   (или админка → «rt_bus → Delivery» → действие «Повторить все dead выбранных подписчиков»; видно только суперпользователю,
   требует причину, пишется в «Журнал доступа»). Попытки обнуляются, доставка идёт при ближайшем `pump`.
4. Проверка: `manage.py bus_retry --list --status dead --subscriber crm` пуст, свежие строки `delivered`; в CRM события появились в ленте.

Приёмник ERP `/bus/v1/events` снаружи закрыт: Caddy отвечает на `{ERP_DOMAIN}/bus*` 404 (так и должно быть). Если CRM получает
404 от ERP, а не от Caddy, проверьте адрес `http://erp-backend:8000/bus/v1/events` — он внутри сети compose, не публичный домен.

## Повторить

* **Одну доставку**: `manage.py bus_retry --delivery <id>` (id из `--list`) или админка → действие «Повторить доставку». Повтор `delivered` бессмыслен
  (подписчик дубль погасит по `id` события, но попытка лишняя) — действие их пропускает.
* **Все dead подписчика**: `manage.py bus_retry --all-dead --subscriber crm` (без `--subscriber` — все подписчики).
* **Обработку входящего** (`failed`, `skipped`): `manage.py bus_retry --inbox <event-id>` или админка → «Повторить обработку».
* Повтор безопасен: подписчик гасит дубль по `id` события (200 `duplicate`), проекции ERP идемпотентны (снимок старее применённого
  не применяется).

## Метрики и алерты

Beat раз в 5 минут пишет в лог строку `rt_bus_metrics` (`erp-worker`): `outbox_pending`, `oldest_undelivered_age_seconds`, `dlq_size`,
`inbox_failed`, по подписчикам — `pending`, `in_flight`, `dead`, `consecutive_failures`, `paused`. То же по запросу:
`manage.py bus_retry --metrics`. Алерты (пока по логу): рост `dlq_size`, `inbox_failed > 0`, `oldest_undelivered_age_seconds` больше часа.
Уборка (`rt_bus.purge`, раз в сутки) удаляет доставленное и обработанное старше 30 дней; `dead` и `failed` остаются до ручного решения.

## Проверка после выкладки и на стенде

1. `docker compose … exec erp-backend python manage.py migrate rt_bus` (миграции шины в базе ERP; при выкладке — общий шаг миграций ERP).
2. В `erp-beat` есть расписание `rt_bus.pump` (5 с), `rt_bus.requeue_stuck_inbox` (60 с), `rt_bus.log_metrics` (5 мин), `rt_bus.purge` (сутки):
   `docker compose … logs erp-beat | grep rt_bus`. Устаревшей задачи `integration.requeue_stuck_webhook_events` нет (миграция
   `integration/0007` убирает её строку из БД Beat).
3. Секрет пары: либо `RT_BUS_SECRET_ERP_CRM` / `RT_BUS_SECRET_CRM_ERP` одинаковы у ERP и CRM, либо у обеих сторон один секрет сопряжения
   (`WEBHOOK_SECRET`) — тогда оба выводят пару сами (CONTRACTS §9.3). Проверка: отправьте КП в ERP, в журнале появляется строка
   `delivered` и событие видно в CRM.
4. Снаружи `/bus/v1/events` на домене ERP — 404: `curl -s -o /dev/null -w '%{http_code}' https://$ERP_DOMAIN/bus/v1/events` (тест Caddy в `make deploy-check`).

## Ротация секрета

Секрет пары выводится из секрета вебхуков сопряжения (первый в списке подписывает, принимается любой). При ротации
сопряжения (`POST /pairing/rotate`) ERP сохраняет прежний секрет на переходный срок (`PAIRING_ROTATION_GRACE_SECONDS`, 1 час) и
принимает события, подписанные им, — 401 не будет; по шагам — раздел «Ротация секрета вебхуков» в [`webhooks.md`](webhooks.md); для явных `RT_BUS_SECRET_*` — список «новый,прежний»
у обеих сторон, затем «новый».
