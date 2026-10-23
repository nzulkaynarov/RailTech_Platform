# Токены дизайна — `packages/ui-tokens` (версия 0.2.0)
Статус: действует · Владелец: лид · Обновлено: 2026-10-23

Один файл `tokens.json` задаёт цвета, шрифт, радиусы и плотность для всех фронтендов ансамбля
(ансамбль выглядит одной семьёй; унификация компонентов — не цель; темы и семантические токены — ADR-0018). Версия 0.2.0 — токены
SPEC-v3 §5.2 (`docs/architecture/platform-frontend.md` §3); значения 0.1.0 были из темы CRM (дизайн-аудит 2026-10-11).
Контраст WCAG 2.1 AA ≥ 4.5:1 для пар «текст / фон» проверяют `contrast.test.mjs` (здесь) и
`apps/crm/frontend/src/app/theme.test.ts`.

| Файл | Кто читает |
|---|---|
| `tokens.json` | **источник**, правится только он |
| `dist/antd.ts` → копия `apps/crm/frontend/src/app/tokens.generated.ts` | AntD-тема CRM и Платформы: `RT_TOKENS` (`theme.token`), `RT_TAG_TEXT`, `RT_TABLE_CELL_PADDING` (плотность таблиц CRM), `RT_COMPONENTS` (`theme.components` Платформы; CRM не подключает). Копия нужна, потому что фронтенд CRM собирается в контейнере без доступа к `packages/`; Платформа (`apps/platform/web`) возьмёт файл тем же способом (INF-P0-3) |
| `dist/shadcn.css` | ERP и Cabinet — переменные shadcn (`--primary`, `--destructive`, `--success`…) и `@theme inline` для Tailwind 4. Копии `apps/cabinet/src/styles/tokens.generated.css` и `apps/erp/frontend/src/styles/tokens.generated.css` (образы собираются без `packages/`) |
| `dist/tokens.css` | CSS-переменные `--rt-*` для любого другого потребителя (письма, PDF-шаблоны) |

```
make tokens                        # из корня: регенерировать всё (dist/ и копии в apps/crm, apps/cabinet, apps/erp)
make -C packages/ui-tokens test    # контраст пар «текст / фон» (node --test, без зависимостей)
make -C packages/ui-tokens check   # CI: контраст + сгенерированное совпадает с закоммиченным
```

Правило: меняется `tokens.json` → в том же PR перегенерированы `dist/` и копии `tokens.generated.*`, тест контраста пакета
и CRM зелёный. Тёмная тема — не здесь: приложения задают `.dark` поверх (решение при появлении потребности).

## Что нового в 0.2.0

- `color.primary` — `#1668dc` (hover `#0958d9`, active `#003eb3`, bg `#e6f4ff`, text `#0958d9`). Белый на `#1668dc` — 5.19:1.
  **Отступ от таблицы SPEC-v3 §5.2** (там hover `#1677ff` — 4.10:1 с белым текстом): по критерию §11.2 п. 6, решение
  архитектора 2026-10-22. В shadcn-выходе добавлена переменная `--primary-hover` (`bg-primary-hover`); компоненты с
  `bg-primary/90` (4.36:1) её пока не используют — Cabinet перейдёт при CAB-03.
- У статусов `primary`, `info`, `success`, `warning`, `error` появилось поле **`text`** — цвет текста с контрастом ≥ 4.5:1 на
  белом и на своём светлом фоне; `default` — затравочный цвет (`#52c41a`, `#faad14`, `#ff4d4f`) для заливок и границ:
  **в текст `default` не идёт**. В теме AntD это `colorSuccessText`, `colorWarningText`, `colorErrorText`, `colorPrimaryText`;
  в shadcn `--success`, `--warning`, `--destructive` = `text` (они служат и цветом текста, и заливкой кнопок с белым текстом).
  **В AntD-выходе статусные `colorError`, `colorWarning`, `colorSuccess` = `text`** (AntD читает их и как текст — `Form`
  explain, `Tag`, danger-кнопки outlined/text/link, `Menu` danger, — и как фон под белый текст — `Button danger`,
  `Badge count`, `Progress`); затравки доступны как `RT_STATUS_FILL` и `--rt-color-*-default` для графиков и заливок
  без текста (Q-INF-P0-2-2).
- Текст: `#1f1f1f` / `#595959` (secondary) / **`#6e6e6e`** (tertiary и placeholder). **Отступ от таблицы SPEC-v3 §5.2**
  (там tertiary `#767676`: 4.54:1 на белом, но 4.35 на `#fafafa` — label bordered `Descriptions`, 4.17 на `#f5f5f5`,
  4.06 на `#e6f4ff`): по критерию §11.2 п. 6, решение лида по принципу архитектора, как с hover. `#6e6e6e` даёт
  5.10 / 4.89 / 4.68 / 4.55:1 на `#ffffff` / `#fafafa` / `#f5f5f5` / `#e6f4ff`. `colorTextDescription` и shadcn
  `--muted-foreground` = `#595959`.
- Рамки `#d9d9d9` / разделители `#f0f0f0`; фон окна `#f5f5f5`, контейнер `#ffffff`; радиусы 4 / 6 / 8 / 12 (контролы 6, карточки 8).
- Теги: `RT_TAG_TEXT` дополнен `blue`, `gold`, `red`, `purple` (`#531dab`), `cyan` — `#006d75`.
- Ссылка при наведении и нажатии (`colorLinkHover`, `colorLinkActive`) = `primary.hover` / `primary.active` (текст ≥ 4.5:1).
- `RT_COMPONENTS` — компонентные токены Платформы (`Menu`, `Table`, `Card`, `Tabs`, `Badge`, `Layout`) из 03-frontend §3.
  Токены, которые AntD при `cssVar: true` не принимает на уровне компонента (глобальные алиасы: `borderRadiusSM`, `boxShadow`,
  `colorBorderSecondary`), сюда не входят — они заданы глобально в `RT_TOKENS`. `Tag` (высота 22, радиус 4, шрифт 12) и серый
  `Badge` (фон `#f0f0f0`, текст `#595959`) собирает `theme.ts` Платформы.

## Шрифт

Шрифт `Inter, -apple-system, "Segoe UI", Roboto, Arial, sans-serif` задан в `font.family`, **файлов шрифта в пакете нет**
(в `docs/history/platform/05-plan.md` «woff2 в пакете» отменено runbook'ом волны 7). Inter подключает само приложение пакетом
`@fontsource-variable/inter` (самостоятельный хостинг, CSP `font-src 'self'`, не Google Fonts): Платформа — INF-P0-3,
Cabinet — позже, CAB-03. Пока шрифт не подключён, стек падает на системный (`-apple-system`, `Segoe UI`, `Roboto`).
ERP и CRM шрифт не подключают (заморожены, ADR-0011).

## Тест контраста

`contrast.test.mjs` читает `tokens.json`, собранные `dist/shadcn.css` и `dist/antd.ts` (реальные пары компонентов AntD); пары «текст / фон» перечислены в массиве `pairs`
явно (новая пара в интерфейсе → строка в массиве). Пары ниже 4.5:1, которые фиксирует SPEC-v3 §5.2, вынесены в
`KNOWN_BELOW_AA` со ссылкой на вопрос в `docs/QUESTIONS.md` (Q-INF-P0-2-1): тест держит их в 3:1…4.5:1 и просит перенести в
основной список, когда пара начнёт проходить.
