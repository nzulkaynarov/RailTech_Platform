# packages/ui-tokens — общие токены дизайна

Один файл `tokens.json` задаёт цвета, шрифт, радиусы и плотность для всех трёх фронтендов
(ARCHITECTURE §3: ансамбль выглядит одной семьёй; унификация компонентов — не цель). Значения — из темы
CRM (дизайн-аудит 2026-10-11, контраст WCAG 2.1 AA ≥ 4.5:1, проверяется `apps/crm/frontend/src/app/theme.test.ts`).

| Файл | Кто читает |
|---|---|
| `tokens.json` | **источник**, правится только он |
| `dist/antd.ts` → копия `apps/crm/frontend/src/app/tokens.generated.ts` | AntD-тема CRM (`theme.ts` импортирует `RT_TOKENS`, `RT_TAG_TEXT`, `RT_TABLE_CELL_PADDING`). Копия нужна, потому что фронтенд CRM собирается в контейнере без доступа к `packages/` |
| `dist/shadcn.css` | ERP и Cabinet — переменные shadcn (`--primary`, `--destructive`, `--success`…) и `@theme inline` для Tailwind 4. Cabinet подключает копию `apps/cabinet/src/styles/tokens.generated.css` (`@import "tailwindcss"; @import "./styles/tokens.generated.css";`) — образ `cabinet-web` собирается без `packages/` (M2-CAB-01) |
| `dist/tokens.css` | CSS-переменные `--rt-*` для любого другого потребителя (письма, PDF-шаблоны) |

```
make tokens                        # из корня: регенерировать всё (dist/ и копии в apps/crm, apps/cabinet)
make -C packages/ui-tokens check   # CI: сгенерированное совпадает с закоммиченным
```

Правило: меняется `tokens.json` → в том же PR перегенерированы `dist/` и `tokens.generated.ts`, тест контраста CRM зелёный.
Тёмная тема — не здесь: приложения задают `.dark` поверх (решение при появлении потребности).
