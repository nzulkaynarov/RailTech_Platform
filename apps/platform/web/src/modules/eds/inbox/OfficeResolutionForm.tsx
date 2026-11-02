import { App, Button, Input, Radio, Select } from "antd";
import { type FormEvent, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import type { LetterCard, LetterResolutionKind } from "../../../shared/api/generated/model";
import {
  useListEdsStaff,
  useRejectLetter,
  useResolveOfficeLetter,
  useReturnLetter,
  useSaveResolutionDraft,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { DateField } from "../../../shared/ui/DateField";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { useResolutionKindName } from "../dictionaries";
import { companyDate, fieldsOf, reasonOf, useRefreshLetters } from "./api";
import {
  type OfficeErrors,
  type OfficeField,
  type OfficeValues,
  RESOLUTION_KINDS,
  draftAsResolution,
  initialOffice,
  needsExecutor,
  switchKind,
  toDraftBody,
  toOfficeBody,
  validateDraft,
  validateOffice,
} from "./officeModel";
import { ResolutionTemplatePicker } from "./ResolutionTemplatePicker";

type Action = "resolve" | "approve" | "draft" | "return" | "reject";
const ORDER: readonly OfficeField[] = ["kind", "responsible", "due", "text"];

export interface OfficeResolutionFormProps {
  letter: LetterCard;
  /** `resolve` — директор накладывает резолюцию; `draft` — делопроизводитель готовит проект */
  mode: "resolve" | "draft";
  variant?: "panel" | "sheet";
  onDone?: () => void;
}

/**
 * Резолюция пути делопроизводства (P8b, SPEC-v3 §3.2a п. 2): К исполнению · Подготовить ответ · Для сведения; ответственный —
 * любой активный сотрудник (`GET /eds/staff`), срок с подсказкой EDS, текст по шаблону типа, соисполнители и «ознакомить».
 * Проект делопроизводителя директор утверждает одним нажатием («Утвердить проект») или правит. Делопроизводитель в этой же
 * форме сохраняет проект. Вернуть и отклонить — с комментарием, как в резолюции заявки.
 */
export function OfficeResolutionForm({
  letter,
  mode,
  variant = "panel",
  onDone,
}: OfficeResolutionFormProps) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const { message } = App.useApp();
  const refresh = useRefreshLetters();
  const ids = useId();
  const id = (name: string) => `${ids}-${name}`;
  const template = (kind: LetterResolutionKind) => t(`office.template.${kind}`);
  const [values, setValues] = useState<OfficeValues>(() => initialOffice(letter, template));
  const [errors, setErrors] = useState<OfficeErrors>({});
  const [comment, setComment] = useState("");
  const [failure, setFailure] = useState<unknown>(null);
  const staff = useListEdsStaff({ query: { staleTime: 5 * 60_000 } });
  const kindName = useResolutionKindName();
  const today = companyDate();
  const draft = letter.resolution_draft;
  const approvable = mode === "resolve" ? draftAsResolution(letter, today) : null;

  const done = (action: Action) => {
    void refresh();
    // «Для сведения» (своё или утверждённый проект) — «Письмо принято к сведению»
    const kind = action === "approve" ? draft?.kind : values.kind;
    const key =
      action === "approve" || action === "resolve"
        ? kind === "info"
          ? "info"
          : "resolve"
        : action;
    void message.success(t(`office.done.${key}`));
    onDone?.();
  };
  const failed = (error: unknown) => {
    setFailure(error);
    const named = fieldsOf(error);
    setErrors((prev) => ({
      ...prev,
      ...(named.includes("due") ? { due: "past" as const } : {}),
      ...(named.some((f) => f.startsWith("responsible"))
        ? { responsible: "required" as const }
        : {}),
    }));
  };
  const handlers = (action: Action) => ({
    mutation: {
      onSuccess: () => {
        done(action);
      },
      onError: failed,
    },
  });
  const resolve = useResolveOfficeLetter(handlers("resolve"));
  const approve = useResolveOfficeLetter(handlers("approve"));
  const saveDraft = useSaveResolutionDraft(handlers("draft"));
  const sendBack = useReturnLetter(handlers("return"));
  const reject = useRejectLetter(handlers("reject"));
  const busy =
    resolve.isPending ||
    approve.isPending ||
    saveDraft.isPending ||
    sendBack.isPending ||
    reject.isPending;

  const patch = (change: Partial<OfficeValues>, clear: readonly OfficeField[] = []) => {
    setValues((prev) => ({ ...prev, ...change }));
    setFailure(null);
    if (clear.length > 0) {
      setErrors((prev) =>
        Object.fromEntries(
          Object.entries(prev).filter(([key]) => !clear.includes(key as OfficeField)),
        ),
      );
    }
  };

  const people = (staff.data?.items ?? []).map((p) => ({
    value: p.id,
    label: p.position ? `${p.name} · ${p.position}` : p.name,
  }));
  const executor = needsExecutor(values.kind);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setFailure(null);
    const found = mode === "draft" ? validateDraft(values, today) : validateOffice(values, today);
    setErrors(found);
    const first = ORDER.find((key) => found[key]);
    if (first) {
      window.setTimeout(() => document.getElementById(id(first))?.focus(), 0);
      return;
    }
    if (mode === "draft") saveDraft.mutate({ id: letter.id, data: toDraftBody(values) });
    else resolve.mutate({ id: letter.id, data: toOfficeBody(values) });
  };

  const errorText = (field: OfficeField) => {
    const kind = errors[field];
    if (!kind) return null;
    const key = field === "due" && kind === "past" ? "duePast" : field;
    return (
      <span className="pf-res-error" id={id(`${field}-error`)} role="alert">
        {t(`office.errors.${key}`)}
      </span>
    );
  };
  const described = (field: OfficeField) =>
    errors[field] ? id(`${field}-error`) : id(`${field}-hint`);

  const failureText = failure
    ? t("office.failed", { reason: t(`form.reasons.${reasonOf(failure)}`) })
    : null;
  const consequence =
    mode === "draft"
      ? (t("office.consequence.draft", { returnObjects: true }) as string[])
      : (t(`office.consequence.${values.kind === "info" ? "info" : "execute"}`, {
          returnObjects: true,
        }) as string[]);
  const trimmed = comment.trim();

  return (
    <form
      className={`pf-res pf-res--${variant}`}
      aria-label={mode === "draft" ? t("office.draftName") : t("office.name")}
      noValidate
      onSubmit={submit}
    >
      {mode === "draft" ? <p className="pf-hint">{t("office.draftIntro")}</p> : null}
      {mode === "resolve" && draft?.kind ? (
        <div className="pf-res-note" role="status">
          <span>
            {t("office.draftBy", {
              name: draft.drafted_by.name,
              date: date(draft.drafted_at, "datetime"),
            })}
          </span>
          {approvable ? (
            <Button
              type="primary"
              loading={approve.isPending}
              disabled={busy}
              onClick={() => {
                setFailure(null);
                approve.mutate({ id: letter.id, data: approvable });
              }}
            >
              {t("office.approve")}
            </Button>
          ) : null}
        </div>
      ) : null}

      <ResolutionTemplatePicker
        letter={letter}
        values={values}
        idPrefix={ids}
        onApply={(next) => {
          setValues(next);
          setErrors({});
          setFailure(null);
        }}
      />

      <fieldset className="pf-res-fieldset">
        <legend id={id("kind-legend")}>{t("office.kind.legend")}</legend>
        <Radio.Group
          id={id("kind")}
          aria-labelledby={id("kind-legend")}
          value={values.kind || undefined}
          onChange={(event) => {
            const kind = event.target.value as LetterResolutionKind;
            setValues((prev) => switchKind(prev, kind, template, letter.suggested_due));
            setErrors({});
            setFailure(null);
          }}
        >
          <div className="pf-res-kinds">
            {RESOLUTION_KINDS.map((kind) => (
              <Radio key={kind} value={kind}>
                <span className="pf-res-zone-name">{kindName(kind)}</span>
                <span className="pf-hint"> — {t(`office.kindHint.${kind}`)}</span>
              </Radio>
            ))}
          </div>
        </Radio.Group>
        {errorText("kind")}
      </fieldset>

      {staff.isError ? (
        <div className="pf-res-note" role="status">
          <span>{t("office.staff.unavailable")}</span>
          <Button
            size="small"
            onClick={() => {
              void staff.refetch();
            }}
          >
            {t("office.staff.retry")}
          </Button>
        </div>
      ) : null}

      {executor ? (
        <>
          <FormField
            id={id("responsible")}
            label={t("office.responsible.label")}
            hint={errors.responsible ? undefined : t("office.responsible.hint")}
          >
            <Select
              id={id("responsible")}
              className="pf-res-select"
              value={values.responsibleId || undefined}
              placeholder={t("office.responsible.choose")}
              loading={staff.isPending}
              showSearch
              optionFilterProp="label"
              options={people}
              status={errors.responsible ? "error" : undefined}
              aria-invalid={errors.responsible ? true : undefined}
              aria-describedby={described("responsible")}
              onChange={(value: string) => {
                patch({ responsibleId: value }, ["responsible"]);
              }}
            />
            {errorText("responsible")}
          </FormField>
          <FormField
            id={id("due")}
            label={t("office.due.label")}
            hint={
              errors.due
                ? undefined
                : letter.suggested_due
                  ? t("office.due.hint", { date: date(letter.suggested_due) })
                  : t("office.due.hintNone")
            }
          >
            <DateField
              id={id("due")}
              value={values.due}
              min={today}
              status={errors.due ? "error" : undefined}
              aria-invalid={errors.due ? true : undefined}
              aria-describedby={described("due")}
              onChange={(next) => {
                patch({ due: next }, ["due"]);
              }}
            />
            {errorText("due")}
          </FormField>
        </>
      ) : null}

      <FormField
        id={id("text")}
        label={t("office.text.label")}
        hint={errors.text ? undefined : t("office.text.hint")}
      >
        <Input.TextArea
          id={id("text")}
          value={values.text}
          maxLength={4000}
          autoSize={{ minRows: 2, maxRows: 8 }}
          status={errors.text ? "error" : undefined}
          aria-invalid={errors.text ? true : undefined}
          aria-describedby={described("text")}
          onChange={(event) => {
            patch({ text: event.target.value, templated: false }, ["text"]);
          }}
        />
        {errorText("text")}
      </FormField>

      {executor ? (
        <FormField id={id("co")} label={t("office.co.label")} hint={t("office.co.hint")}>
          <Select
            id={id("co")}
            mode="multiple"
            className="pf-res-select"
            value={values.coIds}
            placeholder={t("office.choosePeople")}
            optionFilterProp="label"
            options={people.filter((p) => p.value !== values.responsibleId)}
            aria-describedby={id("co-hint")}
            onChange={(next: string[]) => {
              patch({ coIds: next });
            }}
          />
        </FormField>
      ) : null}
      <FormField
        id={id("acquaint")}
        label={t("office.acquaint.label")}
        hint={t("office.acquaint.hint")}
      >
        <Select
          id={id("acquaint")}
          mode="multiple"
          className="pf-res-select"
          value={values.acquaintIds}
          placeholder={t("office.choosePeople")}
          optionFilterProp="label"
          options={people}
          aria-describedby={id("acquaint-hint")}
          onChange={(next: string[]) => {
            patch({ acquaintIds: next });
          }}
        />
      </FormField>

      <Consequence title={t("office.consequence.title")} items={consequence} />

      {mode === "resolve" ? (
        <fieldset className="pf-res-fieldset">
          <legend>{t("office.other.title")}</legend>
          <FormField
            id={id("comment")}
            label={t("office.other.comment")}
            hint={t("office.other.commentHint")}
          >
            <Input.TextArea
              id={id("comment")}
              value={comment}
              maxLength={4000}
              autoSize={{ minRows: 2, maxRows: 6 }}
              aria-describedby={id("comment-hint")}
              onChange={(event) => {
                setComment(event.target.value);
                setFailure(null);
              }}
            />
          </FormField>
          <p className="pf-hint">{t("office.other.returnHelp")}</p>
          <p className="pf-hint">{t("office.other.rejectHelp")}</p>
        </fieldset>
      ) : null}

      <ErrorNote message={failureText} />

      <div className="pf-res-actions">
        <Button
          type={mode === "resolve" && approvable ? "default" : "primary"}
          htmlType="submit"
          block
          loading={resolve.isPending || saveDraft.isPending}
          disabled={busy}
        >
          {mode === "draft" ? t("office.saveDraft") : t("office.submit")}
        </Button>
        {mode === "resolve" ? (
          <>
            <div className="pf-res-secondary">
              <Button
                block
                loading={sendBack.isPending}
                disabled={busy || trimmed === ""}
                aria-describedby={trimmed === "" ? id("disabled") : undefined}
                onClick={() => {
                  setFailure(null);
                  sendBack.mutate({ id: letter.id, data: { comment: trimmed } });
                }}
              >
                {t("office.other.return")}
              </Button>
              <Button
                block
                danger
                loading={reject.isPending}
                disabled={busy || trimmed === ""}
                aria-describedby={trimmed === "" ? id("disabled") : undefined}
                onClick={() => {
                  setFailure(null);
                  reject.mutate({ id: letter.id, data: { reason: trimmed } });
                }}
              >
                {t("office.other.reject")}
              </Button>
            </div>
            {trimmed === "" ? (
              <p className="pf-hint" id={id("disabled")}>
                {t("office.other.disabled")}
              </p>
            ) : null}
          </>
        ) : null}
      </div>
    </form>
  );
}
