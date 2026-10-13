# SSO-токен сотрудника (CRM ↔ ERP)

Источник: `docs/CONTRACTS.md` §6, ADR-0003. Версия 0 (M0-INF-02). Реализация: ERP — M3-ERP-04, CRM — M3-CRM-06.

## Формат

JWT **HS256**, общий секрет `PLATFORM_SSO_SECRET` (секрет окружения обеих систем; ротация — два
активных значения, принимающая сторона проверяет оба).

| Claim | Тип | Значение |
|---|---|---|
| `iss` | string | `crm` или `erp` — кто выдал |
| `aud` | string | `erp` или `crm` — целевая система (приёмник отклоняет чужой `aud`) |
| `sub` | string | `crm_user_id` как строка — идентификатор сотрудника в CRM (источник истины по людям) |
| `email` | string | e-mail сотрудника |
| `name` | string | отображаемое имя |
| `role` | string | `admin` \| `manager` \| `viewer` (роль CRM); `admin` = суперпользователь ERP |
| `permissions` | string[] | права бэк-офиса `quote.*`, `contract.*`, `finance.*`, `catalog.*`, `supply.*` (для `aud=erp`) |
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
  "permissions": ["quote.view", "quote.edit", "quote.view_cost_margin"],
  "iat": 1792000000,
  "exp": 1792000060,
  "jti": "5c4b6f2e-3b0e-4d4e-9f5a-9c2a6a1f0a11"
}
```

## Передача

1. Пользователь нажимает переключатель в шапке (показывается, если `platform_access` в CRM содержит обе
   системы; ERP узнаёт об этом при провижининге `POST /api/integration/v1/users/provision`).
2. Исходная система выдаёт токен (`POST /api/v1/auth/sso/token` в ERP; аналог в CRM) и перенаправляет
   браузер на точку приёма: `https://erp.railtech.uz/sso/exchange#token=<jwt>` (фрагмент, не query:
   токен не попадает в логи прокси).
3. SPA приёмника читает фрагмент и вызывает `POST /api/v1/auth/sso/exchange {token}`.

## Проверка приёмником (по порядку, любой отказ → 401)

1. Подпись HS256 секретом `PLATFORM_SSO_SECRET` (оба активных значения).
2. `aud` равен собственному имени системы.
3. `exp` не прошёл; допуск часов ≤ 5 с.
4. `jti` не встречался: приёмник хранит использованные `jti` 10 минут (Redis / таблица).
5. Пользователь найден по `sub` (ERP: `crm_user_id`) и активен — иначе 403; поля `email`, `name`,
   `role`, `permissions` обновляются из токена.
6. Выдаётся собственная сессия приёмника; в аудит пишется `sso.exchange` с `iss`, `sub`, `jti`, IP.

## Отзыв

Снятие доступа в CRM → `DELETE /api/integration/v1/users/{crm_user_id}/sessions` → ERP отзывает все
сессии пользователя. Клиенты (Cabinet) SSO не используют: их вход — Telegram `initData` и magic-link.
