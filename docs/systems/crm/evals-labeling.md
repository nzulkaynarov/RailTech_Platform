# Разметка диалогов → golden (PLAN Фаза 7, задача 6)
Статус: действует · Владелец: лид · Обновлено: 2026-10-23

Еженедельно (пилот — Фаза 9) выгружаем 20 случайных диалогов, менеджеры размечают,
спорные и показательные становятся golden-кейсами.

## 1. Выгрузка

```bash
scripts/sample_dialogs.py            # dev; --prod для prod-стенда
# → reports/labeling/YYYY-MM-DD.yaml (в git не попадает)
```

Телефоны, e-mail, ИНН и длинные номера заменены на `[number]` / `[email]`.
Ссылка `crm_url` ведёт на карточку лида — полная история доступна в CRM по правам.

## 2. Формат

```yaml
- lead_id: 123
  crm_url: https://crm.railtech.uz/leads/123
  language: ru
  stage: handoff
  escalation_reasons: [hot_lead]
  dialog:
    - {role: lead, text: "Сколько стоит подключение [number] касс?"}
    - {role: bot, text: "…", action: answer}
  label:
    handoff: ""     # ok | unnecessary (зря передал) | missed (надо было передать)
    tone: ""        # ok | bad
    facts: ""       # ok | wrong | invented
    comment: ""     # свободный текст: что должно было быть
    golden: false   # true — сделать golden-кейс
```

Правила разметки:
- `handoff: missed` — клиент был горячим/просил человека/злился, а эскалации не было.
- `handoff: unnecessary` — эскалация, которую менеджер счёл лишней.
- `facts: invented` — в ответе есть факт или число, которого нет в базе знаний (самое важное).
- `golden: true` ставим на любой `missed`, `invented`, `wrong` и на 1–2 типичных удачных диалога.

## 3. Перенос в golden

Для каждого `golden: true` — скилл `eval-case` (`.claude/skills/eval-case`):
1. Категория по `SPEC §12` (`kb_answer`, `not_in_kb`, `human_request`, `negative`, …).
2. `message` — последнее сообщение лида, `history` — предыдущие ходы (уже без PII).
3. `expect` — из разметки: `actions` (`escalate` для `missed`), `must_not_include` для
   выдуманного факта, `must_include_any` для правильного.
4. `make check` (схема golden) → PR → job `eval-gate` прогонит новый кейс.

Метрики пилота (docs/systems/crm/BUSINESS.md §10): доля `missed` и `invented` по неделям — в отчёт пилота.
