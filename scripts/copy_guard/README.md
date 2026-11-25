# Проверка текстов интерфейса (copy guard)

Только стандартная библиотека Python 3.11+. Запуск с `-I`.

| Файл | Что делает |
|---|---|
| `extract.py <repo> <out.jsonl>` | Собирает все строки, которые видит человек: каталоги i18n Платформы и кабинета, строки в `.ts/.tsx` вне каталога, Python-тексты BFF, ERP, CRM, EDS (без docstring, логов, regex, `help_text`/`description`, тестов, миграций, сидов, промптов), шаблоны писем и PDF (ERP, CRM), переводы ERP из `django.po`, справку `docs/kb/help`. У строки: приложение, поверхность (ui, письмо, бот, PDF, уведомление, статус, ошибка, справка, admin-model), аудитория (сотрудник, клиент, партнёр), язык, файл:строка, ключ. |
| `copy_guard.py audit <strings.jsonl> <findings.csv> --repo <repo> [--curated curated.tsv]` | Проверяет строки по правилам и пишет таблицу находок. |
| `copy_guard.py check <repo> --app <app> --baseline <file.json> [--update]` | Режим CI: красный, если у приложения появилась находка не из списка исключений, или если исправленная находка ещё в списке (список только сокращается — как `ui-guards/baseline.json`). |
| `wordlists/*.tsv` | Словари: одна таблица — один класс. Колонки: regex (без учёта регистра; `(?-i:…)` — с учётом), важность H/M/L, языки, аудитории, предложение, основание. |
| `curated.tsv` | Ручные формулировки «было → стало» для главных находок; подставляются в `findings.csv`. |

Классы в коде (без словаря): `uz-old` (через `scripts/uz_new_alphabet.py` репозитория), `mixed` (латиница в ru,
кириллица в en/uz), `code` (ключи, `snake_case`, `UPPER_CODES`, `#id`, `{{status}}`), `retelling` (длинный текст в
подписи: больше 220 знаков или три предложения длиннее 140), `untranslated`.

Где системные слова и бренды разрешены (`ctx=settings`): Настройки · Подключения, журнал шины и аудита, состояние
системы (`integrations.json`, `bus.json`, `audit.json`, ключи с `settings/setup/integrations/channels/bus/audit`,
CRM `domain/external_*`, `system_status`). Должности не проверяются в каталоге ролей и в «Что нового»
(`docs/kb/help/changelog`). Юридические тексты (договор партнёра, оферта, политика, согласие) получают важность L и
пометку D10 — их правит держатель зоны «Право».

## Как стать проверкой в CI

Задание `gitleaks` в `ci.yml` и `scripts/ci_local.sh` уже выполняет `python3 -m unittest discover -s scripts/tests`
(только stdlib). Поэтому workflow менять не нужно:

```
scripts/copy_guard/extract.py, copy_guard.py, wordlists/*.tsv      # перенести отсюда
scripts/copy_guard/baseline/<app>.json                              # copy_guard.py check … --update
scripts/tests/test_copy_guard_<app>.py                              # unittest: guard(repo, "<app>", baseline) == 0
```

Каждый PR чистки приложения добавляет свой `test_copy_guard_<app>.py` и базовый список, уже сокращённый на то, что
исправлено в этом PR.
