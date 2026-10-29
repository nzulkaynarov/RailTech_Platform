---
name: ui-evidence
description: Доказательство UI для PR (DoD «сценарий глазами») — снимки 1440 и 390 px и axe 0 нарушений в docs/screens/<задача>/ через Playwright-спеки Платформы на MSW, dev-сервер Cabinet или свой стенд compose. Обязательно после любой правки экрана Платформы или Cabinet.
---

# Снимки и axe для PR

Правила — ORCHESTRATOR §3 п. 9 и §7 п. 5: снимки 1440 и 390 (GIF — где важна динамика) и результат axe лежат в
`docs/screens/<задача>/` и перечислены в описании PR; снимок только в чате артефактом не считается. Без токенов, ссылок
входа и персональных данных. Старый фронтенд CRM — скилл `apps/crm/.claude/skills/ui-review`.

## Платформа (MSW, без бэкенда) — основной путь

1. Спек экрана — `apps/platform/web/e2e/<экран>.spec.ts`; нет — создай по образцу соседнего (`admin-no-hop.spec.ts`,
   `first-run.spec.ts`): обе ширины (`const WIDTHS = [1440, 390]`, `page.setViewportSize`), axe через `@axe-core/playwright`
   (функция `expectNoViolations` спека, WCAG 2.1 AA), снимок — только если задан `E2E_SCREENSHOT_DIR`:
   ```ts
   const dir = process.env["E2E_SCREENSHOT_DIR"];
   if (dir) await page.screenshot({ path: `${dir}/<экран>-${String(width)}.png`, fullPage: true });
   ```
2. Прогон только своего спека:
   ```bash
   cd apps/platform/web
   E2E_SCREENSHOT_DIR="$(git rev-parse --show-toplevel)/docs/screens/<задача>" pnpm exec playwright test e2e/<экран>.spec.ts
   ```
   Первый раз — `pnpm exec playwright install chromium`. Журнал axe для PR — как в `erp-catalog.spec.ts`
   (`E2E_AXE_LOG=<файл>`), если спек его пишет; иначе итог axe — строкой в описании PR.
3. Посмотри снимки сам (Read по png): обрезки, наезды, горизонтальная прокрутка на 390, сырые ключи i18n, пустые состояния.

## Cabinet

`make -C apps/cabinet dev` (мок портального API, :5175), затем снимки Playwright из пакета Платформы:
`cd apps/platform/web && pnpm exec playwright screenshot --viewport-size "390, 844" --full-page http://localhost:5175/<путь>
"$(git rev-parse --show-toplevel)/docs/screens/<задача>/<экран>-390.png"` (и `"1440, 900"`). axe Cabinet — в его vitest
(`make check-cabinet`).

## Сквозной сценарий на реальных бэкендах

Свой стенд `docker compose -p rt-<задача>` со своим `.env` и `HTTP_PORT` не 8088 (стенд владельца не трогать); образцы —
`docs/runbooks/*_gate_report.md`. После — `docker compose -p rt-<задача> down -v`. Это работа агента `qa-eyes`.

## В PR

Раздел «Как проверить глазами»: шаги, роль, ожидаемое; список файлов `docs/screens/<задача>/*` и итог axe.
