import { App, Button, Checkbox, Input } from "antd";
import { type FormEvent, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";

import { useAuth } from "../../../app/auth/useAuth";
import { ApiError } from "../../../shared/api/errors";
import type { LetterCard, LetterZone } from "../../../shared/api/generated/model";
import {
  useListResolutionAssignees,
  useRejectLetter,
  useResolveLetter,
  useReturnLetter,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { Consequence } from "../../../shared/ui/Consequence";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { companyDate, fieldsOf, reasonOf, useRefreshLetters } from "./api";
import { type ResolutionDraft, type ZonePick, clearDraft, readDraft, writeDraft } from "./draft";

const ZONES: readonly LetterZone[] = ["goods", "services", "payment_terms"];
// Бухгалтер (условия оплаты) по умолчанию выключен — SPEC-v3 §7.3.
const DEFAULT_ON: Record<LetterZone, boolean> = {
  goods: true,
  services: true,
  payment_terms: false,
};
const MARGIN = /^(100(\.0{1,2})?|\d{1,2}(\.\d{1,2})?)$/;
const DEFAULT_TERM_DAYS = 3;

function initialDraft(): ResolutionDraft {
  const picks = {} as Record<LetterZone, ZonePick>;
  for (const zone of ZONES) picks[zone] = { on: DEFAULT_ON[zone], userId: "" };
  return { text: "", picks, due: companyDate(DEFAULT_TERM_DAYS), margin: "", comment: "" };
}

type Action = "resolve" | "return" | "reject";
type ErrorKey = "text" | "assignees" | "due" | "margin" | LetterZone;
type Errors = Partial<Record<ErrorKey, string>>;

function without(errors: Errors, keys: readonly ErrorKey[]): Errors {
  return Object.fromEntries(Object.entries(errors).filter(([key]) => !keys.some((k) => k === key)));
}

export interface ResolutionFormProps {
  letter: LetterCard;
  /** Лист на телефоне: кнопки решения закреплены внизу */
  variant?: "panel" | "sheet";
  /** Решение принято и сохранено (лист закрывается) */
  onDone?: () => void;
}

/**
 * Боковое окно «Резолюция» (SPEC-v3 §7.3, UX-оценка P0-4): текст, исполнители по зонам с выбором сотрудника, срок, «Маржа не
 * ниже, %», главная кнопка «Утвердить резолюцию → задание в расчёт» с блоком «Что произойдёт», «Вернуть менеджеру» и
 * «Отклонить» (комментарий обязателен: кнопки неактивны с подписью, пока он пуст). Введённое сохраняется в браузере на
 * письмо — ошибка отправки ничего не стирает. Решения принимает EDS (статус, срок, исполнители), форма их не дублирует.
 */
export function ResolutionForm({ letter, variant = "panel", onDone }: ResolutionFormProps) {
  const { t } = useTranslation("letters");
  const { me } = useAuth();
  const { date } = useFormat();
  const { message } = App.useApp();
  const refresh = useRefreshLetters();
  const ids = useId();
  const id = (name: string) => `${ids}-${name}`;
  const canMargin = (me.restricted_fields ?? []).includes("cost_margin");

  const [saved] = useState(() => readDraft(me.id, letter.id));
  const [state, setState] = useState<ResolutionDraft>(() => saved ?? initialDraft());
  const [errors, setErrors] = useState<Errors>({});
  const [failure, setFailure] = useState<{ action: Action; error: unknown } | null>(null);
  const directory = useListResolutionAssignees();

  useEffect(() => {
    writeDraft(me.id, letter.id, state);
  }, [me.id, letter.id, state]);

  const zones = directory.data?.zones ?? [];
  const listed = directory.data?.directory;
  const candidatesOf = (zone: LetterZone) => zones.find((z) => z.zone === zone)?.candidates ?? [];

  // Один кандидат в зоне — выбран сразу; нет кандидатов — зона выключена (отметить её нельзя). Считается при показе:
  // ввод директора в `state` не подменяется, пока справочник не загрузился.
  const pickOf = (zone: LetterZone): ZonePick => {
    const pick = state.picks[zone];
    if (!directory.data) return pick;
    const candidates = candidatesOf(zone);
    const first = candidates[0];
    const known = candidates.some((c) => c.id === pick.userId);
    const userId = known ? pick.userId : candidates.length === 1 && first ? first.id : "";
    return { on: pick.on && candidates.length > 0, userId };
  };

  const done = (action: Action) => {
    clearDraft(me.id, letter.id);
    void refresh();
    void message.success(t(`form.done.${action}`));
    onDone?.();
  };
  const failed = (action: Action) => (error: unknown) => {
    // 409: письмо уже решено или возвращено другим — вводить больше нечего, черновик не нужен.
    if (error instanceof ApiError && error.status === 409) clearDraft(me.id, letter.id);
    setFailure({ action, error });
    const named = fieldsOf(error);
    setErrors((prev) => ({
      ...prev,
      ...(named.includes("due") ? { due: t("form.errors.duePast") } : {}),
      ...(named.includes("assignees") ? { assignees: t("form.errors.assignees") } : {}),
    }));
  };
  const resolve = useResolveLetter({
    mutation: {
      onSuccess: () => {
        done("resolve");
      },
      onError: failed("resolve"),
    },
  });
  const sendBack = useReturnLetter({
    mutation: {
      onSuccess: () => {
        done("return");
      },
      onError: failed("return"),
    },
  });
  const reject = useRejectLetter({
    mutation: {
      onSuccess: () => {
        done("reject");
      },
      onError: failed("reject"),
    },
  });
  const busy = resolve.isPending || sendBack.isPending || reject.isPending;

  const patch = (change: Partial<ResolutionDraft>, clear: readonly ErrorKey[] = []) => {
    setState((prev) => ({ ...prev, ...change }));
    setFailure(null);
    if (clear.length > 0) setErrors((prev) => without(prev, clear));
  };
  const patchPick = (zone: LetterZone, change: Partial<ZonePick>) => {
    setState((prev) => ({
      ...prev,
      picks: { ...prev.picks, [zone]: { ...prev.picks[zone], ...change } },
    }));
    setFailure(null);
    setErrors((prev) => without(prev, [zone, "assignees"]));
  };

  const margin = state.margin.trim().replace(",", ".");
  const today = companyDate();
  const chosen = ZONES.filter((zone) => pickOf(zone).on);
  const comment = state.comment.trim();
  const directoryReady = listed === "ok";

  const validate = (): Errors => {
    const found: Errors = {};
    if (state.text.trim() === "") found.text = t("form.errors.text");
    if (chosen.length === 0) found.assignees = t("form.errors.assignees");
    for (const zone of chosen) {
      if (pickOf(zone).userId === "") found[zone] = t("form.errors.employee");
    }
    if (state.due === "") found.due = t("form.errors.due");
    else if (state.due < today) found.due = t("form.errors.duePast");
    if (canMargin && margin !== "" && !MARGIN.test(margin)) found.margin = t("form.errors.margin");
    return found;
  };

  const chosenFocus = () => id(`pick-${ZONES.find((z) => candidatesOf(z).length > 0) ?? "goods"}`);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    setFailure(null);
    const found = validate();
    setErrors(found);
    const first = (["text", "assignees", ...ZONES, "due", "margin"] as const).find(
      (key) => found[key],
    );
    if (first) {
      const target = first === "assignees" ? chosenFocus() : id(first);
      window.setTimeout(() => document.getElementById(target)?.focus(), 0);
      return;
    }
    resolve.mutate({
      id: letter.id,
      data: {
        text: state.text.trim(),
        assignees: chosen.map((zone) => ({ id: pickOf(zone).userId, zone })),
        due: state.due,
        ...(canMargin && margin !== "" ? { min_margin_pct: margin } : {}),
      },
    });
  };

  // 409 («письмо уже не ждёт резолюции»): черновик стёрт, поэтому фразы «сохранён в черновике» нет.
  const failureText = failure
    ? t(
        `form.${reasonOf(failure.error) === "invalid_state" ? "failedGone" : "failed"}.${failure.action}`,
        { reason: t(`form.reasons.${reasonOf(failure.error)}`) },
      )
    : null;

  return (
    <form
      className={`pf-res pf-res--${variant}`}
      aria-label={t("form.name")}
      noValidate
      onSubmit={submit}
    >
      {saved ? <p className="pf-hint">{t("form.draft")}</p> : null}

      <FormField
        id={id("text")}
        label={t("form.text.label")}
        hint={errors.text ? undefined : t("form.text.hint")}
      >
        <Input.TextArea
          id={id("text")}
          value={state.text}
          maxLength={4000}
          autoSize={{ minRows: 3, maxRows: 8 }}
          status={errors.text ? "error" : undefined}
          aria-invalid={errors.text ? true : undefined}
          aria-describedby={errors.text ? id("text-error") : id("text-hint")}
          onChange={(event) => {
            patch({ text: event.target.value }, ["text"]);
          }}
        />
        {errors.text ? (
          <span className="pf-res-error" id={id("text-error")} role="alert">
            {errors.text}
          </span>
        ) : null}
      </FormField>

      <fieldset className="pf-res-fieldset" aria-describedby={id("assignees-hint")}>
        <legend>{t("form.assignees.legend")}</legend>
        <p className="pf-hint" id={id("assignees-hint")}>
          {t("form.assignees.hint")}
        </p>
        {listed === "forbidden" || listed === "unavailable" ? (
          <div className="pf-res-note" role="status">
            <span>{t(`form.directory.${listed}`)}</span>
            {listed === "unavailable" ? (
              <Button
                size="small"
                onClick={() => {
                  void directory.refetch();
                }}
              >
                {t("form.directory.retry")}
              </Button>
            ) : null}
          </div>
        ) : null}
        {ZONES.map((zone) => {
          const candidates = candidatesOf(zone);
          const pick = pickOf(zone);
          const noOne = directoryReady && candidates.length === 0;
          return (
            <div className="pf-res-zone" key={zone}>
              <Checkbox
                checked={pick.on}
                disabled={!directoryReady || noOne}
                onChange={(event) => {
                  patchPick(zone, { on: event.target.checked });
                }}
              >
                <span className="pf-res-zone-name">{t(`form.zones.${zone}.name`)}</span>
                <span className="pf-hint"> — {t(`form.zones.${zone}.hint`)}</span>
              </Checkbox>
              {noOne ? <span className="pf-hint">{t("form.assignees.none")}</span> : null}
              {pick.on && candidates.length > 0 ? (
                <div className="pf-res-pick">
                  <label className="pf-sr-only" htmlFor={id(`pick-${zone}`)}>
                    {t("form.assignees.employee", { zone: t(`form.zones.${zone}.name`) })}
                  </label>
                  <select
                    id={id(`pick-${zone}`)}
                    className="pf-res-select pf-focusable"
                    value={pick.userId}
                    aria-invalid={errors[zone] ? true : undefined}
                    aria-describedby={errors[zone] ? id(`pick-${zone}-error`) : undefined}
                    onChange={(event) => {
                      patchPick(zone, { userId: event.target.value });
                    }}
                  >
                    <option value="">{t("form.assignees.choose")}</option>
                    {candidates.map((candidate) => (
                      <option key={candidate.id} value={candidate.id}>
                        {candidate.position
                          ? `${candidate.name} · ${candidate.position}`
                          : candidate.name}
                      </option>
                    ))}
                  </select>
                  {errors[zone] ? (
                    <span className="pf-res-error" id={id(`pick-${zone}-error`)} role="alert">
                      {errors[zone]}
                    </span>
                  ) : null}
                </div>
              ) : null}
            </div>
          );
        })}
        {errors.assignees ? (
          <span className="pf-res-error" role="alert">
            {errors.assignees}
          </span>
        ) : null}
      </fieldset>

      <FormField
        id={id("due")}
        label={t("form.due.label")}
        hint={errors.due ? undefined : t("form.due.hint")}
      >
        <Input
          id={id("due")}
          type="date"
          value={state.due}
          min={today}
          status={errors.due ? "error" : undefined}
          aria-invalid={errors.due ? true : undefined}
          aria-describedby={errors.due ? id("due-error") : id("due-hint")}
          onChange={(event) => {
            patch({ due: event.target.value }, ["due"]);
          }}
        />
        {errors.due ? (
          <span className="pf-res-error" id={id("due-error")} role="alert">
            {errors.due}
          </span>
        ) : null}
      </FormField>

      {canMargin ? (
        <FormField
          id={id("margin")}
          label={t("form.margin.label")}
          hint={errors.margin ? undefined : t("form.margin.hint")}
        >
          <Input
            id={id("margin")}
            inputMode="decimal"
            value={state.margin}
            maxLength={6}
            status={errors.margin ? "error" : undefined}
            aria-invalid={errors.margin ? true : undefined}
            aria-describedby={errors.margin ? id("margin-error") : id("margin-hint")}
            onChange={(event) => {
              patch({ margin: event.target.value }, ["margin"]);
            }}
          />
          {errors.margin ? (
            <span className="pf-res-error" id={id("margin-error")} role="alert">
              {errors.margin}
            </span>
          ) : null}
        </FormField>
      ) : null}

      <Consequence
        title={t("form.consequence.title")}
        items={[
          t("form.consequence.step1"),
          state.due
            ? t("form.consequence.step2", { due: date(state.due) })
            : t("form.consequence.step2NoDue"),
          t("form.consequence.step3"),
        ]}
      />

      <fieldset className="pf-res-fieldset">
        <legend>{t("form.other.title")}</legend>
        <FormField
          id={id("comment")}
          label={t("form.other.comment")}
          hint={t("form.other.commentHint")}
        >
          <Input.TextArea
            id={id("comment")}
            value={state.comment}
            maxLength={4000}
            autoSize={{ minRows: 2, maxRows: 6 }}
            aria-describedby={id("comment-hint")}
            onChange={(event) => {
              patch({ comment: event.target.value });
            }}
          />
        </FormField>
        <p className="pf-hint">{t("form.other.returnHelp")}</p>
        <p className="pf-hint">{t("form.other.rejectHelp")}</p>
      </fieldset>

      <ErrorNote message={failureText} />

      <div className="pf-res-actions">
        <Button
          type="primary"
          htmlType="submit"
          block
          loading={resolve.isPending}
          disabled={busy || !directoryReady}
        >
          {t("form.submit")}
        </Button>
        <div className="pf-res-secondary">
          <Button
            block
            loading={sendBack.isPending}
            disabled={busy || comment === ""}
            aria-describedby={comment === "" ? id("disabled") : undefined}
            onClick={() => {
              setFailure(null);
              sendBack.mutate({ id: letter.id, data: { comment } });
            }}
          >
            {t("form.other.return")}
          </Button>
          <Button
            block
            danger
            loading={reject.isPending}
            disabled={busy || comment === ""}
            aria-describedby={comment === "" ? id("disabled") : undefined}
            onClick={() => {
              setFailure(null);
              reject.mutate({ id: letter.id, data: { reason: comment } });
            }}
          >
            {t("form.other.reject")}
          </Button>
        </div>
        {comment === "" ? (
          <p className="pf-hint" id={id("disabled")}>
            {t("form.other.disabled")}
          </p>
        ) : null}
      </div>
    </form>
  );
}
