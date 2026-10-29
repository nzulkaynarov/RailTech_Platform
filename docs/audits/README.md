# Аудиты и отчёты гейтов — индекс
Статус: действует (индекс) · Владелец: архитектор · Обновлено: 2026-10-29

Здесь — **снимки на дату**: оценка состояния (аудит) и отчёт о прогоне гейта или сценария глазами. Снимок не правится
задним числом; что из него сделано или осталось — в [`../BACKLOG.md`](../BACKLOG.md) и [`../PROGRESS.md`](../PROGRESS.md).
Внешние аналоги, эталоны и рынок — не сюда, а в [`../research/`](../research/README.md). Строки «Статус» у снимков нет:
дата и предмет — в имени файла и заголовке.

## Аудиты ансамбля

| Дата | Снимок |
|---|---|
| 2026-10-18 | [`2026-10-18-main-e0f089e.md`](2026-10-18-main-e0f089e.md) — аудит лида разработки, `main` @ e0f089e |
| 2026-10-21 | [`2026-10-21-business-process.md`](2026-10-21-business-process.md) — бизнес-логика: как есть, эталон, целевой процесс; материалы — [`../research/2026-10-21-business-audit/`](../research/README.md) |

## Отчёты гейтов и прогонов глазами

Новый отчёт гейта кладётся сюда (имя — `<волна или этап>_gate_report.md`), скрипты и выводы прогона — в `qa/<прогон>/`,
снимки экранов — в `../screens/<задача>/`.

| Гейт / прогон | Отчёт | Скрипты |
|---|---|---|
| M1 повторно (FIX-50) | [`m1_qa_02_report.md`](m1_qa_02_report.md) | — |
| M2: Cabinet, веб и Mini App | [`m2_qa_01_report.md`](m2_qa_01_report.md) | — |
| M2 против настоящего ERP (FIX-51) | [`m2_qa_02_report.md`](m2_qa_02_report.md) | — |
| Платформа P1 (волна 8) | [`plt_p1_gate_report.md`](plt_p1_gate_report.md) | [`qa/plt-p1/`](qa/plt-p1/) |
| Роль-универсал (волна 9) | [`r3_roles_report.md`](r3_roles_report.md) | [`qa/r3-roles/`](qa/r3-roles/) |
| Этап B (волна 11b) | [`wave11b_gate_b_report.md`](wave11b_gate_b_report.md) | — |
| Этап B повторно (волна 11c) | [`wave11c_gate_report.md`](wave11c_gate_report.md) | [`qa/w11c-gate/`](qa/w11c-gate/) |
| Этап C1, сервис EDS (волна 12) | [`c1_eds_gate_report.md`](c1_eds_gate_report.md) | [`qa/c1-eds/`](qa/c1-eds/) |
| Этап C2a, паритет Admin (волна 13) | [`c2a_admin_gate_report.md`](c2a_admin_gate_report.md) | [`qa/w13-a7-gate/`](qa/w13-a7-gate/) |
| Замер шины A/B (волна 13c, F7) | [`wave13c_bus_measure.md`](wave13c_bus_measure.md) | [`qa/w13c-f7/`](qa/w13c-f7/) |
| Волна 15 «Честный интерфейс» | [`wave15_gate_report.md`](wave15_gate_report.md) | [`qa/w15-h9-gate/`](qa/w15-h9-gate/) |

## Аудиты CRM (до монорепозитория и в первые дни)

| Дата | Снимок |
|---|---|
| 2026-10-09 | [`crm/2026-10-09-product-audit.md`](crm/2026-10-09-product-audit.md) — продуктовый аудит CRM |
| 2026-10-11 | [`crm/2026-10-11-design-audit.md`](crm/2026-10-11-design-audit.md) — дизайн-аудит CRM и бота; приложения — [`crm/2026-10-11-design/`](crm/2026-10-11-design/) |
| 2026-10-11 | [`crm/2026-10-11-benchmark-business-os.md`](crm/2026-10-11-benchmark-business-os.md) — бенчмарк «Business OS», экран «Коммуникации» |
| 2026-10-12 | [`crm/2026-10-12-full-audit.md`](crm/2026-10-12-full-audit.md) — полный аудит: продукт и техлид |
| 2026-10-12 | [`crm/2026-10-12-admin-console-scope.md`](crm/2026-10-12-admin-console-scope.md) — админка без терминала |
| 2026-10-12 | [`crm/2026-10-12-refine-antd-capabilities.md`](crm/2026-10-12-refine-antd-capabilities.md) — возможности Refine и Ant Design |
| 2026-10-12 | [`crm/2026-10-12-ux-layout-proposal.md`](crm/2026-10-12-ux-layout-proposal.md) — эргономика CRM и дашборд |
| 2026-10-12 | [`crm/2026-10-12-skills-audit.md`](crm/2026-10-12-skills-audit.md) — скиллы агента |

Фронтенд CRM заморожен и отключается задачей P6 волны 18a — аудиты CRM интересны как история решений, а не как задачи.
