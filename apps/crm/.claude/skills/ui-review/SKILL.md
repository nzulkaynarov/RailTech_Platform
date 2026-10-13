---
name: ui-review
description: Проверить интерфейс на запущенном стенде глазами и axe — скриншоты каждой роли на 1440 и 390 px, нарушения WCAG, горизонтальная прокрутка, сырые ключи в title, ошибки консоли и 4xx; обязательна после любой правки UI.
---

# UI-ревью на стенде

Тест в jsdom не видит контраст, переполнение шапки на телефоне и сырые ключи в `document.title`. Поэтому любая правка экрана проверяется на стенде: `frontend/scripts/ui-review.mjs` (Playwright + `@axe-core/playwright`). Гейт дизайн-аудита: **0 нарушений axe** на всех экранах × роли × оба размера, без горизонтальной прокрутки (`docs/audit/2026-10-11-design-audit.md`).

## Шаги

1. Стенд запущен (`make ps`, `/ready` 200), на нём код ветки (api/web перечитывают сами; worker/MCP — скилл `stand-verify`). Нужны учётки трёх ролей; пароли — из `.env`/сессии, не из репозитория и не в чат.
2. Запуск из `frontend/` (аргументы с `?` — в кавычках):
   ```bash
   REVIEW_EMAIL=… REVIEW_PASSWORD=… node scripts/ui-review.mjs manager desktop /inbox /leads /leads/1
   REVIEW_EMAIL=… REVIEW_PASSWORD=… node scripts/ui-review.mjs manager mobile /inbox /leads/1
   REVIEW_EMAIL=… REVIEW_PASSWORD=… node scripts/ui-review.mjs admin desktop "/settings?section=texts" /users /audit
   ```
   Нет chromium Playwright — `REVIEW_BROWSER=chrome`. Другой стенд — `BASE_URL=http://localhost:8080`.
3. Прочитай `review-out/summary.json` и **посмотри скриншоты** (Read png) — критично, как владелец продукта: сырые коды, обрезанные подписи, три строки в шапке телефона, кнопка «Забрать» у чужого лида, цвет без смысла, тексты не по словарю Q-015.
4. Нарушения axe чини в коде, не в исключениях; контраст — токенами темы (`app/theme.ts`, `styles/a11y.css`; в режиме `cssVar` палитра antd не переопределяется — цвета тегов через `--crm-tag-*`).
5. Для изменений вне экрана (клавиши, SSE, переходы) допиши сценарий в скрипт-однодневку в scratchpad, а повторяемое — в `frontend/e2e/*.spec.ts`.
6. Результаты (экраны × роли × размеры, нарушений до/после) — в «Как проверено» PR; `review-out/` в git не попадает.
