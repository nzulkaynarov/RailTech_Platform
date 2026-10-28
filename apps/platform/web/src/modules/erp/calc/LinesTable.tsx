import { App, Button, InputNumber, Popconfirm } from "antd";
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

const KIND_TONE = { goods: "blue", goods_to_order: "purple", service: "cyan" } as const;
const GROUP_OF = { stock: "stock", supply: "supply", engineer: "engineer" } as const;

/** Число с пробелами тысяч в поле ввода; в API уходит без пробелов. */
const groupDigits = (value: string | number | undefined) =>
  value === undefined ? "" : String(value).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
const ungroup = (value: string | undefined) => (value ?? "").replace(/\s/g, "");

/** Поле суммы или количества: сохраняется по Enter и при уходе из поля, если значение изменилось. */
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

function Position({ line, onMatch }: { line: CalcLine; onMatch: () => void }) {
  const { t } = useTranslation("calc");
  return (
    <div className="pf-calc-position">
      <span className="pf-calc-line-name">{line.name}</span>
      <span className="pf-calc-line-meta">
        {line.article ? <span className="pf-hint pf-num">{line.article}</span> : null}
        <StatusTag tone={KIND_TONE[line.kind]}>{t(`lines.kind.${line.kind}`)}</StatusTag>
      </span>
      {line.product_id === null && line.can_edit ? (
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
        <StatusTag tone="green">{t("lines.inStock", { count: line.stock.on_hand })}</StatusTag>
      ) : (
        <StatusTag tone="default">{t("lines.noStock")}</StatusTag>
      )}
      {line.stock.cell ? (
        <span className="pf-hint">{t("lines.cell", { cell: line.stock.cell })}</span>
      ) : null}
      {free !== null ? <span className="pf-hint">{t("lines.free", { count: free })}</span> : null}
      {reserved > 0 ? (
        <StatusTag tone="blue">{t("lines.reservedTag", { count: reserved })}</StatusTag>
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
          {t("lines.offerPrice", { price: money(supplier.offer_price) })}
        </span>
      ) : null}
    </div>
  );
}

function Purchase({ line, actions }: { line: CalcLine; actions: Actions }) {
  const { t } = useTranslation("calc");
  const { money } = useFormat();
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
          <span className="pf-hint pf-num">= {money(line.cost)}</span>
        ) : null}
      </div>
    );
  }
  if (line.purchase_price === undefined || line.purchase_price === null) {
    return <span className="pf-hint">{t("lines.hidden")}</span>;
  }
  return (
    <NumberCell
      value={line.purchase_price}
      label={t("lines.purchaseLabel", { name: line.name })}
      disabled={!line.can_edit || actions.pending}
      onCommit={(next) => {
        actions.patch(line, { purchase_price: next });
      }}
    />
  );
}

function Visa({ line, actions }: { line: CalcLine; actions: Actions }) {
  const { t } = useTranslation("calc");
  const group = t(`groups.${GROUP_OF[line.group]}`);
  if (line.visa) {
    return (
      <span className="pf-calc-visa">
        <StatusTag tone="green">{t("lines.signedGroup", { group })}</StatusTag>
        <span className="pf-hint">{line.visa.by}</span>
        <span className="pf-sr-only">{t("lines.signed", { group, name: line.visa.by })}</span>
      </span>
    );
  }
  if (line.can_edit) {
    return (
      <Button
        size="small"
        onClick={() => {
          actions.sign(line);
        }}
        disabled={actions.pending}
        aria-label={t("lines.confirmLabel", { name: line.name })}
      >
        {t("lines.confirm")}
      </Button>
    );
  }
  return <StatusTag tone="gold">{t("lines.waits", { group })}</StatusTag>;
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

function Quantity({ line, actions }: { line: CalcLine; actions: Actions }) {
  const { t } = useTranslation("calc");
  return (
    <span className="pf-calc-qty">
      <NumberCell
        value={line.quantity}
        label={t("lines.quantityLabel", { name: line.name })}
        disabled={!line.can_edit || actions.pending}
        decimals={0}
        min={1}
        onCommit={(next) => {
          actions.patch(line, { quantity: Number(next) });
        }}
      />
      {line.unit ? <span className="pf-hint">{line.unit}</span> : null}
    </span>
  );
}

function Totals({ sheet, mobile }: { sheet: CalcSheet; mobile: boolean }) {
  const { t } = useTranslation("calc");
  const { money } = useFormat();
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
            {t("lines.columns.purchase")}: <span className="pf-num">{money(purchase)}</span>
          </span>
        ) : null}
        <span>
          {t("lines.columns.client")}: <span className="pf-num">{money(totals.client)}</span>
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
      <td className="pf-num">
        {purchase !== undefined ? money(purchase, { currency: false }) : "—"}
      </td>
      <td className="pf-num">
        <strong>{money(totals.client, { currency: false })}</strong>
      </td>
      <td className="pf-num">{markup ?? "—"}</td>
      <td colSpan={2} />
    </tr>
  );
}

/**
 * Таблица строк расчёта на всю ширину (SPEC-v3 §7.4): позиция и тип · кол-во · склад · поставщик и срок · закупка ·
 * клиенту · наценка · виза. Правит строку тот, у кого право её зоны (`can_edit`): товар — снабженец, услуга —
 * гл. инженер (ставка бригады и дни). Себестоимость и наценка — только при `rights.cost`. На телефоне — карточки.
 */
export function LinesTable({ sheet }: { sheet: CalcSheet }) {
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
                <Purchase line={line} actions={actions} />
                <span className="pf-hint">{t("lines.columns.client")}</span>
                <ClientPrice line={line} actions={actions} />
                {showMarkup ? (
                  <>
                    <span className="pf-hint">{t("lines.columns.markup")}</span>
                    <span className="pf-num">{line.markup_pct ?? "—"}</span>
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
              <th scope="col">{t("lines.columns.quantity")}</th>
              <th scope="col">{t("lines.columns.stock")}</th>
              <th scope="col">{t("lines.columns.supplier")}</th>
              <th scope="col">{t("lines.columns.purchase")}</th>
              <th scope="col">{t("lines.columns.client")}</th>
              <th scope="col">{t("lines.columns.markup")}</th>
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
                    onMatch={() => {
                      setMatching(line);
                    }}
                  />
                </td>
                <td>
                  <Quantity line={line} actions={actions} />
                </td>
                <td>
                  <Stock line={line} canStock={canStock} actions={actions} />
                </td>
                <td>
                  <Supplier line={line} />
                </td>
                <td>
                  <Purchase line={line} actions={actions} />
                </td>
                <td>
                  <ClientPrice line={line} actions={actions} />
                </td>
                <td className="pf-num">{showMarkup ? (line.markup_pct ?? "—") : "—"}</td>
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
