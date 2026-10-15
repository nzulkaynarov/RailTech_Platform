/**
 * Типы CRM-домена: сделки, КП, позиции, сообщения, лента, лиды, книга контрагентов,
 * схема нумерации документов.
 *
 * Вынесено из crmApi.ts при распиле. Публичные имена и пути импорта сохранены —
 * `@/api/crmApi` остаётся барьером и реэкспортирует всё отсюда.
 */

import { Product as CatalogProduct } from '../catalogApi';
import type { components } from '../schema';

export type Product = CatalogProduct;

export type QuoteFxRate = components['schemas']['QuoteFxRate'];

// N2 — document-numbering scheme. Reset period mirrors the backend
// DocumentNumberingScheme.RESET_PERIOD_CHOICES.
export type NumberingResetPeriod = 'never' | 'yearly' | 'monthly';

// Редактируемые метки токена {type} по виду документа (КП/CT/INV/ACT/DOC → текст).
export type NumberingTypeLabels = Record<string, string>;

export interface NumberingScheme {
	pattern: string;
	padding: number;
	reset_period: NumberingResetPeriod;
	start_value: number;
	prefix: string;
	is_effective: boolean;
	type_labels: NumberingTypeLabels;
}

// PATCH / preview body — a full draft scheme (mask semantics validated backend-side).
export interface NumberingSchemeUpdate {
	pattern: string;
	padding: number;
	reset_period: NumberingResetPeriod;
	start_value: number;
	type_labels?: NumberingTypeLabels;
}

// Preview дополнительно принимает ЧЕРНОВОЙ префикс из поля редактора, чтобы пример
// нумерации отражал ещё не сохранённый префикс И метки типов вживую (WYSIWYG).
export interface NumberingPreviewInput extends NumberingSchemeUpdate {
	prefix?: string;
}

export interface NumberingPreviewItem {
	type_code: string;
	label: string;
	number: string;
}

// Odoo-style строковый тип позиции КП (mirror backend QuoteItem.DisplayType):
//   ITEM — обычная позиция с ценой (входит в итоги); SECTION — заголовок раздела
//   (жирный, с подытогом, без цен); NOTE — заметка (курсив, без цен).
export type QuoteItemDisplayType = 'ITEM' | 'SECTION' | 'NOTE';

export interface QuoteItem {
	id: number;
	quote: number;
	// S1 (спека §5 п.19): тип строки. undefined трактуется как ITEM (обратная совместимость).
	display_type?: QuoteItemDisplayType;
	// Опциональная позиция — показывается клиенту с ценой, но НЕ входит в итоги/маржу КП.
	is_optional?: boolean;
	// Явный порядок строки внутри КП (перемещение ↑/↓, группировка под разделами).
	position?: number;
	product?: number | null;
	product_name?: string;
	product_domain?: string;
	product_sku?: string;
	product_gost?: string;
	product_mpn?: string;
	product_uom?: string;
	offer?: number | null;
	offer_supplier_name?: string;
	imported_raw_name: string;
	quantity: number;
	unit?: string;
	unit_code?: string;
	mpn?: string;
	gost_drawing?: string;
	hs_code?: string;
	note?: string;
	is_incomplete?: boolean;
	frozen_base_price: string;
	// The LINE's COST currency (base-price currency), code e.g. "USD". null ⇒ UZS.
	frozen_currency: string;
	logistics_cost: string;
	// customs_duty is entered in the SAME line currency as frozen_base_price.
	customs_duty: string;
	// DT1 — ПОЗИЦИОННОЕ переопределение наценки (семантика Salesforce CPQ / Odoo).
	// `null` = переопределения НЕТ, позиция наследует КП-маржу (`Quote.margin_percent`) — это
	// дефолт. Любое НЕ-null значение побеждает КП-маржу, ВКЛЮЧАЯ явный «0» = «продать по
	// себестоимости». Поэтому очистка ячейки обязана слать именно `null`, а не «0»: раньше
	// колонка была NOT NULL с default=0 и эти два состояния были неразличимы.
	margin_percent: string | null;
	discount_percent: string;
	// Per-line срок поставки (days). КП-level effective срок = max over lines.
	lead_time_days: number;
	// landed_cost / final_price_excl_vat are READ-ONLY and now in UZS
	// = (frozen_base_price + customs_duty) × fx rate of frozen_currency.
	landed_cost: string;
	final_price_excl_vat: string;
	assigned_at?: string | null;
	// Optimistic-concurrency counter (волна 3). READ-ONLY: the server bumps it on every save.
	// The grid echoes the last-read value back in the bulk/single save payload so the backend can
	// reject a stale write (QUOTE_ITEM_STALE) instead of clobbering a colleague's committed edit.
	version?: number;
}

export type DealItem = QuoteItem;

export interface DeliveryBasis {
	id: number;
	code: string;
	name: string;
	description?: string;
	seller_pays_freight: boolean;
	seller_pays_insurance: boolean;
	seller_pays_import: boolean;
	seller_pays_delivery: boolean;
}

// КП-level expense item / discount (UBL document AllowanceCharge). Seller-only —
// the buyer never receives these rows (server gates them).
export interface QuoteCharge {
	id: number;
	quote: number;
	charge_type: string;          // ChargeType code, e.g. 'FREIGHT'
	charge_type_name?: string;
	description?: string;
	amount: string;
	rate_percent?: string | null; // % of subtotal; takes priority over amount
	cost_amount?: string | null;  // seller's REAL cost (null ⇒ billed-at-cost pass-through)
	is_deduction: boolean;        // true = discount (−), false = charge (+)
	from_template?: boolean;      // auto-created from an Incoterm template (vs added by hand)
	sort_order?: number;          // cascade position (top→bottom); reorder changes the % base
	resolved_base?: string | null;   // running tax-excl subtotal this row was applied to
	resolved_amount?: string | null; // signed computed amount (UBL BaseAmount/Amount)
	created_by?: number | null;
	created_at?: string;
}

// Per-company charge template (org-admin): default charges auto-applied per basis.
export interface ChargeTemplate {
	id: number;
	delivery_basis: string;        // Incoterm code
	delivery_basis_name?: string;
	charge_type: string;           // ChargeType code
	charge_type_name?: string;
	default_amount: string;
	default_rate_percent?: string | null;
	is_deduction: boolean;
	sort_order: number;
	is_active: boolean;
}

/** Seller unit economics for the КП (cost-gated; null when the viewer can't see costs or
 *  on list endpoints). Decimals arrive as strings. Re-exported from the generated OpenAPI
 *  types (DT2) — the hand-written interface was a field-for-field duplicate. */
export type QuoteEconomics = components['schemas']['QuoteEconomics'];

/** One node of the КП internal approval chain (unified workflow). */
export interface QuoteApprovalStep {
	id: number;
	order: number;
	participation: 'HEAD' | 'APPROVER' | 'INFORMED';
	status: 'PENDING' | 'APPROVED' | 'REJECTED' | 'SKIPPED' | 'RECALLED';
	approver: number | null;
	approver_name: string;
	approver_role: number | null;
	acted_by: number | null;
	acted_by_name: string;
	is_mandatory: boolean;
	is_auto: boolean;
	trigger_reason: string;
	comment: string;
	decided_at: string | null;
	created_at: string;
	can_act: boolean;        // may the requesting user act on this step right now
}

export interface QuoteApprovalPreviewStep {
	participation: string;
	participation_label: string;
	trigger: string;
	trigger_label: string;
	name: string;
	role: string;
	is_assigned: boolean;
	is_submitter: boolean;
}

export interface QuoteApprovalPreview {
	would_auto_approve: boolean;
	below_floor: boolean;
	steps: QuoteApprovalPreviewStep[];
}

export interface Quote {
	id: number;
	deal: number;
	version: number;
	status: number;
	status_code: string;
	status_name: string;
	delivery_basis?: number | null;
	delivery_basis_data?: DeliveryBasis | null;
	// Presentation currency (all stored totals are in UZS regardless); Currency code.
	quote_currency?: string | null;
	// Default cost currency new lines inherit (Currency code or null ⇒ UZS).
	cost_currency_default?: string | null;
	// Frozen FX (READ-ONLY): { currencyCode: "rateToUzsString" } e.g. {"USD":"12000"}.
	fx_snapshot?: Record<string, string>;
	// Договорной курс КП (READ-ONLY; пишется только fx-override с правом finance.rates, M1-ERP-08).
	fx_manual?: Record<string, string>;
	// M1-ERP-08 «курс на дату КП»: курсы с датой и источником (только с quote.view_cost_margin),
	// режим (live — черновик по текущему курсу, fixed — зафиксировано при отправке на согласование).
	fx_rates?: QuoteFxRate[];
	fx_mode?: components['schemas']['FxModeEnum'];
	fx_fixed_at?: string | null;
	// READ-ONLY preliminary PUBLIC market rates { currencyCode: "rateToUzs" } for currencies not
	// yet frozen into fx_snapshot — lets the pricing mirror preview a new-currency line instead of
	// «пересчёт после сохранения». The server freezes its own rate on save (detail context only).
	fx_market?: Record<string, string>;
	// КП-level срок поставки OVERRIDE in days (null ⇒ use derived max over lines).
	delivery_lead_time_days?: number | null;
	// READ-ONLY computed срок = override if set else max(items[].lead_time_days) (0 if none).
	effective_delivery_lead_time_days?: number;
	// "в наличии" / "под заказ" nuance (max 255).
	delivery_note?: string;
	tax_country?: number | null;
	vat_rate?: string;
	margin_percent?: string;          // КП-level markup applied to every line (F3.8)
	items: QuoteItem[];
	charges?: QuoteCharge[];       // seller-only; absent for buyers
	subtotal_excl_vat: string;
	charges_total?: string;        // seller-only
	vat_amount: string;
	total_incl_vat: string;
	valid_until?: string | null;
	notes?: string;
	pdf_file?: string | null;
	frozen_at?: string | null;
	// ── Wave B2 post-send tracking (PandaDoc pattern). All OPTIONAL: the seller-facing
	// QuoteSerializer only exposes these once the parallel backend (B1) lane adds them, so the
	// post-send panel degrades gracefully (hides the affected control) when a field is absent.
	// first_viewed_at — first genuine client open of the public КП page (Wave A model field,
	// «Просмотрено {date}»). public_access_token — the no-login share token (public URL built
	// client-side). public_token_revoked — whether the seller revoked the share link.
	first_viewed_at?: string | null;
	public_access_token?: string | null;
	public_token_revoked?: boolean;
	approved_by?: number | null;
	approved_at?: string | null;
	// Seller unit economics — present only on the single-quote/deal detail for a cost-viewer.
	economics?: QuoteEconomics | null;
	// Internal approval chain — present only on the single-quote/deal detail.
	approval_steps?: QuoteApprovalStep[];
	created_at: string;
	updated_at?: string;
}

/**
 * Цепочка документов сделки — ответ `GET crm/deals/{id}/documents/` (F1, «карточка как хаб»).
 *
 * Подсказку следующего шага считает СЕРВЕР (`for_viewer` — ход бэк-офиса; шаги клиента —
 * подписать, оплатить, принять — показываются как ожидание: клиент делает их в Cabinet).
 */
export type DealDocumentStepCode =
	| 'SIGN_CONTRACT'
	| 'CREATE_INVOICE'
	| 'ISSUE_INVOICE'
	| 'PAY_INVOICE'
	| 'GENERATE_ACT'
	| 'SIGN_ACT'
	| 'SHIP'
	| 'ACCEPT_DELIVERY'
	| 'DONE';

export interface DealDocumentStep {
	code: DealDocumentStepCode;
	/** Ход зрителя (иначе шаг за контрагентом — показываем как ожидание, без кнопки). */
	for_viewer: boolean;
	page: string;
	object_id: number | null;
}

export interface DealHubContract {
	id: number;
	number: string;
	status: string | null;
	status_name: string | null;
	total_amount: string;
	client_signed_at: string | null;
	manager_signed_at: string | null;
	is_fully_signed: boolean;
	viewer_can_sign_manager: boolean;
}

export interface DealHubInvoice {
	id: number;
	number: string;
	status: string | null;
	status_name: string | null;
	total_incl_vat: string;
	amount_paid: string;
	balance_due: string;
	due_date: string | null;
	issued_at: string | null;
}

export interface DealHubAct {
	id: number;
	number: string;
	status: string | null;
	status_name: string | null;
	total_amount: string;
	signed_at: string | null;
}

export interface DealHubFulfillment {
	id: number;
	status: string | null;
	status_name: string | null;
	expected_delivery_date: string | null;
	shipped_at: string | null;
	delivered_at: string | null;
	accepted_at: string | null;
	tracking_number: string;
	carrier: string;
}

export interface DealDocumentHub {
	deal: number;
	stage_code: string | null;
	contract: DealHubContract | null;
	invoices: DealHubInvoice[];
	acts: DealHubAct[];
	fulfillment: DealHubFulfillment | null;
	payments_count: number;
	payments_total: string;
	next_step: DealDocumentStep | null;
}

export interface Deal {
	id: number;
	company?: number | null;
	company_name?: string;
	contact_name?: string | null;
	client?: number | null;
	client_name?: string;
	manager?: number | null;
	manager_name?: string;
	assigned_to?: number | null;       // deal owner (claimed); null = unclaimed, in the queue
	assigned_to_name?: string;
	assigned_at?: string | null;       // time-to-first-touch anchor
	/**
	 * Может ли зритель вернуть сделку в очередь своей компании. Считает СЕРВЕР тем же
	 * предикатом, что и сам возврат (владелец записи ИЛИ участник с `team.manage`), — фронт
	 * не выводит право сам, иначе кнопка появлялась бы там, где действие откажет (U1).
	 */
	viewer_can_release?: boolean;
	stage?: number | null;
	stage_code?: string;
	stage_name?: string;
	title?: string;
	total_value?: string;
	notes?: string;
	active_quote?: Quote | null;
	quotes?: Quote[];
	/** O4: исполнение закрыто целиком (оплата + поставка + акт) — не то же, что «сделка выиграна». */
	execution_complete?: boolean;
	created_at: string;
	updated_at?: string;
}

/** Wedge metric — hours from RFQ routed → first КП sent (ADR-0006 Move 4). */
export interface TimeToFirstQuoteStats {
	sample_size: number;
	median_hours: number;
	avg_hours: number;
	p90_hours: number;
	fastest_hours: number;
	slowest_hours: number;
}

// Лента активности сделки/контрагента. Форма ОДНА: прежний `ActivityLog` дублировал её
// один-в-один и остался без потребителей, когда лента переехала на таймлайн-эндпоинт.
export interface TimelineEntry {
	id: number;
	action: string;
	detail: string;
	// Structured event (spec-timeline-i18n): localized on the client from these when present.
	event_code?: string;
	event_params?: Record<string, unknown>;
	level: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR';
	timestamp: string;
	user_name: string;
	entity_type: string;
	entity_id: number | null;
	deal_id: number | null;
	company_id: number | null;
	contact_id: number | null;
}


/** Contact of a company in the team's own client book. */
export interface Contact {
	id: number;
	company: number;
	company_name: string;
	company_is_registered: boolean;
	name: string;
	email?: string;
	phone?: string;
	position?: string;
	is_primary?: boolean;
	created_at: string;
}

/** «Завести оффлайн-клиента» — company + contact in one step (flat write). */
export interface OfflineClientPayload {
	company_name: string;
	contact_name: string;
	inn?: string;
	email?: string;
	phone?: string;
	position?: string;
}
