import { App, Button, Card, Input } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { useAuth } from "../../../app/auth/useAuth";
import type {
  LetterCard,
  LetterInstruction,
  LetterInstructionExtension,
} from "../../../shared/api/generated/model";
import { useDecideInstructionExtension } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { ErrorNote } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { useResolutionKindName } from "../dictionaries";
import { reasonOf, useRefreshLetters } from "./api";
import { Attachments } from "./Parts";

/** Резолюция пути делопроизводства (P8b): тип, ответственный, соисполнители, «ознакомить», срок, текст, кто и когда. */
export function OfficeDecision({ letter }: { letter: LetterCard }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const kindName = useResolutionKindName();
  const res = letter.office_resolution;
  if (!res) return null;
  const names = (people: readonly { name: string }[]) =>
    people.length > 0 ? people.map((p) => p.name).join(", ") : null;
  return (
    <Card size="small" title={<h2 className="pf-letters-title">{t("instr.resolution")}</h2>}>
      <DefinitionList
        items={[
          { label: t("instr.fields.kind"), value: kindName(res.kind) },
          { label: t("instr.fields.responsible"), value: res.responsible?.name },
          { label: t("instr.fields.co"), value: names(res.co_executors) },
          { label: t("instr.fields.due"), value: res.due ? date(res.due) : null },
          { label: t("instr.fields.text"), value: res.text },
          { label: t("instr.fields.acquaint"), value: names(res.acquaint) },
          {
            label: t("instr.fields.decidedBy"),
            value: `${res.decided_by.name} · ${date(res.decided_at, "datetime")}`,
          },
        ]}
      />
    </Card>
  );
}

function History({ items }: { items: readonly LetterInstructionExtension[] }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  if (items.length === 0) return null;
  return (
    <>
      <h4 className="pf-res-subhead">{t("instr.history")}</h4>
      <ol className="pf-letters-journal">
        {items.map((ext) => (
          <li key={ext.id}>
            <strong>
              {t("instr.ext.item", {
                old: date(ext.old_due),
                new: date(ext.new_due),
                reason: ext.reason,
              })}
            </strong>{" "}
            <span className="pf-hint">
              · {t(`instr.ext.status.${ext.status}`)} ·{" "}
              {t("instr.ext.by", {
                name: ext.requested_by.name,
                date: date(ext.requested_at, "datetime"),
              })}
              {ext.decided_by && ext.decided_at
                ? ` · ${t("instr.ext.decidedBy", {
                    name: ext.decided_by.name,
                    date: date(ext.decided_at, "datetime"),
                  })}`
                : ""}
            </span>
            {ext.comment ? <p className="pf-letters-note">{ext.comment}</p> : null}
          </li>
        ))}
      </ol>
    </>
  );
}

/**
 * Решение автора резолюции по запросу переноса (SPEC-v3 §3.2a п. 4): «Одобрить» — срок меняется, «Отклонить» — прежний.
 * Кто вправе решать, проверяет EDS (`not_resolution_author`); здесь кнопки видит автор резолюции.
 */
export function ExtensionDecision({
  instruction,
  pending,
  urgent = false,
}: {
  instruction: LetterInstruction;
  pending: LetterInstructionExtension;
  /** Срочное письмо: срок не продлевается (Росархив 5.14) — одобрить нельзя, только отклонить (решает EDS) */
  urgent?: boolean;
}) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const { message } = App.useApp();
  const refresh = useRefreshLetters();
  const ids = useId();
  const [comment, setComment] = useState("");
  const [failure, setFailure] = useState<unknown>(null);
  const [choice, setChoice] = useState<"approve" | "reject">("approve");
  const decide = useDecideInstructionExtension({
    mutation: {
      onSuccess: (_card, variables) => {
        void refresh();
        void message.success(
          t(`instr.decide.done.${variables.data.decision}`, { date: date(pending.new_due) }),
        );
      },
      onError: setFailure,
    },
  });
  const send = (decision: "approve" | "reject") => {
    setChoice(decision);
    setFailure(null);
    const text = comment.trim();
    decide.mutate({ id: instruction.id, data: { decision, comment: text || null } });
  };
  return (
    <section className="pf-instr-decide" aria-labelledby={`${ids}-title`}>
      <h3 className="pf-res-subhead" id={`${ids}-title`}>
        {t("instr.decide.title")}
      </h3>
      <p>
        {t("instr.decide.text", {
          name: pending.requested_by.name,
          old: date(pending.old_due),
          new: date(pending.new_due),
        })}
      </p>
      <p className="pf-hint">{t("instr.decide.reason", { reason: pending.reason })}</p>
      {urgent ? (
        <p className="pf-hint" id={`${ids}-urgent`}>
          {t("instr.decide.urgent")}
        </p>
      ) : null}
      <div className="pf-fp-field">
        <label htmlFor={`${ids}-comment`}>{t("instr.decide.comment")}</label>
        <Input.TextArea
          id={`${ids}-comment`}
          value={comment}
          maxLength={2000}
          autoSize={{ minRows: 2, maxRows: 5 }}
          onChange={(event) => {
            setComment(event.target.value);
          }}
        />
      </div>
      <ErrorNote
        message={
          failure ? t("tasks.failed", { reason: t(`form.reasons.${reasonOf(failure)}`) }) : null
        }
      />
      <div className="pf-fp-row">
        <Button
          type="primary"
          loading={decide.isPending && choice === "approve"}
          disabled={decide.isPending || urgent}
          aria-describedby={urgent ? `${ids}-urgent` : undefined}
          onClick={() => {
            send("approve");
          }}
        >
          {t("instr.decide.approve")}
        </Button>
        <Button
          danger
          loading={decide.isPending && choice === "reject"}
          disabled={decide.isPending}
          onClick={() => {
            send("reject");
          }}
        >
          {t("instr.decide.reject")}
        </Button>
      </div>
    </section>
  );
}

function InstructionItem({
  instruction,
  author,
  urgent,
}: {
  instruction: LetterInstruction;
  author: boolean;
  urgent: boolean;
}) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const pending = instruction.extensions.find((e) => e.status === "pending");
  const executed = instruction.status === "executed";
  return (
    <li className="pf-instr">
      <div className="pf-instr-head">
        <strong>{instruction.person.name}</strong>
        <span className="pf-hint"> · {t(`instr.role.${instruction.role}`)}</span>
        <span className="pf-instr-tags">
          <StatusTag kind="instruction" status={instruction.status}>
            {t(`instr.status.${instruction.status}`)}
          </StatusTag>
          {instruction.overdue ? (
            <StatusTag kind="due" status="overdue">
              {t("instr.overdue")}
            </StatusTag>
          ) : null}
        </span>
      </div>
      <p className={instruction.overdue ? "pf-instr-due pf-instr-due--overdue" : "pf-instr-due"}>
        {executed && instruction.executed_at
          ? t("instr.executedAt", { date: date(instruction.executed_at, "datetime") })
          : t("instr.due", { date: date(instruction.due) })}
      </p>
      {instruction.report ? (
        <DefinitionList items={[{ label: t("instr.report"), value: instruction.report }]} />
      ) : null}
      {instruction.outgoing ? (
        <DefinitionList
          items={[
            {
              label: t("instr.outgoing"),
              value: (
                <Link className="pf-focusable" to={instruction.outgoing.path}>
                  {instruction.outgoing.number}
                </Link>
              ),
            },
          ]}
        />
      ) : null}
      {instruction.handed_to ? (
        <DefinitionList
          items={[
            {
              label: t("instr.handedTo.label"),
              value: (
                <>
                  {t(`instr.handedTo.${instruction.handed_to.kind}`)}{" "}
                  {instruction.handed_to.path ? (
                    <Link className="pf-focusable" to={instruction.handed_to.path}>
                      {instruction.handed_to.number}
                    </Link>
                  ) : (
                    instruction.handed_to.number
                  )}
                </>
              ),
            },
          ]}
        />
      ) : null}
      {instruction.files.length > 0 ? (
        <>
          <h4 className="pf-res-subhead">{t("instr.files")}</h4>
          <Attachments files={instruction.files} />
        </>
      ) : null}
      <History items={instruction.extensions} />
      {author && pending && !executed ? (
        <ExtensionDecision instruction={instruction} pending={pending} urgent={urgent} />
      ) : null}
    </li>
  );
}

/**
 * Поручения письма и ознакомление (P8b, SPEC-v3 §3.2a п. 3–5): исполнитель, роль, срок (просрочка красным — признак EDS),
 * статус, отчёт, файлы, ответ ИСХ, история переносов; автору резолюции — решение по ожидающему переносу.
 */
export function InstructionsCard({ letter }: { letter: LetterCard }) {
  const { t } = useTranslation("letters");
  const { date } = useFormat();
  const { me } = useAuth();
  const instructions = letter.instructions ?? [];
  const acquaintances = letter.acquaintances ?? [];
  if (instructions.length === 0 && acquaintances.length === 0) return null;
  const author = letter.office_resolution?.decided_by.id === me.id;
  return (
    <Card
      size="small"
      title={<h2 className="pf-letters-title">{t("instr.title")}</h2>}
      extra={letter.on_control ? <StatusTag tone="blue">{t("card.onControl")}</StatusTag> : null}
    >
      {instructions.length > 0 ? (
        <ul className="pf-instr-list">
          {instructions.map((instruction) => (
            <InstructionItem
              key={instruction.id}
              instruction={instruction}
              author={author}
              urgent={letter.urgent}
            />
          ))}
        </ul>
      ) : (
        <p className="pf-hint">{t("instr.none")}</p>
      )}
      {acquaintances.length > 0 ? (
        <>
          <h3 className="pf-res-subhead">{t("instr.acq.title")}</h3>
          <ul className="pf-instr-acq">
            {acquaintances.map((a) => (
              <li key={a.person.id}>
                {a.person.name}{" "}
                <span className="pf-hint">
                  ·{" "}
                  {a.acknowledged_at
                    ? t("instr.acq.done", { date: date(a.acknowledged_at, "datetime") })
                    : t("instr.acq.waiting")}
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </Card>
  );
}
