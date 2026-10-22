# MIGRATION-MAP — что из B2B и CRM куда переезжает

Версия 1.0 · 2026-10-13 · Источник для задач M1-ERP-02, M2-CAB-02, M3-CRM-*. Колонка «Удалить» — порядок
удаления в M1-ERP-02: сначала невплетённое (операторская плоскость, Lead, Message, KYC, заявки на роли),
затем вплетённое (entitlements в сервисах КП, routing в выборках, capability-навигация).

---
## 1. Карта переезда: из B2B

| Модуль B2B | → ERP | → Cabinet | Удалить |
|---|---|---|---|
| accounts: пользователи, 2FA, сессии, lockout | ✓ (`accounts`) | | |
| accounts: Company, Contact, DocumentProfile | ✓ (`parties`) | профиль компании и команда | |
| accounts: KYC L1–L3, заявки на роли, регистрация с улицы | | | ✓ |
| accounts: подписки, entitlements, DEMO, кредиты | | | ✓ |
| accounts: OperatorRole, break-glass | | | ✓ (роль «Администратор») |
| accounts: CompanyRole (права КП/документов) | ✓ (роли бэк-офиса) | | |
| accounts: merge по ИНН, CounterpartyRelationship | | | ✓ |
| catalog: Product, Category, импорт, ИИ-обогащение, полнота, публикация | ✓ | опубликованный слой | |
| catalog: EquipmentGroup, DomainType ЖД, DomainKeyword | | | ✓ |
| catalog: SupplierOffer | ✓ (`supply`) | | |
| catalog: CategoryRequest | ✓ (как запрос на карточку из ERP-очереди) | «нет нужной позиции» → свободная строка | |
| master_data: страны, валюты, единицы, базисы, курсы | ✓ | | |
| master_data: HSCode + автосинк | ✓ (справочник, выключаемый) | | |
| crm: Deal, FSM, assignment | ✓ (`sales`) | мои запросы | |
| crm: DealSellerRouting, скрытая конкуренция | | | ✓ |
| crm: Quote, QuoteItem, charges, approvals, versions, pricing_assist | ✓ | КП клиента | |
| crm: Contract, wording, document_blocks, templates | ✓ (`sales` + `documents`) | договоры | |
| crm: Invoice, Payment, Act, deal_emails | ✓ (`finance`) | счета, акты | |
| crm: Fulfillment, накладная | ✓ (`inventory`, по строкам) | поставки | |
| crm: public quote page (202 + PDF) | ✓ (`portal`) | страница акцепта | |
| crm: Lead, LeadCreateView, AdminLeadsPage | | | ✓ (CRM) |
| crm: Message, ChatDrawer, support tickets | | | ✓ (бот CRM) |
| crm: analytics dashboard, TTFK | ✓ | | |
| sourcing: AI import/preflight/extract/compose, AIJob, ImportTask | ✓ (`ai`, через LiteLLM) | | |
| notifications: EmailLog, шаблоны, WS-уведомления | ✓ | уведомления клиенту | |
| core: audit, idempotency, optimistic locking, validators, health | ✓ | | |
| frontend: AppShell, QuoteBuilder, Admin* (16), PlatformAdminShell | ERP: AppShell (бэк-офис), QuoteBuilder | Cabinet: своя оболочка | Admin*, PlatformAdminShell |
| frontend: покупательские страницы | | ✓ | |
| deploy/caddy, workflows | `infra/` | | |

## 2. Карта переезда: из CRM

| Модуль CRM | Судьба |
|---|---|
| bot, agents, kb, qualifier, inbox, lead card, settings, admin console, evals | без изменений |
| `services/deals`, ADR-0019 | становится зеркалом сделок ERP; создание сделки = заявка в ERP |
| `ClientService.make_customer` | становится «Передать в бэк-офис»: вызывает ERP, стадия `customer`, бот в сервисный режим (CRM ADR-0022) |
| `documents`, `docs-mcp` | документы клиента читаются из ERP через `erp-mcp`; собственное хранилище — только для файлов, которых в ERP нет |
| `security/tokens`, пользователи | + `platform_access`, SSO-токены, провижининг |
| `integrations/` | + коннектор ERP, приёмник вебхуков |

## 3. Что новое и ни откуда не переезжает

`supply` (заказы поставщикам, приёмки, счета поставщиков, субподряд), `inventory` (журнал движений,
резервы), политика видимости каталога, курс на дату КП с отклонением маржи, `portal` API и вход по
Telegram, `integration` API и вебхуки, `erp-mcp`, SSO и `platform_access`, ERP через LiteLLM и
Langfuse, evals ERP, общие токены дизайна, инфраструктура ансамбля.
