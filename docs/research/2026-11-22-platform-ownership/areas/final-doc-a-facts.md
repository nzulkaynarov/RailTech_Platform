# AREA 1 — внешняя проверка фактов ДОКУМЕНТА A (Knowledge-First), 2026-11-23

Статусы: **подтверждено / частично / неверно / не проверить**. Выводы без прямого источника помечены «(вывод)». Проверялось веб-поиском и чтением первоисточников. В репозитории (`research-main`) сверено только то, что нужно для сопоставления.

## 0. Итог

1. Фактическая часть про MCP в основном верна: ревизия `2026-07-28` существует и действует. Две ошибки: Tasks вынесены из ядра в расширение, а OAuth спецификация называет необязательным.
2. «8–15 инструментов» — число без первоисточника. Направление верное, норма не подтверждена.
3. Слой Postgres описан верно по возможностям, но с четырьмя неточностями: VIRTUAL-колонки, CHECK с JSON Schema, «физически не сможет» про RLS, «морфология» в tsvector.
4. «Чистая сериализация в Markdown» неверна: сам Tiptap пишет, что обратный импорт даёт упрощённый документ.
5. Сроки «4–6 недель на фазу» сопоставимыми публикациями не подтверждаются; косвенные данные говорят о кратном занижении для фаз 1–2.
6. Заметная часть уже есть в репозитории (outbox с HMAC, MCP-серверы, Tiptap в Платформе, pgvector), а часть прямо отклонена владельцем 18.11 и 21.11 (пользовательские поля, холст).
7. Документ написан для многоарендного SaaS с одной базой. У нас одна компания и три базы, поэтому `tenant_id` + RLS и единый граф `entity_links` к нам не переносятся как есть.

## 1. MCP: ревизии спецификации

| Ревизия | Что добавила или убрала | Источник |
|---|---|---|
| 2024-11-05 | Первая версия: stdio и HTTP+SSE; Resources, Prompts, Tools; Sampling, Roots | modelcontextprotocol.io/specification/2024-11-05 (состав этой ревизии — по памяти, страница в этой сессии не открывалась) |
| 2025-03-26 | Авторизация на базе OAuth 2.1; Streamable HTTP вместо HTTP+SSE; tool annotations; JSON-RPC batching; аудио | …/specification/2025-03-26/changelog |
| 2025-06-18 | Batching убран; structured tool output; сервер = OAuth Resource Server; клиентам MUST RFC 8707; elicitation; resource links; заголовок `MCP-Protocol-Version` | …/specification/2025-06-18/changelog |
| 2025-11-25 | OIDC Discovery; иконки; incremental scope consent; URL-mode elicitation; sampling с tools; Client ID Metadata Documents (CIMD); **experimental** tasks; JSON Schema 2020-12 | …/specification/2025-11-25/changelog |
| **2026-07-28 (current)** | Убраны сессии и `Mcp-Session-Id`, handshake `initialize`, `ping`, `logging/setLevel`, возобновление SSE. Добавлены `server/discover`, `subscriptions/listen`, обязательный `resultType`, Multi Round-Trip Requests (MRTR), заголовки `Mcp-Method`/`Mcp-Name`, `ttlMs`/`cacheScope`. **Tasks вынесены в расширение** `io.modelcontextprotocol/tasks` с переделанным API. Deprecated: Roots, Sampling, Logging, HTTP+SSE, Dynamic Client Registration | …/specification/2026-07-28/changelog; …/specification/versioning («The current protocol version is 2026-07-28») |

## 2. Таблица вердиктов

### 2.1. MCP и авторизация

| Утверждение документа A | Статус | Примечание и источник |
|---|---|---|
| Ревизия MCP `2026-07-28` существует и актуальна | подтверждено | Страница versioning и блог blog.modelcontextprotocol.io/posts/2026-07-28/ |
| «stateless JSON-RPC 2.0 поверх Streamable HTTP» | подтверждено | Точное описание для удалённого сервера. Оговорка: изменение ломающее. Claude на 28.07 — «rolling out soon» (claude.com/blog/bringing-mcp-2026-07-28-to-claude). По вторичным источникам TS SDK по умолчанию оставляет старый handshake |
| Три примитива Resources / Tools / Prompts | подтверждено | `resources/subscribe` заменён на `subscriptions/listen` |
| SDK даёт «полную поддержку… Tasks и Elicitation» | частично | Tasks никогда не были стабильной частью ядра: experimental в 2025-11-25, с 2026-07-28 — отдельное расширение с другим API. Четыре SDK Tier 1 (TS, Python, Go, C#) говорят на 2026-07-28 (официальный блог) |
| Human-in-the-loop через MCP Elicitation | частично | Elicitation в ядре с 2025-06-18, но механизм изменён в 2026-07-28 (идёт через `InputRequiredResult`). Это возможность клиента: «Servers SHOULD NOT assume that elicitation requests will always succeed». URL-режим помечен «may change». Надёжна только вторая ветка документа A: черновик и подтверждение в нашем интерфейсе (…/2026-07-28/client/elicitation) |
| «8–15 доменных инструментов — правило 2026 года» | частично | Направление подтверждено: Anthropic — «More tools don't always lead to better outcomes», объединять, не оборачивать эндпоинты, **числа нет** (anthropic.com/engineering/writing-tools-for-agents). OpenAI — «fewer than 20 functions… soft suggestion» (developers.openai.com/api/docs/guides/function-calling). Блоги называют 30–50; FullStory пишет, что ясность описаний важнее числа. Диапазон «8–15» в первоисточниках не найден |
| «Нельзя статические API-ключи; обязательный минимум OAuth 2.1 + PKCE + RFC 8707» | частично | Спецификация: «Authorization is OPTIONAL»; для HTTP — SHOULD. Если авторизация есть: клиент MUST RFC 8707, сервер MUST проверять audience и MUST реализовать RFC 9728. Для публичного сервера под Claude/ChatGPT/Cursor OAuth практически обязателен. Для вызова «наш агент → наш сервер» — нет. Документ A не упоминает CIMD (DCR уже deprecated), RFC 9728, RFC 9207 |
| OAuth 2.1 | частично | Это всё ещё Internet-Draft: `draft-ietf-oauth-v2-1-17` от 30–31.10.2026, IESG state «I-D Exists», номера RFC нет (datatracker.ietf.org/doc/draft-ietf-oauth-v2-1/). Спецификация MCP ссылается на draft-13. RFC 8707 — действующий RFC. PKCE — RFC 7636 (по памяти) |
| Недоверенный текст «в изолированных тегах» защищает от indirect prompt injection | частично | Обзоры сходятся: одних разделителей мало, нужны структурные меры — подтверждение записи человеком, детерминированная проверка, разрыв «lethal trifecta» (dzone.com/articles/mcp-lethal-trifecta и др., вторичные). Вторая половина тезиса (детерминированная валидация записи) верна |
| A2A «легко добавляется поверх MCP» | частично | Статус верен: A2A v1.0, под Linux Foundation с 23.06.2025, 150+ организаций (opensource.googleblog.com/2026/04/…anniversary-of-a2a.html; linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations…). Но это отдельный протокол рядом с MCP, а не слой над ним; «легко» ничем не подтверждено |

### 2.2. Редактор и совместная работа

| Утверждение | Статус | Примечание и источник |
|---|---|---|
| Tiptap — открытое ядро | подтверждено | Редактор MIT (tiptap.dev/pricing). Платная Tiptap Platform: $49 / $149 / $999 в месяц при годовой оплате; on-prem только Enterprise. Часть Pro-расширений под отдельной лицензией (tiptap.dev/pro-license) |
| «Yjs + Hocuspocus — open-source без привязки к дорогим облакам» | частично | Hocuspocus — MIT (github.com/ueberdosis/hocuspocus). В открытой части только синхронизация и присутствие. Комментарии, сравнение версий, tracked changes, импорт и экспорт DOCX — платная платформа либо своя разработка |
| BlockNote: совместная работа «встроена (часто через Liveblocks)» | частично | Работает на Yjs с любым провайдером: Liveblocks, PartyKit, Y-Sweet, Hocuspocus, y-websocket (blocknotejs.org/docs/features/collaboration). Лицензии: ядро MPL-2.0; XL-пакеты (экспорт PDF/DOCX/ODT, колонки, AI) — AGPL-3.0 или коммерческая, Business $390 в месяц (blocknotejs.org/pricing) |
| Lexical: Yjs нативно | не проверить | В этой сессии не перепроверялось |
| Liveblocks «дорогой» | частично | По документации: Pro $30 в месяц с 1 000 активных комнат, Team от $600. Страницы цен противоречат друг другу (liveblocks.io/docs/pricing/…) |
| CRDT на Yjs зрелый | частично | Широко используется, но есть известные проблемы. y-prosemirror пересоздаёт документ и ломает привязку позиций (комментарии, присутствие). При несовпадении схемы узел удаляется у всех. У Yjs нет серверного авторитета для прав. (moment.dev/blog/lies-i-was-told-pt-2 — автор продаёт конкурирующий продукт; исправление идёт в y-prosemirror PR #216.) Размер документа растёт, открытые документы держатся в памяти (discuss.yjs.dev; tiptap.dev/docs/hocuspocus/guides/scalability) |
| «Чистая сериализация в MD», `content_md` как каноническое представление | **неверно** | `@tiptap/markdown` — «early release». Комментарии не поддержаны; в ячейке таблицы один узел; объединённые ячейки не поддержаны; «re-importing the exported Markdown will produce a simplified document» (tiptap.dev/docs/editor/markdown; …/conversion/export/markdown/editor-extension). Markdown годится как проекция для чтения и ИИ, не как хранение. (вывод) Пара `content_md` + `yjs_state` — два источника правды |
| Цена своего Hocuspocus | не проверить | Опубликованных цифр нет. (вывод) Это служба на Node в стеке Python, WebSocket через Caddy, хранение, авторизация, Redis при нескольких экземплярах, миграции схемы. Для десятков пользователей хватит одного экземпляра |

### 2.3. PostgreSQL и хранение

| Утверждение | Статус | Примечание и источник |
|---|---|---|
| JSONB + GIN `jsonb_path_ops` для `@>` | подтверждено | Класс поддерживает только `@>`, `@?`, `@@`. Диапазоны и сортировку не ускоряет (postgresql.org/docs/current/datatype-json.html, раздел JSON-INDEXING — по памяти, страница не открывалась). (вывод) Индекс на каждое «горячее» поле — это DDL и миграция, что спорит с идеей поля без разработчика |
| Generated Columns «виртуальные/хранимые» на PostgreSQL 16+ | частично | До 17 включительно только STORED. VIRTUAL появились в PostgreSQL 18, по умолчанию, не идут в логическую репликацию (postgresql.org/docs/19/ddl-generated-columns.html; dbi-services.com/blog/postgresql-18-virtual-generated-columns/) |
| Валидация `custom_props` по JSON Schema через `CHECK` | частично | Встроенной проверки JSON Schema в Postgres нет, нужно расширение или ручной CHECK. CHECK не может читать `property_definitions` (postgresql.org/docs/current/ddl-constraints.html — по памяти). Проверка по динамическому реестру возможна только в приложении или триггере |
| RLS: агент «физически не сможет» прочитать чужое | частично | Механизм есть, формулировка завышена. Владелец таблицы, суперпользователь и роль `BYPASSRLS` обходят политики без `FORCE ROW LEVEL SECURITY`; ORM обычно ходит под владельцем. При пуле нужен `SET LOCAL` в транзакции. Представления до PG 15 идут с правами владельца (bytebase.com/blog/postgres-row-level-security-footguns; planetscale.com/blog/rls-sounds-great-until-it-isnt — блоги) |
| pgvector с HNSW | подтверждено | Предел индекса 2 000 измерений для `vector`, 4 000 для `halfvec`; bge-m3 (1024) помещается. Слабое место — поиск с фильтром по правам: без `hnsw.iterative_scan` (с 0.8.0) возвращается слишком мало строк (postgresql.org/about/news/pgvector-080-released-2952/) |
| `tsvector` «с морфологией RU/EN» | частично | Встроенная конфигурация `russian` — стеммер Snowball, не словарная морфология; для неё нужны словари hunspell. Узбекского стеммера в списке Snowball нет (по памяти; проверить `\dF` на сервере). `ts_rank` — не BM25 |
| «Отказаться от EAV; JSONB + реестр — как у Notion» | частично | У Notion блок действительно несёт `properties` (notion.com/blog/data-model-behind-notion). Но аналитику Notion вынесла в отдельное озеро: Debezium → Kafka → Hudi → S3 (notion.com/blog/building-and-scaling-notions-data-lake). GitLab для полей задач отверг JSONB из-за фильтров, группировки и сортировки и взял типизированные таблицы значений; лимиты 50 полей на группу и 10 на тип (gitlab.com/gitlab-org/gitlab/-/issues/335110; docs.gitlab.com/user/work_items/custom_fields). «EAV убивает отчёты» — не универсальная истина |
| ClickHouse/DuckDB «опционально на масштабе» | подтверждено как оговорка | (вывод) При десятках записей на проде не нужно |

### 2.4. Файлы, шина, сроки, подход

| Утверждение | Статус | Примечание и источник |
|---|---|---|
| Docling / Unstructured дают «качественный перевод PDF/Excel в Markdown», поиск «внутри сканов сертификатов» | не проверить | Замеров на русских и узбекских сканах не найдено. Скорость на CPU: медиана 0,79 с и среднее 3,1 с на страницу, таблица 1,74 с, OCR — около 60 % времени (arxiv.org/pdf/2501.17887); EasyOCR на CPU — более 30 с на страницу (arxiv.org/html/2408.09869, ранний отчёт). Русский: EasyOCR `ru`, RapidOCR cyrillic. Узбекский: `uz` только в латинской модели EasyOCR и в PP-OCRv6; **узбекской кириллицы нет** (docling-project.github.io/docling/concepts/OCR_native/). Сравнение Unstructured (0,857 против 0,716 у Docling) сделано самим вендором. Нужен тест на своих 30–50 документах |
| Transactional outbox | подтверждено | Стандартный приём |
| Брокер NATS / Kafka / RabbitMQ обязателен | частично | Для малого объёма очередь в Postgres (`SKIP LOCKED`) достаточна; брокер оправдан при повторном чтении истории, многих независимых потребителях, высокой нагрузке (techcommunity.microsoft.com/blog/adforpostgresql/potential-consequences-of-using-postgres-as-a-job-queue/4514332; morling.dev/blog/you-dont-need-kafka-just-use-postgres-considered-harmful). (вывод) Kafka для одной компании избыточна |
| Вебхуки: HMAC-SHA256, Idempotency-Key, повторы, DLQ | подтверждено | Это стандарт (Standard Webhooks: `webhook-id`, `webhook-timestamp`, `webhook-signature`; OWASP Webhook Security Cheat Sheet). В документе A нет окна по времени против повтора и ротации секрета |
| «4–6 недель на фазу», всего 16–22 недели | не проверить; косвенно занижено | Сопоставимых публикаций нет. Косвенно: Aha! перестраивала редактор около двух лет силами 28 инженеров (aha.io/engineering/articles/derisking-editor-upgrade). Офлайн в Notion был запросом №1 пять лет и потребовал перевода страниц на CRDT (notion.com/blog/how-we-made-notion-available-offline). У GitLab первая очередь полей шла несколько месяцев выделенной командой, вторая и третья не запланированы. Tiptap обещает «days or weeks», но это вендор; TinyMCE оценивает совместную работу на Tiptap как «Extra Large». (вывод) Редактор в карточке без совместной работы за 4–6 недель реален; фазы 1–2 в заявленном составе — занижение в 2–4 раза. Фаза 4 правдоподобна для самого сервера; главная трудность по отзывам — OAuth |
| «Knowledge-first» работает в B2B с транзакциями | частично | Сам документ A предупреждает против прямого копирования — это верно. Провалы: Salesforce закрывает Quip (документы внутри CRM), продление невозможно после 01.03.2027 (salesforceben.com/salesforce-announces-end-of-life-for-quip/). Notion как CRM упирается в отчёты, права и контроль процесса при 10–50 людях (блоги конкурентов, предвзяты). Публичные страницы Notion отдавали адреса редакторов с 2022 по 2026 (cyberinsider.com/notion-pages-have-leaked-user-data…). У Odoo есть Knowledge, но свою документацию Odoo ведёт на GitHub (форум, единичное мнение). По Fibery, Coda, Airtable, Anytype, Capacities как системе учёта независимых разборов не найдено |

## 3. Чего в документе A нет, а это важно

1. **Перенос существующих данных.** Нет плана для уже лежащих документов и полей. Обратный путь через Markdown — с потерями (2.2).
2. **Права на документы и обратные ссылки.** Обратная ссылка, поиск и векторный фрагмент могут раскрыть название закрытой сделки. Notion показывает обратные ссылки только на доступные страницы (notion.com/help/create-links-and-backlinks). У Yjs нет серверного авторитета для прав на уровне блока.
3. **Качество поиска.** Нет узбекского стеммера, нет узбекской кириллицы в OCR, `ts_rank` не BM25. Нет набора проверочных запросов и метрики.
4. **Сроки хранения и удаление.** История версий и следы правок Yjs спорят с требованием удалить данные; про сроки хранения документов и персональных данных ничего нет.
5. **Выгрузка по запросу и неизменяемость.** Нет «заморозки» документа после подписи, нет выгрузки журнала и версий.
6. **Стоимость ИИ-индексации.** Нет расчёта: OCR 3–30 с на страницу на CPU, пересчёт векторов при каждой правке и при смене модели.
7. **Офлайн.** Не упомянут вовсе, хотя документ B требует работу без сети.
8. **Совместимость клиентов MCP.** Переход на 2026-07-28 ломающий в обе стороны; матрицы клиентов нет.
9. **Эксплуатация.** Резервные копии состояния Yjs и S3, миграция схемы редактора при открытых документах, наблюдаемость.
10. **Печатные формы.** Markdown не выражает бланк, реквизиты и подписи; у нас это делает `rt_docs` (`docs/architecture/rt-docs.md:53`).
11. **Три языка.** Документ A знает только RU/EN.

## 4. Сопоставление с репозиторием (только то, что влияет на вердикты)

| Тезис документа A | Что есть | Где |
|---|---|---|
| «Внедрить outbox + шину» (фаза 3) | Уже есть: outbox → relay → подписанный HTTP (HMAC v2) → inbox с дедупликацией → dead. NATS JetStream записан как v2, этап F | `docs/architecture/rt-bus.md:6-13`; `docs/adr/0014-integration-bus-rt-bus.md:19` |
| «Развернуть Remote MCP Server» (фаза 4) | Уже есть: `erp-mcp` (streamable-http, 7 инструментов, модели отдаются 5), серверы CRM `kb`/`crm`/`docs`, подписанный одноразовый контекст вместо OAuth | `packages/contracts/mcp-tools.json`; `apps/crm/backend/app/mcp/servers.py:1-6`; `apps/crm/backend/pyproject.toml:20`; `docs/DECISIONS.md:178` |
| Tiptap в `apps/cabinet` | Tiptap 3.32 стоит в Платформе; в Кабинете его нет; Yjs и Hocuspocus нет нигде | `apps/platform/web/package.json:38-41` |
| `custom_props JSONB` + `property_definitions` | Отклонено владельцем дважды | `docs/DECISIONS.md:349` (18.11), `:360` (21.11); `docs/research/2026-11-18-flexible-ui-assessment.md` §2.5 |
| Свободный холст, блок `/таблица` в карточке сделки | Отклонено 18.11; холст разрешён только для процессов | там же, §2.3; `docs/DECISIONS.md:360` п. 5 |
| RLS по `tenant_id` | Платформа одной компании; общая база с RLS — только по решению этапа H | `docs/adr/0019-product-readiness-tenant.md:11` |
| «В одной базе данных», единый `entity_links` | Три домена с отдельными базами. (вывод) Общая таблица рёбер между сделками ERP, контактами CRM и документами EDS нарушает инвариант «общих таблиц нет» | корневой `CLAUDE.md`, инварианты; ADR-0002 (по названию файла) |
| Docling и pgvector | CRM уже использует `docling-core` (только нарезку текста) и `pgvector` | `apps/crm/backend/pyproject.toml:13,23,119-121` |
| «TypeScript (NestJS/Fastify)» | (вывод) Третий серверный стек рядом с FastAPI и Django; внешних доводов за него для команды на Python нет | — |

## 5. Что не удалось проверить

- Текст дизайн-документа GitLab о полях (страница не отдала содержимое); вывод о типизированных таблицах — по issue 335110 и выдаче поиска.
- Точность Docling и Unstructured на русских и узбекских сканах; цена эксплуатации Hocuspocus в цифрах.
- Поддержка 2026-07-28 в Claude, ChatGPT и Cursor на ноябрь 2026.
- Независимый опыт Fibery, Coda, Airtable, Anytype, Capacities как системы учёта.
- Список стеммеров Snowball, операторы `jsonb_path_ops`, ограничение CHECK, состав ревизии MCP 2024-11-05, PKCE как RFC 7636 и лицензия Lexical приведены по памяти, страницы документации в этой сессии не открывались.
