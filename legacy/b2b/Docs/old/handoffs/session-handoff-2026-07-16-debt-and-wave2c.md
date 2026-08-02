# Session Handoff — 2026-07-16 — долговой аудит + КП волна 2 этап C + security-хвост

**База:** main @ `97bcfec` (после PR #332). Дерево чистое, открытых PR нет (кроме этого docs-PR), ветки/worktrees вычищены.
Кросс-машинный handoff: память `~/.claude` НЕ переезжает — этот документ = источник истины.
Предыдущие: `session-handoff-2026-07-15-quote-builder-wave2.md`, `-07-14-quote-builder.md`.

## TL;DR

Провёл полный долговой аудит (2 Opus-агента: верификация по коду + сбор по докам) → реестр долгов. Затем отгрузил на прод **7 PR (#326–#332)** двумя параллельными волнами: docs-правда + мёртвый код, Phase-4 security хвост (3 PR), КП этап C (Excel-paste + typeahead), AI спенд-кап. Всё с адверсариальным ревью до мержа. **КП-конструктор волна 2 ПОЛНОСТЬЮ завершена** (этапы A+B+C). Остаток — owner-policy решения и волна 3 (по спросу).

## Отгружено (PR #326–#332, на проде, деплои проверены)

| PR | Суть |
|----|------|
| #326 | CLAUDE.md/ROADMAP-правда (Leads/Analytics/Clients ЖИВЫ — было ложно «cut»); удалены react-router-dom, supportApi.deleteTicket, accountsApi.getCompanyTypes |
| #327 | reset/setup-письма → Celery (async, не блокирует ASGI, гасит timing-side-channel); throttle-ключ = sha256(email) |
| #328 | Sentry `before_send` PII-скраббер (inn/phone/bank/token…); удалены мёртвые CORS/CSRF из .env.example |
| #330 | Публичный токен КП: TTL/revoke поля + миграция **crm/0060** + гейт 404/410; браузер по истёкшей ссылке видит человеческую HTML-страницу (`quote_unavailable.html`), API → `{"detail":CODE}` |
| #329 | **Excel-paste**: буфер tab-separated → диалог назначения колонок (превью с нормализованным числом) → bulk-create |
| #331 | **AI суточный спенд-кап** per-company в `enqueue_ai_job` (аудит #13): `sourcing/ai_spend_cap.py`, дефолт `AI_DAILY_JOB_CAP_PER_COMPANY`=300, ≤0=выкл, оператор/без-компании exempt; 429 + перевод |
| #332 | **Typeahead-подбор товара** в ячейке имени КП (комбобокс + reassign-bind); свободный текст на blur → каноническое имя (не регресс — имя раньше не редактировалось) |

Находки ревью, исправленные ДО мержа: 410-браузерная страница (#330), N+1 fx_market за гейтом (ранее #322), перевод AI-кода (#331), undo stale-rollback (ранее #323).

## Реестр долгов (верифицирован по коду — многое в старых доках уже ЗАКРЫТО)

**Закрыто, доки врали:** INF-01/04/05/07/08/09; security HIGH/MED #1–#9 (#277–#285); CRM-книга контрагентов; ADR-0005 U3; nginx dead-config. TODO/FIXME в коде НЕТ. Схема-дрейфа НЕТ.

**Owner-side (главное):** биллинг GitHub Actions мёртв с ~07-06 (CI+e2e стоят) → потом INF-12 + F0.3. Staging (workflow есть, инертен: DNS+env+Caddy). Sentry DSN. DMARC. ЗРУ-547.

**Owner-POLICY (ЖДУ решения — не делаю автономно):**
- AI compose/enrich/extract за KYC-floor/подпиской (тариф→фича). Спенд-кап уже сделан (#331).
- Register-энумерация (400 vs 201 = оракул email; forgot-password уже нейтрален) — меняет UX регистрации.
- sync-PDF `?format=pdf` → 202 (WeasyPrint inline в `crm/services/quotes.py:711` / `exporters.py:130`) — меняет UX кнопки.
- Удаление orphan `crm/status-choices/` + `sourcing/requests/` (0 фронт-вызовов).

**Волна 3 КП (по спросу, спека §5 `spec-quote-builder-ux-refactor-2026-07-14.md`):** TanStack Virtual + распил `QuoteBuilderGrid.tsx` (~1400 стр!); optimistic locking QuoteItem; консолидация настроек; каскад-визуализация charges; секции/optional items. Fast-follows: **fx_market в usePricingMirror** (backend отдаёт с #322, фронт НЕ потребляет — уберёт маркер «пересчёт после сохранения»); тихий кламп bulk→тост; мёртвый `variant="full"` QuoteApprovalChain; лишние /me-запросы.

**Гигиена:** spectacular 182 warnings/68 errors; cov-гейт 30% при ~78% (971 тест); файлы >500 строк (backend quotes.py 1478/1191/1030, frontend grid ~1400/crmApi 995/App 797); master-system-document.md устарел.

**Deferred owner P0:** Click/Payme+идемпотентность; E-IMZO (модели PaymentProviderEvent/DigitalSignature НЕ существуют).

## Процесс-уроки (подтверждены сессией)
- **Только `npm run build` (tsc -b) проверяет типы** — голый `tsc --noEmit` на корне пуст (стоило сломанного прода 07-15).
- black/isort в контейнере: конфиг из репо-root — `docker cp pyproject.toml railtech_backend:/tmp/` + `--config /tmp/pyproject.toml` / `--settings-path`.
- Backend-контейнер бинд-маунтит main-репо → одновременно ОДИН backend-агент в main; frontend-агенты — в worktree параллельно. Грид = один файл → grid-фичи сериализуются.
- Адверсариальное ревью ловит 1-2 MAJOR на PR стабильно — не пропускать; фиксы оркестратором до мержа; мерж по подтверждению владельца (классификатор блокирует self-merge).
- Менял тип `Capabilities` (обязательные поля) → grep ВСЕ тест-фикстуры в том же PR (иначе `tsc -b` валит build).

## Инфра
CI мёртв (billing) — гейты локально, deploy (self-hosted) работает; серия мержей отменяет промежуточные раны — проверять финальный + бандл на VPS. Прод здоров. Миграция crm/0060 применена на проде.
