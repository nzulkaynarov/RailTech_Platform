# Session handoff — «Документы 2.0» (полный цикл) — 2026-07-22

_Продолжение на другом компьютере. Всё смёржено в `main` и на проде `b2b.railtech.uz`. Открытых веток/PR по этому треку нет._

## TL;DR

Реализована и вычищена **станция документов** (весь раздел «Документы»): произвольные документы по шаблонам, редактор шаблонов, инвойс-DRAFT, реестр «Файлы», доставка письма контрагенту. Затем — адверсариальный аудит и 3 фикс-волны. **8 PR (#383–#390), все на проде, DoD пройден глазами по каждой волне.**

## Что на проде (по волнам)

### Спека A→D (`Docs/dev/specs/spec-documents-hub-2026-07-22.md`, УТВЕРЖДЕНА)

| PR | Волна | Суть |
|----|-------|------|
| #383 | A | Произвольные документы по шаблонам: модели `DocumentTemplate`/`GeneratedDocument`, SSTI-safe плейсхолдеры по белому списку, мастер «Создать документ», реестр «Прочие», жизненный цикл DRAFT→ISSUED→CANCELLED, PDF офф-тред |
| #384 | B | Секция «Настройки → Шаблоны документов»: редактор + каталог 13 плейсхолдеров (клик-вставка) + live-предпросмотр на демо-данных; эндпоинты `preview`/`placeholders` |
| #385 | C | Инвойс DRAFT-стадия: рождается DRAFT (не ISSUED), редактор срока/примечаний, «Выставить»/«Отменить»; авто-инвойс при выигрыше → DRAFT+уведомление |
| #386 | D | Реестр «Файлы» (DMS-лайт) на существующем `AttachmentViewSet`; клиент `listAllAttachments` обходит все страницы |

### Аудит + фиксы (`Docs/dev/specs/spec-documents-fixes-2026-07-22.md`, УТВЕРЖДЕНА)

Аудит: 3 адверсариальных агента (backend/frontend/benchmark-gap). CRITICAL не найдено; ядро безопасности повторно чистое.

| PR | Волна | Суть |
|----|-------|------|
| #388 | F1 | Корректность инвойс-lifecycle: (I-1) оплата отвергает DRAFT — устранён «зомби-инвойс»; (I-2) PATCH черновика гейтится стороной; (I-3) DRAFT скрыт от покупателя в queryset; (I-4) перевыставление после отмены; (I-5) 404 вместо 500; (III-3) `invoice_id` на договоре → кнопка «Создать»⇄«Открыть» |
| #389 | F2 | **Доставка письма**: публичная no-login ссылка `/public/documents/<token>/` (ISSUED-only, throttle), send-email, видимость покупателю read-only (бейдж «Получен»), мастер из карточки сделки, `?deal=` фильтр. **Ревью F2-3 нашло 2 MAJOR → закрыто:** hidden-competition (конкурент не видит чужой ISSUED) + email-релей (валидация `to` + throttle) |
| #390 | F3 | Гигиена: (III-1) удаление использованного шаблона → 400 `TEMPLATE_IN_USE`; (III-2) деактивированные шаблоны скрыты в мастере; (III-4) OtherDocuments/CompanyFiles на `ResponsiveDataTable`; (III-5) throttle preview; (III-6) `quote.build`-гейт на генерацию; (III-7) пакет мелочи |

## Ключевые архитектурные факты (для будущей работы)

- **Модели**: `crm/models/documents.py` — `DocumentTemplate` (company-scoped, `is_sample` для глобальных образцов), `GeneratedDocument` (снапшот `values`+`rendered_html`+`body_html_snapshot` — документ НЕ «плывёт»; public-token поля как у КП). Head миграций crm — **0070**.
- **Безопасность генерации** (`crm/services/document_placeholders.py`): плейсхолдеры по БЕЛОМУ СПИСКУ (не template-движок — SSTI-safe), значения HTML-экранируются, тело санитайзится stdlib-allowlist (nh3 — harden-forward). Ревью A4+F2-3 подтвердили чистым.
- **Публичная доставка**: паттерн повторяет КП (`crm/views/quotes/public.py`) — `crm/views/documents_public.py` `PublicDocumentView`, токен `secrets.token_urlsafe(32)` минтится на issue, gate только ISSUED+не-revoked+не-expired. `send_document_email` таска (`crm/tasks.py`) + шаблон `templates/emails/generated_document.*`.
- **Видимость (hidden-competition, ADR-0003)**: `party_visible_document_q` — покупатель видит любые ISSUED по своей сделке; routed-продавец видит ТОЛЬКО документы покупателя (`company_id=F("deal__company_id")`), никогда со-routed конкурента. Мутации owner-гейтятся (`_user_owns_document`).
- **Инвойс DRAFT**: `generate_invoice_from_contract` создаёт DRAFT (идемпотентность исключает CANCELLED — перевыставление); `invoice_lifecycle.py` (issue/cancel/update_draft, seller-гейт); `record_payment` отвергает DRAFT.
- **Throttle-scopes** (settings.py): `public_document` 30/min, `document_send_email` 20/hour, `document_preview` 60/min.
- **Гейт генерации**: `member_has_permission(user, company, "quote.build")` (OWNER проходит по legacy-fallback).

## Демо для eyes-on (dev)

- Продавец-OWNER: `solo.seller@railtech.uz` / `Demo1234!` (company 28, `document.generate=True`). deal 6 = соло CT-2026-00003 (buyer `company=None` → уведомления/публичная видимость покупателю не применяются).
- Локально Docker Hub периодически таймаутит на pull node/nginx → фронт-контейнер не пересобрать; проход глазами делать через `cd frontend && npm run dev` (vite :5174 проксирует `/api` на :8000). После правок navigation/pagination/вьюх — **хард-релоад** (dev HMR не подхватывает nav; Daphne — `docker compose restart backend`).

## Отложено (P3, НЕ начато — по решению владельца)

- **RequestDetailPage не грузится для соло-сделки** продавца (buyer=None) → блок «Документы сделки»/«Создать из сделки» там не виден; продавец создаёт из мастера реестра (не тупик). `deal-quote` (КП-билдер) блока не имеет — возможный P3-мониторинг.
- Дублирование КП + ручной инвойс «с нуля» (нужны новые бэкенд-эндпоинты).
- Letterhead ISSUED-документа живой (не снапшот бренд-шапки) — частичная иммутабельность (тело снапшотится).
- MINOR-3 (revoke-public-link action) — отмена документа уже закрывает публичный доступ.
- upload из реестра «Файлы»; сквозной поиск по документам + «недавние» на дашборде; системная инвалидация дашборд-статов после billing-мутаций (общий долг billing).
- DOCX-шаблоны V2 (docxtpl+libreoffice — тяжело для VPS).

## Процессные уроки этой сессии

- Стековые фикс-волны мержил СВЕРХУ-ВНИЗ с ретаргетом на main (PRODUCT RULE 6). Параллельные агенты (backend+frontend) на одной ветке — норм, но агент с широким `git add` может подхватить чужие несохранённые правки (было в F1: frontend-агент захватил backend-код в свой коммит) — давал агентам инструкцию `git add` ТОЛЬКО свои файлы явными путями.
- Два агента упали по обрыву API (A1, F1-1) на этапе тестов — ядро успевали записать; дописывал тесты/верификацию сам, ловил реальные баги (escape `quote=`, стейл-инвалидация contracts).
- Каждую волну: агенты → интеграция (свод контракта + регенерация схемы) → адверсариальное ревью где риск → eyes-on глазами → PR → мерж → деплой → прод-проверка (health/бандл/маркеры + глазами).

## Состояние на момент handoff

`main` = **7eea1f9** (после #390). Все 8 PR на проде. Аудит закрыт. Открытых блокеров нет. Память: `project-spec-documents-hub-draft.md`, `project-documents-fixes-audit.md`.
