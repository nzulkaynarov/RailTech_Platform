import { App, Button, InputNumber, Popconfirm, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useViewport } from "../../../app/shell/useViewport";
import type { CalcLine, CalcLinePatch, CalcSheet } from "../../../shared/api/generated/model";
import {
  useDeleteCalcLine,
  useReleaseCalcLineReservation,
  useReserveCalcLine,
  useSignCalcLine,
  useUpdateCalcLine,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { ScrollRegion } from "../../../shared/ui/FormParts";
import { CrossIcon } from "../../../shared/ui/icons";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { calcRef, useApplySheet, useErrorText } from "./api";
import { useErrorText as useStockErrorText } from "../stock/api";
import { MatchModal } from "./MatchModal";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { useGetCatalogLookups } from "../../../shared/api/generated/platform-bff";
import { HOME_CURRENCY, currencyLabel } from "../../../shared/lib/money";
import { ItemRefCell } from "../../ItemRefCell";

const GROUP_OF = { stock: "stock", supply: "supply", engineer: "engineer" } as const;

/** Число с пробелами тысяч в поле ввода; в API уходит без пробелов. */
const groupDigits = (value: string | number | undefined) =>
  value === undefined ? "" : String(value).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
const ungroup = (value: string | undefined) => (value ?? "").replace(/\s/g, "");

/** Поле суммы или количества: сохраняется по Enter и при уходе из поля, если значение изменилось. */
/** Коды валют справочника ERP для выбора валюты закупки; нет доступа к справочнику — только текущая валюта строки. */
function useCurrencyCodes(): string[] {
  const lookups = useGetCatalogLookups({ query: { staleTime: 10 * 60_000, retry: false } });
  return (lookups.data?.currencies ?? []).map((c) => c.code);
}

function NumberCell({
  value,
  label,
  disabled,
  onCommit,
  decimals = 2,
  min = 0,
}: {
  value: string | number | null;
  label: string;
  disabled: boolean;
  onCommit: (next: string) => void;
  decimals?: number;
  min?: number;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  const current = value === null ? "" : String(value);
  const commit = () => {
    if (draft === null) return;
    const next = draft.trim();
    setDraft(null);
    if (next === "" || Number(next) === Number(current)) return;
    onCommit(decimals ? Number(next).toFixed(decimals) : String(Math.round(Number(next))));
  };
  return (
    <InputNumber<string>
      aria-label={label}
      stringMode
      controls={false}
      disabled={disabled}
      min={String(min)}
      value={draft ?? current}
      formatter={groupDigits}
      parser={ungroup}
      onChange={(next) => {
        setDraft(next ?? "");
      }}
      onBlur={commit}
      onPressEnter={commit}
      className="pf-calc-input"
    />
  );
}

function useLineActions(sheet: CalcSheet) {
  const { message } = App.useApp();
  const apply = useApplySheet();
  const errorText = useErrorText();
  const number = calcRef(sheet.number);
  const onError = (error: unknown) => {
    void message.error(errorText(error));
  };
  const stockErrorText = useStockErrorText();
  const onStockError = (error: unknown) => {
    void message.error(stockErrorText(error));
  };
  const update = useUpdateCalcLine({ mutation: { onSuccess: apply, onError } });
  const reserve = useReserveCalcLine({ mutation: { onSuccess: apply, onError: onStockError } });
  const unreserve = useReleaseCalcLineReservation({
    mutation: { onSuccess: apply, onError: onStockError },
  });
  const sign = useSignCalcLine({ mutation: { onSuccess: apply, onError } });
  const remove = useDeleteCalcLine({ mutation: { onSuccess: apply, onError } });
  return {
    pending:
      update.isPending ||
      sign.isPending ||
      remove.isPending ||
      reserve.isPending ||
      unreserve.isPending,
    reserve: (line: CalcLine, quantity: number) => {
      reserve.mutate({ number, lineId: line.id, data: { quantity } });
    },
    release: (line: CalcLine) => {
      unreserve.mutate({ number, lineId: line.id });
    },
    patch: (line: CalcLine, data: CalcLinePatch) => {
      update.mutate({ number, lineId: line.id, data });
    },
    sign: (line: CalcLine) => {
      sign.mutate({ number, lineId: line.id });
    },
    remove: (line: CalcLine) => {
      remove.mutate({ number, lineId: line.id });
    },
  };
}

type Actions = ReturnType<typeof useLineActions>;

function Position({
  line,
  onMatch,
  actions,
}: {
  line: CalcLine;
  onMatch: () => void;
  actions: Actions;
}) {
  const { t } = useTranslation("calc");
  const hint = line.catalog_hint;
  return (
    <div className="pf-calc-position">
      <ItemRefCell
        item={line.item}
        name={line.name}
        kind={line.kind === "service" ? "service" : "goods"}
      />
      <span className="pf-calc-line-meta">
        {/* Наш артикул — в позиции; артикул изготовителя — только с полной подписью (стандарт §12 п. 6) */}
        {line.article && line.article !== line.item?.sku ? (
          <span className="pf-hint">
            {t("lines.mpn")} <span className="pf-num">{line.article}</span>
          </span>
        ) : null}
        <StatusTag kind="itemKind" status={line.kind}>
          {t(`lines.kind.${line.kind}`)}
        </StatusTag>
        {line.product_draft ? (
          <StatusTag kind="catalogItem" status="draft">
            {t("lines.draft")}
          </StatusTag>
        ) : null}
      </span>
      {hint && line.can_edit ? (
        // СЦ-10: строка похожа на позицию каталога — решает человек, черновик не заводится сам.
        <span className="pf-calc-hint">
          <span>{t("lines.hint", { name: hint.name })}</span>
          <Button
            type="link"
            size="small"
            className="pf-calc-link"
            disabled={actions.pending}
            onClick={() => {
              actions.patch(line, { product_id: hint.id });
            }}
            aria-label={t("lines.hintTakeLabel", { name: hint.name })}
          >
            {t("lines.hintTake")}
          </Button>
          <Button
            type="link"
            size="small"
            className="pf-calc-link"
            disabled={actions.pending}
            onClick={() => {
              actions.patch(line, { product_id: null });
            }}
            aria-label={t("lines.hintNewLabel", { name: line.name })}
          >
            {t("lines.hintNew")}
          </Button>
        </span>
      ) : null}
      {(line.product_id === null || line.product_draft) && line.can_edit && !hint ? (
        <Button
          type="link"
          size="small"
          className="pf-calc-link"
          onClick={onMatch}
          aria-label={t("lines.matchLabel", { name: line.name })}
        >
          {t("lines.match")}
        </Button>
      ) : null}
    </div>
  );
}

function Stock({
  line,
  canStock,
  actions,
}: {
  line: CalcLine;
  canStock: boolean;
  actions: Actions;
}) {
  const { t } = useTranslation("calc");
  if (line.zone === "services") return <span className="pf-hint">—</span>;
  if (line.stock.on_hand === null) return <span className="pf-hint">{t("lines.noStockData")}</span>;
  const reserved = line.stock.reserved ?? 0;
  const free = line.stock.free ?? null;
  // Сколько строка может удерживать: не больше её количества и свободного остатка плюс уже удерживаемого ею.
  const wanted = free === null ? 0 : Math.min(line.quantity, free + reserved);
  return (
    <div className="pf-calc-supplier">
      {line.stock.on_hand > 0 ? (
        <StatusTag kind="stock" status="free">
          {t("lines.inStock", { count: line.stock.on_hand })}
        </StatusTag>
      ) : (
        <StatusTag kind="stock" status="none">
          {t("lines.noStock")}
        </StatusTag>
      )}
      {line.stock.cell ? (
        <span className="pf-hint">{t("lines.cell", { cell: line.stock.cell })}</span>
      ) : null}
      {free !== null ? <span className="pf-hint">{t("lines.free", { count: free })}</span> : null}
      {reserved > 0 ? (
        <StatusTag kind="stock" status="reserved">
          {t("lines.reservedTag", { count: reserved })}
        </StatusTag>
      ) : null}
      {canStock && line.product_id !== null ? (
        <span className="pf-stock-reserve">
          {wanted > reserved ? (
            <Button
              size="small"
              disabled={actions.pending}
              aria-label={t("lines.reserveLabel", { count: wanted, name: line.name })}
              onClick={() => {
                actions.reserve(line, wanted);
              }}
            >
              {t("lines.reserve", { count: wanted })}
            </Button>
          ) : null}
          {reserved > 0 ? (
            <Button
              size="small"
              type="text"
              disabled={actions.pending}
              aria-label={t("lines.releaseLabel", { name: line.name })}
              onClick={() => {
                actions.release(line);
              }}
            >
              {t("lines.release")}
            </Button>
          ) : null}
        </span>
      ) : null}
    </div>
  );
}

function Supplier({ line }: { line: CalcLine }) {
  const { t } = useTranslation("calc");
  const { date, money } = useFormat();
  if (line.zone === "services") return <span className="pf-hint">{t("lines.service")}</span>;
  const supplier = line.supplier;
  if (!supplier) {
    return (
      <span className="pf-hint">
        {t("lines.noSupplier")}
        {line.lead_days ? ` · ${t("lines.days", { count: line.lead_days })}` : ""}
      </span>
    );
  }
  return (
    <div className="pf-calc-supplier">
      <span>
        {supplier.name}
        {supplier.lead_days ? ` · ${t("lines.days", { count: supplier.lead_days })}` : ""}
      </span>
      <span className="pf-hint">
        {supplier.price_valid_until
          ? t("lines.supplierHint", {
              qty: supplier.min_order_qty,
              date: date(supplier.price_valid_until),
            })
          : t("lines.supplierHintNoDate", { qty: supplier.min_order_qty })}
      </span>
      {supplier.offer_price ? (
        <span className="pf-hint">
          {t("lines.offerPrice", {
            price: money(supplier.offer_price, { currency: supplier.offer_currency }),
          })}
        </span>
      ) : null}
    </div>
  );
}

/** РАСЧ-1: откуда закупка — цена партнёра (от какой даты, до какой), выбор другой цены из короткого списка и «Запросить
 *  цену», когда действующей нет (истёкшая цена молча не берётся). */
function PartnerSource({
  line,
  actions,
  onRequestPrice,
}: {
  line: CalcLine;
  actions: Actions;
  onRequestPrice?: () => void;
}) {
  const { t } = useTranslation("calc");
  const { date, money } = useFormat();
  const part = line.partner_price;
  if (!part || line.zone === "services") return null;
  const source = part.source;
  const alternatives = part.options.length > 1;
  return (
    <div className="pf-calc-partner-source" data-testid="partner-source">
      {source ? (
        <span className="pf-hint">
          {source.valid_until
            ? t("partner.source", {
                name: source.supplier,
                from: date(source.price_date),
                until: date(source.valid_until),
              })
            : t("partner.sourceOpen", { name: source.supplier, from: date(source.price_date) })}
          {source.freshness === "expiring" ? ` · ${t("partner.expiring")}` : null}
          {source.freshness === "stale" ? ` · ${t("partner.stale")}` : null}
        </span>
      ) : null}
      {alternatives && line.can_edit ? (
        <Select
          size="small"
          aria-label={t("partner.pickLabel", { name: line.name })}
          placeholder={t("partner.pick")}
          value={source?.offer_id ?? null}
          disabled={actions.pending}
          popupMatchSelectWidth={false}
          optionLabelProp="short"
          options={part.options.map((option) => ({
            value: option.offer_id,
            short: option.supplier,
            label: t("partner.option", {
              name: option.supplier,
              price: money(option.price, { currency: option.currency }),
              until: option.valid_until ? date(option.valid_until) : t("partner.noDate"),
            }),
          }))}
          onChange={(offerId: string) => {
            if (offerId !== source?.offer_id) actions.patch(line, { offer_id: offerId });
          }}
          className="pf-calc-partner-pick"
        />
      ) : null}
      {!source && part.can_request ? (
        <span className="pf-hint">
          {part.expired
            ? t("partner.expired", {
                name: part.expired.supplier,
                until: date(part.expired.valid_until),
              })
            : t("partner.none")}
          {onRequestPrice && line.can_edit ? (
            <>
              {" "}
              <Button type="link" size="small" onClick={onRequestPrice}>
                {t("partner.request")}
              </Button>
            </>
          ) : null}
        </span>
      ) : null}
    </div>
  );
}

function Purchase({
  line,
  actions,
  onRequestPrice,
}: {
  line: CalcLine;
  actions: Actions;
  onRequestPrice?: () => void;
}) {
  const { t, i18n } = useTranslation("calc");
  const currencies = useCurrencyCodes();
  if (line.zone === "services") {
    // Ставку и дни бригады видит `cost_margin` или держатель зоны услуг; остальным — прочерк, а не пустые поля.
    if (
      !line.can_edit &&
      line.crew_rate === null &&
      line.crew_days === null &&
      line.cost === undefined
    ) {
      return <span className="pf-hint">{t("lines.hidden")}</span>;
    }
    return (
      <div className="pf-calc-crew">
        <label className="pf-calc-crew-field">
          <span className="pf-hint">{t("lines.crewRate")}</span>
          <NumberCell
            value={line.crew_rate}
            label={t("lines.crewLabel", { name: line.name })}
            disabled={!line.can_edit || actions.pending}
            onCommit={(next) => {
              actions.patch(line, { crew_rate: next });
            }}
          />
        </label>
        <label className="pf-calc-crew-field">
          <span className="pf-hint">{t("lines.crewDays")}</span>
          <NumberCell
            value={line.crew_days}
            label={t("lines.daysLabel", { name: line.name })}
            disabled={!line.can_edit || actions.pending}
            decimals={1}
            onCommit={(next) => {
              actions.patch(line, { crew_days: next });
            }}
          />
        </label>
        {line.cost !== undefined && line.cost !== null ? (
          <span className="pf-hint">
            = <MoneyText value={line.cost} currency={line.purchase_currency} />
          </span>
        ) : null}
      </div>
    );
  }
  if (line.purchase_price === undefined || line.purchase_price === null) {
    return <span className="pf-hint">{t("lines.hidden")}</span>;
  }
  const currency = line.purchase_currency ?? HOME_CURRENCY;
  return (
    <div className="pf-calc-purchase">
      <NumberCell
        value={line.purchase_price}
        label={t("lines.purchaseLabel", { name: line.name })}
        disabled={!line.can_edit || actions.pending}
        onCommit={(next) => {
          actions.patch(line, { purchase_price: next });
        }}
      />
      {/* Валюта закупки строки: новые строки берут валюту по умолчанию из настроек компании (часто USD), поэтому
          она видна и меняется здесь же — иначе сумма в сумах считалась в долларах (прод, ЗВ-2026-002). */}
      {line.can_edit ? (
        <Select
          size="small"
          aria-label={t("lines.currencyLabel", { name: line.name })}
          value={currency}
          disabled={actions.pending}
          popupMatchSelectWidth={false}
          options={(currencies.length ? currencies : [currency]).map((code) => ({
            value: code,
            label: currencyLabel(code, i18n.language),
          }))}
          onChange={(code: string) => {
            if (code !== currency) actions.patch(line, { purchase_currency: code });
          }}
          className="pf-calc-currency"
        />
      ) : (
        <span className="pf-hint">{currencyLabel(currency, i18n.language)}</span>
      )}
      <PartnerSource line={line} actions={actions} onRequestPrice={onRequestPrice} />
    </div>
  );
}

function Visa({ line, actions }: { line: CalcLine; actions: Actions }) {
  const { t } = useTranslation("calc");
  const group = t(`groups.${GROUP_OF[line.group]}`);
  if (line.visa) {
    return (
      <span className="pf-calc-visa">
        <StatusTag kind="visa" status="done">
          {t("lines.signedGroup", { group })}
        </StatusTag>
        <span className="pf-hint">{line.visa.by}</span>
        <span className="pf-sr-only">{t("lines.signed", { group, name: line.visa.by })}</span>
      </span>
    );
  }
  if (line.can_edit) {
    const pendingMatch = Boolean(line.catalog_hint);
    return (
      <span className="pf-calc-visa">
        <Button
          size="small"
          onClick={() => {
            actions.sign(line);
          }}
          disabled={actions.pending || pendingMatch}
          aria-label={t("lines.confirmLabel", { name: line.name })}
        >
          {t("lines.confirm")}
        </Button>
        {pendingMatch ? <span className="pf-hint">{t("lines.hintFirst")}</span> : null}
      </span>
    );
  }
  return (
    <StatusTag kind="visa" status="waiting">
      {t("lines.waits", { group })}
    </StatusTag>
  );
}

function Remove({ line, actions }: { line: CalcLine; actions: Actions }) {
  const { t } = useTranslation("calc");
  if (!line.can_edit) return null;
  return (
    <Popconfirm
      title={t("lines.removeConfirm", { name: line.name })}
      okText={t("lines.removeOk")}
      cancelText={t("lines.cancel")}
      onConfirm={() => {
        actions.remove(line);
      }}
    >
      <Button
        size="small"
        type="text"
        danger
        icon={<CrossIcon />}
        aria-label={t("lines.remove", { name: line.name })}
      />
    </Popconfirm>
  );
}

function ClientPrice({ line, actions }: { line: CalcLine; actions: Actions }) {
  const { t } = useTranslation("calc");
  return (
    <NumberCell
      value={line.client_price}
      label={t("lines.clientLabel", { name: line.name })}
      disabled={!line.can_edit || actions.pending}
      onCommit={(next) => {
        actions.patch(line, { client_price: next });
      }}
    />
  );
}

/**
 * Наценка строки (D26G-5): видна с доступом к себестоимости; правится там же, где цена клиенту. Введённая наценка —
 * цена из неё, округлённая до сума; введённая цена — хранится как есть, наценка пересчитывается из неё.
 */
function Markup({ line, actions }: { line: CalcLine; actions: Actions }) {
  const { t } = useTranslation("calc");
  if (!line.can_edit || line.cost === null || line.cost === undefined) {
    return <span className="pf-num">{line.markup_pct ?? "—"}</span>;
  }
  return (
    <NumberCell
      value={line.markup_pct ?? null}
      label={t("lines.markupLabel", { name: line.name })}
      disabled={actions.pending}
      onCommit={(next) => {
        actions.patch(line, { markup_pct: next });
      }}
    />
  );
}

/** Единицы справочника (ADR-0027 п. 10): код и название; нет доступа к справочнику — пусто, единица видна текстом. */
function useUnits(): { code: string; name: string }[] {
  const lookups = useGetCatalogLookups({ query: { staleTime: 10 * 60_000, retry: false } });
  return (lookups.data?.units ?? []).map((u) => ({ code: u.code, name: u.name }));
}

function Quantity({ line, actions }: { line: CalcLine; actions: Actions }) {
  const { t } = useTranslation("calc");
  const units = useUnits();
  return (
    <span className="pf-calc-qty">
      {/* ADR-0027 п. 9: количество дробное — до трёх знаков после запятой (12,5 т). */}
      <NumberCell
        value={line.quantity}
        label={t("lines.quantityLabel", { name: line.name })}
        disabled={!line.can_edit || actions.pending}
        decimals={3}
        min={0.001}
        onCommit={(next) => {
          actions.patch(line, { quantity: Number(next) });
        }}
      />
      {line.can_edit && units.length ? (
        <Select
          size="small"
          showSearch
          optionFilterProp="label"
          aria-label={t("lines.unitLabel", { name: line.name })}
          value={line.unit_code ?? undefined}
          placeholder={line.unit || t("lines.unitPick")}
          disabled={actions.pending}
          popupMatchSelectWidth={false}
          options={units.map((u) => ({ value: u.code, label: u.name }))}
          onChange={(code: string) => {
            if (code !== line.unit_code) actions.patch(line, { unit_code: code });
          }}
          className="pf-calc-unit"
        />
      ) : line.unit ? (
        <span className="pf-hint">{line.unit}</span>
      ) : null}
    </span>
  );
}

function Totals({ sheet, mobile }: { sheet: CalcSheet; mobile: boolean }) {
  const { t } = useTranslation("calc");
  const totals = sheet.totals;
  const purchase = totals.purchase;
  const markup = totals.markup_pct;
  if (mobile) {
    return (
      <div className="pf-calc-totals-mobile">
        <strong>
          {t("lines.totals")} ({t("lines.noVat")})
        </strong>
        {purchase !== undefined ? (
          <span>
            {t("lines.columns.purchase")}: <MoneyText value={purchase} />
          </span>
        ) : null}
        <span>
          {t("lines.columns.client")}: <MoneyText value={totals.client} />
        </span>
        {markup !== undefined && markup !== null ? (
          <span>
            {t("lines.columns.markup")}: <span className="pf-num">{markup}</span>
          </span>
        ) : null}
      </div>
    );
  }
  return (
    <tr className="pf-calc-totals">
      <th scope="row" colSpan={4}>
        {t("lines.totals")} <span className="pf-hint">· {t("lines.noVat")}</span>
      </th>
      <td className="pf-col-num">
        {purchase !== undefined ? <MoneyText value={purchase} currency={false} /> : "—"}
      </td>
      <td className="pf-col-num">
        <MoneyText value={totals.client} currency={false} strong />
      </td>
      <td className="pf-col-num">{markup ?? "—"}</td>
      <td colSpan={2} />
    </tr>
  );
}

/**
 * Таблица строк расчёта на всю ширину (SPEC-v3 §7.4): позиция и тип · кол-во · склад · поставщик и срок · закупка ·
 * клиенту · наценка · виза. Правит строку тот, у кого право её зоны (`can_edit`): товар — снабженец, услуга —
 * гл. инженер (ставка бригады и дни). Себестоимость и наценка — только при `rights.cost`. На телефоне — карточки.
 */
export function LinesTable({
  sheet,
  onRequestPrice,
}: {
  sheet: CalcSheet;
  onRequestPrice?: () => void;
}) {
  const { t } = useTranslation("calc");
  const { mobile } = useViewport();
  const actions = useLineActions(sheet);
  const [matching, setMatching] = useState<CalcLine | null>(null);
  const showMarkup = sheet.rights.cost;
  const canStock = sheet.rights.stock === true;

  const matchModal = matching ? (
    <MatchModal
      sheet={sheet}
      line={matching}
      onClose={() => {
        setMatching(null);
      }}
    />
  ) : null;

  if (sheet.lines.length === 0) {
    return <p className="pf-hint pf-calc-empty">{t("lines.empty")}</p>;
  }

  if (mobile) {
    return (
      <>
        <ul
          className="pf-calc-line-cards"
          aria-label={t("lines.caption", { number: sheet.number })}
        >
          {sheet.lines.map((line) => (
            <li key={line.id}>
              <div className="pf-calc-card-head">
                <Position
                  line={line}
                  actions={actions}
                  onMatch={() => {
                    setMatching(line);
                  }}
                />
                <Remove line={line} actions={actions} />
              </div>
              <div className="pf-calc-card-grid">
                <span className="pf-hint">{t("lines.columns.quantity")}</span>
                <Quantity line={line} actions={actions} />
                <span className="pf-hint">{t("lines.columns.stock")}</span>
                <Stock line={line} canStock={canStock} actions={actions} />
                <span className="pf-hint">{t("lines.columns.supplier")}</span>
                <Supplier line={line} />
                <span className="pf-hint">{t("lines.columns.purchase")}</span>
                <Purchase line={line} actions={actions} onRequestPrice={onRequestPrice} />
                <span className="pf-hint">{t("lines.columns.client")}</span>
                <ClientPrice line={line} actions={actions} />
                {showMarkup ? (
                  <>
                    <span className="pf-hint">{t("lines.columns.markup")}</span>
                    <Markup line={line} actions={actions} />
                  </>
                ) : null}
              </div>
              <div className="pf-calc-card-foot">
                <Visa line={line} actions={actions} />
              </div>
            </li>
          ))}
        </ul>
        <Totals sheet={sheet} mobile />
        {matchModal}
      </>
    );
  }

  return (
    <>
      <ScrollRegion label={t("lines.scroll")}>
        <table className="pf-calc-table pf-calc-lines">
          <caption className="pf-sr-only">{t("lines.caption", { number: sheet.number })}</caption>
          <thead>
            <tr>
              <th scope="col">{t("lines.columns.position")}</th>
              <th scope="col" className="pf-col-num">
                {t("lines.columns.quantity")}
              </th>
              <th scope="col">{t("lines.columns.stock")}</th>
              <th scope="col">{t("lines.columns.supplier")}</th>
              <th scope="col" className="pf-col-num">
                {t("lines.columns.purchase")}
              </th>
              <th scope="col" className="pf-col-num">
                {t("lines.columns.client")}
              </th>
              <th scope="col" className="pf-col-num">
                {t("lines.columns.markup")}
              </th>
              <th scope="col">{t("lines.columns.visa")}</th>
              <th scope="col">
                <span className="pf-sr-only">{t("lines.columns.action")}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sheet.lines.map((line) => (
              <tr key={line.id}>
                <td>
                  <Position
                    line={line}
                    actions={actions}
                    onMatch={() => {
                      setMatching(line);
                    }}
                  />
                </td>
                <td className="pf-col-num">
                  <Quantity line={line} actions={actions} />
                </td>
                <td>
                  <Stock line={line} canStock={canStock} actions={actions} />
                </td>
                <td>
                  <Supplier line={line} />
                </td>
                <td className="pf-col-num">
                  <Purchase line={line} actions={actions} onRequestPrice={onRequestPrice} />
                </td>
                <td className="pf-col-num">
                  <ClientPrice line={line} actions={actions} />
                </td>
                <td className="pf-col-num">
                  {showMarkup ? <Markup line={line} actions={actions} /> : "—"}
                </td>
                <td>
                  <Visa line={line} actions={actions} />
                </td>
                <td>
                  <Remove line={line} actions={actions} />
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <Totals sheet={sheet} mobile={false} />
          </tfoot>
        </table>
      </ScrollRegion>
      {matchModal}
    </>
  );
}
