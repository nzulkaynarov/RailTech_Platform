import { App, Button, Input, Segmented, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import type {
  CatalogIssueField,
  CatalogItem,
  CatalogItemDetail,
  CatalogReturnIssue,
} from "../../../shared/api/generated/model";
import {
  getGetCatalogItemQueryKey,
  getListCatalogItemsQueryKey,
  useListCatalogItems,
  useReturnCatalogItem,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { FormField } from "../../../shared/ui/FormParts";
import { MoneyText } from "../../../shared/ui/MoneyText";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { FormModal } from "./common";
import { errorFields } from "./errors";

/** Поля замечаний при возврате карточки: перечень ERP (`catalog.models.reviews.ISSUE_FIELDS`), подписи — `catalog:review.issueFields`. */
const ISSUE_FIELDS: readonly CatalogIssueField[] = [
  "name",
  "description",
  "brand",
  "manufacturer_part_number",
  "gost_drawing",
  "category",
  "uom",
  "hs_code",
  "price",
  "valid_until",
  "other",
];

/** Сколько карточек ждут проверки: один запрос на строку счётчика (страница размером 1, берётся `total`). */
function useWaitingCount(): number | undefined {
  const query = useListCatalogItems({ review: "waiting", page: 1, page_size: 1 });
  return query.data?.total;
}

/** Переключатель «Все позиции / Ждут проверки · N»: адрес хранит только `?review=waiting`. */
export function QueueSwitch({
  waiting,
  onChange,
}: {
  waiting: boolean;
  onChange: (waiting: boolean) => void;
}) {
  const { t } = useTranslation("catalog");
  const count = useWaitingCount();
  return (
    <Segmented
      aria-label={t("queue.view")}
      value={waiting ? "waiting" : "all"}
      onChange={(value) => {
        onChange(value === "waiting");
      }}
      options={[
        { value: "all", label: t("queue.all") },
        {
          value: "waiting",
          label: count === undefined ? t("queue.waiting") : t("queue.waitingCount", { count }),
        },
      ]}
    />
  );
}

/** Срок ответа словом: дата и «Просрочено» или «В срок» (статус всегда словом, правило 7). */
export function DueCell({ item }: { item: Pick<CatalogItem, "review"> }) {
  const { t } = useTranslation("catalog");
  const { date } = useFormat();
  const review = item.review;
  if (!review) return <>—</>;
  return (
    <>
      {date(review.due_at, "datetime")}{" "}
      <StatusTag kind="validity" status={review.overdue ? "expired" : "ok"}>
        {review.overdue ? t("queue.overdue") : t("queue.inTime")}
      </StatusTag>
    </>
  );
}


/** «Цена в каталоге»: что покажет каталог клиенту и по чьей настройке (карточка, партнёр, компания). */
export function CatalogPriceValue({ card }: { card: CatalogItemDetail }) {
  const { t } = useTranslation("catalog");
  const { catalog_price: shown } = card;
  const source = t(`catalogPrice.source.${shown.source}`);
  return (
    <>
      {shown.price ? (
        <MoneyText value={shown.price.amount} currency={shown.price.currency} />
      ) : shown.visibility === "cabinet" ? (
        t("catalogPrice.notSet")
      ) : (
        t("catalogPrice.onRequest")
      )}
      <span className="pf-cat-sub">{source}</span>
    </>
  );
}

/** Блок «Проверка карточки»: кто прислал, когда, срок и полнота. Решения — кнопки рядом с карточкой. */
export function ReviewBlock({ card }: { card: CatalogItemDetail }) {
  const { t } = useTranslation("catalog");
  const { date } = useFormat();
  const review = card.review;
  if (!review) return null;
  return (
    <section aria-labelledby={`review-${card.id}`}>
      <h3 className="pf-cat-section" id={`review-${card.id}`}>
        {t("review.title")}
      </h3>
      <DefinitionList
        items={[
          { label: t("review.kind"), value: t(`queue.kind.${review.kind}`) },
          { label: t("review.partner"), value: review.partner?.name },
          { label: t("review.sent"), value: date(review.submitted_at, "datetime") },
          { label: t("review.due"), value: <DueCell item={{ review }} /> },
          {
            label: t("review.completeness"),
            value: card.completeness === null ? "—" : `${String(card.completeness)} %`,
          },
        ]}
      />
      {review.kind === "changes" ? <p className="pf-cat-note">{t("review.changesNote")}</p> : null}
    </section>
  );
}

interface IssueDraft {
  key: number;
  field: CatalogIssueField | null;
  comment: string;
}

/** «Вернуть партнёру»: общий комментарий и замечания по полям; нужна хотя бы одна причина. */
export function ReturnModal({ card, onClose }: { card: CatalogItemDetail; onClose: () => void }) {
  const { t } = useTranslation("catalog");
  const { message } = App.useApp();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [issues, setIssues] = useState<IssueDraft[]>([]);
  const [next, setNext] = useState(1);
  const reasonId = useId();
  const mutation = useReturnCatalogItem({
    mutation: {
      onSuccess: (saved) => {
        queryClient.setQueryData(getGetCatalogItemQueryKey(saved.id), saved);
        void queryClient.invalidateQueries({ queryKey: getListCatalogItemsQueryKey() });
        void message.success(t("review.returned"));
        onClose();
      },
    },
  });
  const complete = issues.filter((i) => i.field !== null && i.comment.trim() !== "");
  const halfFilled = issues.some((i) => (i.field === null) !== (i.comment.trim() === ""));
  const valid = !halfFilled && (reason.trim() !== "" || complete.length > 0);
  const fields = errorFields(mutation.error);
  const update = (key: number, patch: Partial<IssueDraft>) => {
    setIssues((rows) => rows.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  };
  const submit = () => {
    const sent: CatalogReturnIssue[] = complete.flatMap((i) =>
      i.field ? [{ field: i.field, comment: i.comment.trim() }] : [],
    );
    mutation.mutate({
      id: card.id,
      data: {
        ...(reason.trim() ? { reason: reason.trim() } : {}),
        ...(sent.length ? { issues: sent } : {}),
      },
    });
  };
  return (
    <FormModal
      title={t("review.form.title")}
      okLabel={t("review.form.ok")}
      items={t("review.form.steps", { returnObjects: true }) as string[]}
      loading={mutation.isPending}
      error={mutation.error}
      disabled={!valid}
      onOk={submit}
      onCancel={onClose}
    >
      <FormField id={reasonId} label={t("review.form.reason")} hint={t("review.form.reasonHint")}>
        <Input.TextArea
          id={reasonId}
          rows={3}
          maxLength={2000}
          value={reason}
          status={fields.includes("reason") ? "error" : undefined}
          aria-describedby={`${reasonId}-hint`}
          onChange={(event) => {
            setReason(event.target.value);
          }}
        />
      </FormField>
      <fieldset className="pf-cat-issues">
        <legend>{t("review.form.issues")}</legend>
        {issues.map((issue, index) => (
          <IssueRow
            key={issue.key}
            index={index + 1}
            issue={issue}
            onChange={(patch) => {
              update(issue.key, patch);
            }}
            onRemove={() => {
              setIssues((rows) => rows.filter((row) => row.key !== issue.key));
            }}
          />
        ))}
        <Button
          disabled={issues.length >= 30}
          onClick={() => {
            setIssues((rows) => [...rows, { key: next, field: null, comment: "" }]);
            setNext(next + 1);
          }}
        >
          {t("review.form.add")}
        </Button>
      </fieldset>
    </FormModal>
  );
}

function IssueRow({
  index,
  issue,
  onChange,
  onRemove,
}: {
  index: number;
  issue: IssueDraft;
  onChange: (patch: Partial<IssueDraft>) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation("catalog");
  const fieldId = useId();
  const commentId = useId();
  return (
    <div className="pf-cat-issue">
      <FormField id={fieldId} label={`${t("review.form.field")} ${String(index)}`}>
        <Select
          id={fieldId}
          value={issue.field ?? undefined}
          placeholder={t("review.form.fieldPlaceholder")}
          onChange={(value: CatalogIssueField) => {
            onChange({ field: value });
          }}
          options={ISSUE_FIELDS.map((field) => ({
            value: field,
            label: t(`review.issueFields.${field}`),
          }))}
        />
      </FormField>
      <FormField id={commentId} label={`${t("review.form.comment")} ${String(index)}`}>
        <Input
          id={commentId}
          maxLength={500}
          value={issue.comment}
          onChange={(event) => {
            onChange({ comment: event.target.value });
          }}
        />
      </FormField>
      <Button aria-label={t("review.form.remove", { n: index })} onClick={onRemove}>
        ×
      </Button>
    </div>
  );
}

/** Кнопка «Вернуть партнёру» с окном возврата; видна только у карточки на проверке. */
export function ReturnButton({ card }: { card: CatalogItemDetail }) {
  const { t } = useTranslation("catalog");
  const [open, setOpen] = useState(false);
  if (card.status !== "REVIEW") return null;
  return (
    <>
      <Button
        onClick={() => {
          setOpen(true);
        }}
      >
        {t("review.return")}
      </Button>
      {open ? (
        <ReturnModal
          card={card}
          onClose={() => {
            setOpen(false);
          }}
        />
      ) : null}
    </>
  );
}
