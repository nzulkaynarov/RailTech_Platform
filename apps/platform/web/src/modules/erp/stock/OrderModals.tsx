import { App, Button, Input, InputNumber, Skeleton } from "antd";
import { Dialog } from "../../../shared/ui/Dialog";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { SupplierOrderDetail } from "../../../shared/api/generated/model";
import {
  useCancelSupplierOrder,
  useConfirmSupplierOrder,
  useGetSupplierOrder,
  useReceiveSupplierOrder,
  useSendSupplierOrder,
  useUpdateSupplierOrder,
} from "../../../shared/api/generated/platform-bff";
import { DateField } from "../../../shared/ui/DateField";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { FormSheet } from "../../../shared/ui/FormSheet";
import { clean, useErrorText, useRefreshStock } from "./api";
import { EMPTY_TRACE, type TraceDraft, needsTracking, traceFields, traceProblem } from "./trace";
import { ReceiveTracking } from "./Tracking";

const ref = (number: string) => encodeURIComponent(number);

function useAction(done: string) {
  const { t } = useTranslation("stock");
  const { message } = App.useApp();
  const refresh = useRefreshStock();
  const errorText = useErrorText();
  const [error, setError] = useState<string | null>(null);
  return {
    error,
    options: (onClose: () => void) => ({
      onSuccess: () => {
        setError(null);
        refresh();
        void message.success(t(done));
        onClose();
      },
      onError: (e: unknown) => {
        setError(errorText(e));
      },
    }),
  };
}

function Footer({
  onClose,
  submit,
  pending,
  danger = false,
  disabled = false,
}: {
  onClose: () => void;
  submit: { label: string; run: () => void };
  pending: boolean;
  danger?: boolean;
  disabled?: boolean;
}) {
  const { t } = useTranslation("stock");
  return [
    <Button key="cancel" onClick={onClose}>
      {t("common.cancel")}
    </Button>,
    <Button
      key="submit"
      type="primary"
      danger={danger}
      loading={pending}
      disabled={disabled}
      onClick={submit.run}
    >
      {submit.label}
    </Button>,
  ];
}

/** «Отправить поставщику»: письмо на почту поставщика (или на указанный адрес) и запись в журнале заказа. */
export function SendModal({ order, onClose }: { order: SupplierOrderDetail; onClose: () => void }) {
  const { t } = useTranslation("stock");
  const id = useId();
  const action = useAction("order.notice.sent");
  const [email, setEmail] = useState(order.supplier.email ?? "");
  const send = useSendSupplierOrder({ mutation: action.options(onClose) });
  const missing = !order.supplier.email && email.trim() === "";
  return (
    <Dialog
      open
      title={t("order.send.title", { number: order.number })}
      onCancel={onClose}
      footer={Footer({
        onClose,
        pending: send.isPending,
        disabled: missing,
        submit: {
          label: t("order.send.submit"),
          run: () => {
            const to = clean(email);
            send.mutate({
              orderNumber: ref(order.number),
              data: to && to !== order.supplier.email ? { to_email: to } : {},
            });
          },
        },
      })}
    >
      <div className="pf-calc-stack">
        <FormField
          id={id}
          label={t("order.send.email")}
          hint={order.supplier.email ? t("order.send.emailKnown") : t("order.send.emailMissing")}
        >
          <Input
            id={id}
            type="email"
            value={email}
            maxLength={254}
            aria-describedby={`${id}-hint`}
            onChange={(event) => {
              setEmail(event.target.value);
            }}
          />
        </FormField>
        <ErrorNote message={action.error} />
      </div>
    </Dialog>
  );
}

/** «Поставщик подтвердил»: ожидаемая дата поставки обязательна. */
export function ConfirmModal({
  order,
  onClose,
}: {
  order: SupplierOrderDetail;
  onClose: () => void;
}) {
  const { t } = useTranslation("stock");
  const id = useId();
  const action = useAction("order.notice.confirmed");
  const [date, setDate] = useState(order.expected_date ?? "");
  const confirm = useConfirmSupplierOrder({ mutation: action.options(onClose) });
  return (
    <Dialog
      open
      title={t("order.confirm.title", { number: order.number })}
      onCancel={onClose}
      footer={Footer({
        onClose,
        pending: confirm.isPending,
        disabled: date === "",
        submit: {
          label: t("order.confirm.submit"),
          run: () => {
            confirm.mutate({ orderNumber: ref(order.number), data: { expected_date: date } });
          },
        },
      })}
    >
      <div className="pf-calc-stack">
        <FormField id={id} label={t("order.confirm.date")} hint={t("order.confirm.dateHint")}>
          <DateField id={id} value={date} aria-describedby={`${id}-hint`} onChange={setDate} />
        </FormField>
        <ErrorNote message={action.error} />
      </div>
    </Dialog>
  );
}

/** «Отменить заказ»: только пока по нему ничего не принято. */
export function CancelModal({
  order,
  onClose,
}: {
  order: SupplierOrderDetail;
  onClose: () => void;
}) {
  const { t } = useTranslation("stock");
  const id = useId();
  const action = useAction("order.notice.cancelled");
  const [reason, setReason] = useState("");
  const cancel = useCancelSupplierOrder({ mutation: action.options(onClose) });
  return (
    <Dialog
      open
      title={t("order.cancel.title", { number: order.number })}
      onCancel={onClose}
      footer={Footer({
        onClose,
        pending: cancel.isPending,
        danger: true,
        submit: {
          label: t("order.cancel.submit"),
          run: () => {
            const text = clean(reason);
            cancel.mutate({ orderNumber: ref(order.number), data: text ? { reason: text } : {} });
          },
        },
      })}
    >
      <div className="pf-calc-stack">
        <FormField id={id} label={t("order.cancel.reason")}>
          <Input
            id={id}
            value={reason}
            maxLength={500}
            onChange={(event) => {
              setReason(event.target.value);
            }}
          />
        </FormField>
        <ErrorNote message={action.error} />
      </div>
    </Dialog>
  );
}

interface Draft {
  quantity: number;
  cell: string;
  trace: TraceDraft;
}

/** «Принять товар»: количество по строкам (частично или полностью), ячейка и накладная поставщика; остаток склада растёт. */
export function ReceiveModal({
  number,
  line,
  onClose,
}: {
  number: string;
  /** Строка, которую открыли из вкладки «Приёмка»: остальные не заполняются */
  line?: string;
  onClose: () => void;
}) {
  const { t } = useTranslation("stock");
  const docId = useId();
  const action = useAction("order.notice.received");
  const query = useGetSupplierOrder(ref(number));
  const receive = useReceiveSupplierOrder({ mutation: action.options(onClose) });
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [doc, setDoc] = useState("");
  const order = query.data;
  const open = (order?.lines ?? []).filter((l) => l.received_quantity < l.quantity);
  const draftOf = (id: string, left: number): Draft =>
    drafts[id] ?? {
      quantity: line === undefined || line === id ? left : 0,
      cell: "",
      trace: EMPTY_TRACE,
    };
  const picked = open
    .map((l) => ({ line: l, draft: draftOf(l.id, l.quantity - l.received_quantity) }))
    .filter((item) => item.draft.quantity > 0);
  // Серийные, партия и документ — до отправки (ADR-0021): чего не хватает, видно у строки.
  const problems = picked
    .map(({ line: l, draft }) => ({ l, problem: traceProblem(l, draft.trace, draft.quantity) }))
    .filter((p) => p.problem !== null);
  const [tried, setTried] = useState(false);
  return (
    <FormSheet
      layer="drawer"
      wide
      title={t("order.receive.title", { number })}
      submitLabel={t("order.receive.submit")}
      saving={receive.isPending}
      submitDisabled={picked.length === 0}
      onCancel={onClose}
      onSubmit={() => {
        setTried(true);
        if (problems.length > 0) return;
        const supplierDoc = clean(doc);
        receive.mutate({
          orderNumber: ref(number),
          data: {
            lines: picked.map(({ line: l, draft }) => ({
              order_line_id: l.id,
              quantity: draft.quantity,
              ...(clean(draft.cell) ? { cell: clean(draft.cell) } : {}),
              ...traceFields(l, draft.trace),
            })),
            ...(supplierDoc ? { supplier_doc: supplierDoc } : {}),
          },
        });
      }}
    >
      {!order ? (
        <Skeleton active paragraph={{ rows: 3 }} title={false} />
      ) : (
        <div className="pf-calc-stack">
          <p className="pf-hint">{t("order.receive.hint")}</p>
          <ul className="pf-stock-receive">
            {open.map((l) => {
              const left = l.quantity - l.received_quantity;
              const draft = draftOf(l.id, left);
              return (
                <li key={l.id}>
                  <div>
                    <strong>{l.name}</strong>
                    <div className="pf-hint">
                      {t("order.receive.left", { left, total: l.quantity })}
                    </div>
                  </div>
                  <InputNumber
                    min={0}
                    max={left}
                    value={draft.quantity}
                    aria-label={t("order.receive.quantityLabel", { name: l.name })}
                    onChange={(value) => {
                      setDrafts((prev) => ({
                        ...prev,
                        [l.id]: { ...draft, quantity: value ?? 0 },
                      }));
                    }}
                  />
                  <Input
                    value={draft.cell}
                    maxLength={32}
                    placeholder={t("order.receive.cell")}
                    aria-label={t("order.receive.cellLabel", { name: l.name })}
                    onChange={(event) => {
                      setDrafts((prev) => ({
                        ...prev,
                        [l.id]: { ...draft, cell: event.target.value },
                      }));
                    }}
                  />
                  {needsTracking(l) && draft.quantity > 0 ? (
                    <ReceiveTracking
                      line={l}
                      name={l.name}
                      quantity={draft.quantity}
                      draft={draft.trace}
                      onChange={(trace) => {
                        setDrafts((prev) => ({ ...prev, [l.id]: { ...draft, trace } }));
                      }}
                    />
                  ) : null}
                </li>
              );
            })}
          </ul>
          <FormField id={docId} label={t("order.receive.doc")}>
            <Input
              id={docId}
              value={doc}
              maxLength={100}
              onChange={(event) => {
                setDoc(event.target.value);
              }}
            />
          </FormField>
          <ErrorNote
            message={
              tried && problems[0]
                ? t(`trace.problem.${problems[0].problem ?? "serials"}`, {
                    name: problems[0].l.name,
                  })
                : action.error
            }
          />
        </div>
      )}
    </FormSheet>
  );
}

/** Правка черновика: ожидаемая дата, внутреннее примечание, комментарий партнёру, количество и цена по строкам, удаление
 * строк. Цена уходит только у строк, где её меняли: без права на цены сотрудник видит пустую цену и не стирает чужую. */
export function EditModal({ order, onClose }: { order: SupplierOrderDetail; onClose: () => void }) {
  const { t } = useTranslation("stock");
  const dateId = useId();
  const noteId = useId();
  const partnerNoteId = useId();
  const action = useAction("order.notice.edited");
  const [date, setDate] = useState(order.expected_date ?? "");
  const [note, setNote] = useState(order.note);
  const [partnerNote, setPartnerNote] = useState(order.partner_note);
  const [quantities, setQuantities] = useState<Record<string, number>>({});
  const [prices, setPrices] = useState<Record<string, string>>({});
  const [removed, setRemoved] = useState<Set<string>>(new Set());
  const update = useUpdateSupplierOrder({ mutation: action.options(onClose) });
  const kept = order.lines.filter((l) => !removed.has(l.id));
  return (
    <FormSheet
      layer="drawer"
      wide
      title={t("order.edit.title", { number: order.number })}
      submitLabel={t("order.edit.submit")}
      saving={update.isPending}
      submitDisabled={kept.length === 0}
      onCancel={onClose}
      onSubmit={() => {
        update.mutate({
          orderNumber: ref(order.number),
          data: {
            expected_date: date === "" ? null : date,
            note,
            partner_note: partnerNote,
            lines: kept.map((l) => ({
              id: l.id,
              product_id: l.product_id ?? "",
              quantity: quantities[l.id] ?? l.quantity,
              ...(l.id in prices ? { unit_price: clean(prices[l.id]) ?? null } : {}),
            })),
          },
        });
      }}
    >
      <div className="pf-calc-stack">
        <FormField id={dateId} label={t("order.edit.date")}>
          <DateField id={dateId} value={date} onChange={setDate} />
        </FormField>
        <FormField id={noteId} label={t("order.edit.note")} hint={t("create.noteHint")}>
          <Input
            id={noteId}
            value={note}
            maxLength={5000}
            aria-describedby={`${noteId}-hint`}
            onChange={(event) => {
              setNote(event.target.value);
            }}
          />
        </FormField>
        <FormField
          id={partnerNoteId}
          label={t("order.edit.partnerNote")}
          hint={t("create.partnerNoteHint")}
        >
          <Input.TextArea
            id={partnerNoteId}
            value={partnerNote}
            maxLength={5000}
            aria-describedby={`${partnerNoteId}-hint`}
            autoSize={{ minRows: 2, maxRows: 6 }}
            onChange={(event) => {
              setPartnerNote(event.target.value);
            }}
          />
        </FormField>
        <ul
          className={
            order.rights.prices ? "pf-stock-receive pf-stock-receive--priced" : "pf-stock-receive"
          }
        >
          {kept.map((l) => (
            <li key={l.id}>
              <strong>{l.name}</strong>
              <InputNumber
                min={0.001}
                value={quantities[l.id] ?? l.quantity}
                aria-label={t("order.edit.quantityLabel", { name: l.name })}
                onChange={(value) => {
                  setQuantities((prev) => ({ ...prev, [l.id]: value ?? l.quantity }));
                }}
              />
              {order.rights.prices ? (
                <Input
                  inputMode="decimal"
                  placeholder={t("order.edit.price")}
                  value={prices[l.id] ?? l.unit_price ?? ""}
                  aria-label={t("order.edit.priceLabel", { name: l.name })}
                  onChange={(event) => {
                    setPrices((prev) => ({ ...prev, [l.id]: event.target.value }));
                  }}
                />
              ) : null}
              <Button
                danger
                type="text"
                disabled={kept.length === 1}
                aria-label={t("order.edit.removeLabel", { name: l.name })}
                onClick={() => {
                  setRemoved((prev) => new Set(prev).add(l.id));
                }}
              >
                {t("order.edit.remove")}
              </Button>
            </li>
          ))}
        </ul>
        <ErrorNote message={action.error} />
      </div>
    </FormSheet>
  );
}
