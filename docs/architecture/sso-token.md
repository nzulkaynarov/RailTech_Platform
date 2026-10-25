# SSO-токен сотрудника (CRM ↔ ERP, CRM → EDS)
Статус: действует · Владелец: архитектор · Обновлено: 2026-10-26

Источник: `docs/architecture/CONTRACTS.md` §6, ADR-0003. Версия 0 (M0-INF-02). Реализация: ERP — M3-ERP-04, CRM — M3-CRM-06.

## Формат

JWT **HS256**, общий секрет `PLATFORM_SSO_SECRET` (секрет окружения обеих систем; ротация — два
активных значения, принимающая сторона проверяет оба).

| Claim | Тип | Значение |
|---|---|---|
| `iss` | string | `crm` или `erp` — кто выдал |
| `aud` | string | `erp`, `crm` или `eds` — целевая система (приёмник отклоняет чужой `aud`; EDS — раздел «Токен сотрудника для EDS») |
| `sub` | string | `crm_user_id` как строка — идентификатор сотрудника в CRM (источник истины по людям) |
| `email` | string | e-mail сотрудника |
| `name` | string | отображаемое имя |
| `role` | string | `admin` \| `manager` \| `viewer` (роль CRM); `admin` = суперпользователь ERP |
| `permissions` | string[] | коды из каталога прав ERP (`ErpPermission` в `erp-integration.yaml`: `deal.*`, `quote.*`, `contract.*`, `catalog.*`, `supply.*`, `fulfillment.*`, `finance.*`, `settings.*`, `team.*`, `data.*`) по карте ниже; для `aud=erp`, при обмене не применяются (права приходят провижинингом). Для `aud=eds` — коды `permissions.eds` сотрудника (`EdsPermission` в `openapi/eds.yaml`), справочно: EDS их не применяет (раздел «Токен сотрудника для EDS») |
| `iat` | number | момент выдачи, unix seconds |
| `exp` | number | `iat + 60` |
| `jti` | string | UUID v4, одноразовый |

Пример полезной нагрузки:

```json
{
  "iss": "crm",
  "aud": "erp",
  "sub": "42",
  "email": "estimator@example.com",
  "name": "Расчётчик",
  "role": "manager",
  "permissions": ["deal.manage", "quote.build", "quote.edit_pricing", "quote.send"],
  "iat": 1792000000,
  "exp": 1792000060,
  "jti": "5c4b6f2e-3b0e-4d4e-9f5a-9c2a6a1f0a11"
}
```

## Передача

1. Пользователь нажимает переключатель в шапке. CRM показывает его, только если `platform_access` пользователя
   содержит `erp` (см. «Доступ»); ERP — только у пользователя с сопоставлением `CrmUserMapping`, то есть
   провижиненного из CRM. Флаг `PLATFORM_SSO_ENABLED` должен быть включён на стороне, где нажата кнопка.
2. Исходная система выдаёт токен (`POST /api/v1/auth/sso/token` в ERP; аналог в CRM) и перенаправляет
   браузер на точку приёма: `https://erp.railtech.uz/sso/exchange#token=<jwt>` (фрагмент, не query:
   токен не попадает в логи прокси).
3. SPA приёмника читает фрагмент и вызывает `POST /api/v1/auth/sso/exchange {token}`.

## Проверка приёмником (по порядку)

Отказы по пп. 1–4 → 401; отказ по п. 5 → 403.

1. Подпись HS256 секретом `PLATFORM_SSO_SECRET` (оба активных значения).
2. `aud` равен собственному имени системы.
3. `exp` не прошёл; допуск часов ≤ 5 с. Срок жизни строго ограничен: **`exp − iat ≤ 60`** (с тем же допуском
   5 с, т.е. не больше 65 с) — токен с большим сроком отклоняется, даже если подпись верна.
4. `jti` не встречался: приёмник хранит использованные `jti` 10 минут (Redis / таблица).
5. Пользователь найден **только по `sub`** (ERP: `CrmUserMapping.crm_user_id`; CRM: `users.id`) и активен, иначе
   403 `USER_NOT_PROVISIONED` (неактивен — 403 `USER_INACTIVE`). Поиска по e-mail нет; обмен **не создаёт**
   пользователей и не привязывает существующих. Из токена обновляются только `email` и `name`; `role` и
   `permissions` не применяются при обмене — они приходят только провижинингом
   (`POST /api/integration/v1/users/provision`), `is_superuser` обмен не меняет.
6. Выдаётся собственная сессия приёмника; в аудит пишется `sso.exchange` с `iss`, `sub`, `jti`, IP.

Выдача токена (`POST /api/v1/auth/sso/token`): `sub` — только сопоставление сотрудника с `crm_user_id`
(ERP: `CrmUserMapping`); нет сопоставления → 403 `USER_NOT_PROVISIONED`, запасного значения (`user.pk`) нет.
CRM выдаёт токен только при `erp` в `platform_access` (иначе 403, `details.reason = platform_access_denied`).

Формат ошибки 403 по п. 5 у CRM — `details.reason = user_not_provisioned` (подкод `Reason.USER_NOT_PROVISIONED`,
ADR-0017), у ERP — `{"detail": "USER_NOT_PROVISIONED"}`; неактивный — `user_inactive` / `USER_INACTIVE`.

## Токен сотрудника для EDS

Решение лида L-C1-1 (волна 12, runbook [`wave12-eds-c1.md`](../runbooks/wave12-eds-c1.md) §2.2; контракт —
`packages/contracts/openapi/eds.yaml`). У EDS нет своей формы входа и внешнего маршрута: сотрудник приходит только через BFF
Платформы, BFF получает токен у CRM и обменивает его в EDS. Реализация: CRM — задача E4, EDS — E2.

**Выдача (CRM).** Тот же JWT HS256 тем же `POST /api/v1/auth/sso/token` с телом `{"aud": "eds"}` (тело без `aud` или
`{"aud": "erp"}` — токен для ERP, как раньше; совместимо). Claims: `iss = crm`, `aud = eds`, `sub` — `crm_user_id` строкой,
`email`, `name`, `iat`, `exp = iat + 60`, `jti` (UUID v4); `permissions` — коды `permissions.eds` сотрудника, **справочно**
(EDS их не применяет). Секрет — `PLATFORM_SSO_SECRET` (ротация — два активных значения). Токен выдаётся только активному
сотруднику с непустым `permissions.eds` (их CRM вычисляет из ролей Платформы по каталогу `platform-rbac.yaml`,
`backend.eds`), иначе 403, `details.reason = eds_access_denied`. Нет поля `permissions` или `permissions.eds` в снимке
`identity.user.*` (CRM до задачи E4 публикует без него) или список пуст — доступа к EDS нет.

**Обмен (EDS).** `POST /api/v1/auth/sso/exchange {"token": "<jwt>"}` → 200 `{"access_token", "token_type": "bearer",
"expires_in": 900}` — собственный токен доступа EDS (HS256, секрет `EDS_ACCESS_SECRET`, срок 15 минут, `iss = eds`,
`aud = eds-api` — не `eds`, чтобы токен сотрудника CRM и токен доступа EDS не подменяли друг друга ни при какой ошибке
конфигурации секретов; `sub = crm_user_id`). API EDS принимает только `aud = eds-api`, обмен — только `aud = eds`.
Refresh нет: истёк — BFF берёт у CRM новый токен сотрудника и обменивает снова. Проверки — по порядку
раздела «Проверка приёмником»: подпись (оба значения `PLATFORM_SSO_SECRET`), `iss = crm` и `aud = eds`, срок (`exp − iat ≤ 60`, допуск 5 с —
не больше 65 с), одноразовый `jti` (таблица в базе `eds`, 10 минут) — отказ 401 `INVALID_SSO_TOKEN` с `details.reason`;
сотрудник — **только по `sub`** в проекции сотрудников EDS (из `identity.user.*`): нет — 403 `USER_NOT_PROVISIONED`,
`is_active = false` — 403 `USER_INACTIVE`. Обмен сотрудников не создаёт и прав не меняет; в журнал EDS — `sso.exchange`.

**Каждый запрос.** `Authorization: Bearer <токен доступа EDS>`; право проверяется по проекции **на момент запроса** (коды
`x-rt-permissions` операции в `eds.yaml`). Отзыв роли (`identity.user.updated` с новым `permissions.eds`) и отключение
(`identity.user.deactivated`) действуют сразу, не дожидаясь срока токена доступа.

| | ERP | EDS |
|---|---|---|
| `aud` | `erp` | `eds` |
| Права | провижининг REST (`POST /api/integration/v1/users/provision`) | проекция из событий `identity.user.*` (`user.permissions.eds`) |
| Условие выдачи в CRM | `erp` в `platform_access` | непустой `permissions.eds` |
| Сессия приёмника | своя сессия ERP (access 30 минут + refresh) | токен доступа EDS 15 минут, без refresh |

## Доступ (`platform_access`)

Источник истины — CRM: `users.platform_access` — список систем, куда пользователю можно (`["crm"]` по умолчанию,
`["crm","erp"]` — доступ к ERP выдан админом в консоли «Пользователи»). ERP о доступе узнаёт только провижинингом
и отзывом (очередь Procrastinate на стороне CRM, ошибки ERP — в центре внешних сервисов, ADR-0024):

| Событие в CRM | Задача | Вызов ERP |
|---|---|---|
| выдан доступ к ERP; у пользователя с доступом изменились роли, роли ERP (`erp_role_codes`) или имя (смена почты провижининг не запускает) | `erp_provision_user` | `POST /api/integration/v1/users/provision` (идемпотентно по `crm_user_id`, повторы) |
| доступ снят; пользователь с доступом деактивирован | `erp_revoke_sessions` | `DELETE /api/integration/v1/users/{crm_user_id}/sessions` |

Аудит: CRM — `platform_access.granted` / `platform_access.revoked`; ERP — `sso.exchange`, `sso.revoke`.

## Роли ERP из CRM (`role_codes`, FIX-63)

Админ CRM выбирает пользователю с доступом к ERP системные роли бэк-офиса («Расчёт», «Каталог и закупки», «Исполнение и
логистика», «Финансы», «Руководитель», «Наблюдатель»; `SystemRoleCode`). Выбор хранится в `users.erp_role_codes` и уходит
в провижининг как `role_codes` (поле необязательное и терпимое: старый ERP его игнорирует, старый CRM его не шлёт, и тогда
ERP системные роли не трогает). ERP добавляет пришедшие роли и помечает их «выдана из CRM»; при следующем провижининге
снимает только помеченные, которых в `role_codes` больше нет. Роль, уже назначенная в ERP вручную, не помечается и CRM её
не снимает; роль «CRM Sync: <e-mail>» (права по карте ниже) живёт отдельно. Отзыв доступа снимает и помеченные роли.
Для `role: admin` `role_codes` игнорируется (суперпользователь имеет все права).

## Карта прав CRM → ERP

Роль CRM определяет `role` и `permissions` провижининга и claim `permissions`; коды — только из каталога ERP
(`ErpPermission`, 22 кода). Карта живёт в CRM (`app/domain/erp_permissions.py`), тест проверяет, что каждый код есть в каталоге.

| Роль CRM | `role` в ERP | `permissions` |
|---|---|---|
| `admin` | `admin` (суперпользователь ERP) | весь каталог (ERP игнорирует) |
| `manager` | `backoffice` | `deal.manage`, `quote.build`, `quote.edit_pricing`, `quote.send` |
| `viewer` | `backoffice` | — (только просмотр) |

Несколько ролей у одного человека — объединение; `admin` перекрывает остальные. Себестоимость и маржа
(`quote.view_cost_margin`), финансы, договоры, настройки и команда менеджеру CRM не выдаются: расширять права
может только админ ERP ролью в «Настройках → Команда» (но не CRM).

Коллизия e-mail при провижининге: если e-mail занят пользователем ERP, у которого другой `crm_user_id` или нет
сопоставления, `POST /api/integration/v1/users/provision` отвечает 409 `EMAIL_CONFLICT`, пользователь не
переписывается.

## Отзыв

Снятие доступа в CRM → `DELETE /api/integration/v1/users/{crm_user_id}/sessions` → ERP отзывает **всё, чем
пользователь входит**: refresh-токены (чёрный список), уже выданные access-токены (версия токенов пользователя
растёт — прежний access отвечает 401, а не живёт до конца 30 минут) и сам вход (`is_active=false`, чтобы не
вернуться по локальному паролю). Запись в аудит ERP — `sso.revoke`. Повторная выдача доступа — новый провижининг,
он включает пользователя. Клиенты (Cabinet) SSO не используют: их вход — Telegram `initData` и magic-link.
