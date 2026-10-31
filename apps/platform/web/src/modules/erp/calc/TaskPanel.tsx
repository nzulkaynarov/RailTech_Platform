import { useTranslation } from "react-i18next";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { PanelPortal } from "../../../app/shell/PanelSlot";
import type { CalcSheet, CalcVisaGroup } from "../../../shared/api/generated/model";
import { useGetCalcSheet } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DefinitionList } from "../../../shared/ui/DefinitionList";
import { QueryState } from "../../../shared/ui/FormParts";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { calcPath, calcRef, useStateLabels } from "./api";

const GROUPS = ["stock", "supply", "engineer"] as const;
/** Зона резолюции, исполнители которой визируют группу строк: склад и снабжение — товары, гл. инженер — услуги. */
const ZONE_OF = { stock: "goods", supply: "goods", engineer: "services" } as const;

function VisaRow({
  group,
  data,
  assigned,
}: {
  group: (typeof GROUPS)[number];
  data: CalcVisaGroup;
  assigned: string[];
}) {
  const { t } = useTranslation("calc");
  return (
    <li className="pf-calc-task-visa">
      <div className="pf-calc-task-visa-head">
        <strong>{t(`groups.${group}`)}</strong>
        <StatusTag kind="visa" status={data.state}>
          {t(`task.state.${data.state}`)}
          {data.total ? ` · ${t("task.counts", { signed: data.signed, total: data.total })}` : ""}
        </StatusTag>
      </div>
      {data.by.length ? (
        <p className="pf-hint">{t("task.signedBy", { names: data.by.join(", ") })}</p>
      ) : null}
      <p className="pf-hint">
        {assigned.length
          ? t("task.assigned", { names: assigned.join(", ") })
          : t("task.nobodyAssigned")}
      </p>
    </li>
  );
}

/** Содержимое вкладки «Задание» (SPEC-v3 §7.4): резолюция директора, визы по заявке, чат проекта, «Сделать служебку». */
export function TaskBody({ sheet, brief = false }: { sheet: CalcSheet; brief?: boolean }) {
  const { t } = useTranslation("calc");
  const { me } = useAuth();
  const { date } = useFormat();
  const task = sheet.task;
  const assignedFor = (group: (typeof GROUPS)[number]) =>
    task.assignees
      .filter((a) => a.zone === ZONE_OF[group])
      .map((a) => a.name ?? t("task.notInErp"));
  return (
    <div className="pf-calc-task">
      {brief ? (
        <div className="pf-calc-task-brief">
          <h3 className="pf-calc-task-title">{sheet.number}</h3>
          <p className="pf-hint">{[sheet.client, sheet.title].filter(Boolean).join(" · ")}</p>
          <LinkButton type="primary" to={calcPath(sheet.number)}>
            {t("task.open")}
          </LinkButton>
        </div>
      ) : null}
      <section aria-labelledby="pf-calc-task-resolution">
        <h3 id="pf-calc-task-resolution" className="pf-calc-task-title">
          {t("task.resolution")}
        </h3>
        <blockquote className="pf-calc-quote">{task.resolution_text}</blockquote>
        <p className="pf-hint">
          {t("task.decided", {
            name: task.decided_by ?? "—",
            date: date(task.decided_at, "datetime"),
          })}
        </p>
        <DefinitionList
          items={[
            {
              label: t("task.letter", { number: task.letter_number }),
              value: task.letter_subject || "—",
            },
            { label: t("task.due"), value: date(task.due) },
            ...(task.min_margin_pct !== undefined && task.min_margin_pct !== null
              ? [{ label: t("task.margin"), value: `${task.min_margin_pct} %` }]
              : []),
          ]}
        />
      </section>
      <section aria-labelledby="pf-calc-task-visas">
        <h3 id="pf-calc-task-visas" className="pf-calc-task-title">
          {t("task.visas")}
        </h3>
        <ul className="pf-calc-task-visas">
          {GROUPS.map((group) => (
            <VisaRow
              key={group}
              group={group}
              data={sheet.visas[group]}
              assigned={assignedFor(group)}
            />
          ))}
        </ul>
      </section>
      <section aria-labelledby="pf-calc-task-chat">
        <h3 id="pf-calc-task-chat" className="pf-calc-task-title">
          {t("task.chat")}
        </h3>
        <p className="pf-hint">{t("task.chatText")}</p>
      </section>
      {canEdit(me, "eds.memo.create") ? (
        <section className="pf-calc-task-memo">
          <p className="pf-hint">{t("task.memo")}</p>
          <LinkButton size="small" to="/eds/new">
            {t("task.memoAction")}
          </LinkButton>
        </section>
      ) : null}
    </div>
  );
}

function TaskPanel({ number, brief }: { number: string; brief: boolean }) {
  const query = useGetCalcSheet(calcRef(number));
  const labels = useStateLabels();
  return (
    <QueryState query={query} labels={labels} level={3} compact>
      {(sheet) => <TaskBody sheet={sheet} brief={brief} />}
    </QueryState>
  );
}

/**
 * Где живёт «Задание»: вкладка `task` бокового окна каркаса; на телефоне каркас показывает окно листом на весь экран
 * (раздел с `sheetOnMobile`, B-020).
 */
export function TaskSlot({ number, brief = false }: { number: string; brief?: boolean }) {
  return (
    <PanelPortal tab="task">
      <TaskPanel number={number} brief={brief} />
    </PanelPortal>
  );
}
