import type { EventClickArg, EventContentArg, EventInput } from "@fullcalendar/core";
import ruLocale from "@fullcalendar/core/locales/ru";
import uzLocale from "@fullcalendar/core/locales/uz";
import dayGridPlugin from "@fullcalendar/daygrid";
import listPlugin from "@fullcalendar/list";
import FullCalendar from "@fullcalendar/react";
import { Alert, Button, Checkbox } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router";

import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { useGetQueue } from "../../../shared/api/generated/platform-bff";
import { usePollQuery } from "../../../shared/api/polling";
import type { QueueItem, QueueItemKind } from "../../../shared/api/generated/model";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { SoonButton } from "../../../shared/ui/SoonButton";
import { objectLink } from "../../objectLinks";
import "./calendar.css";

const CATEGORIES = ["tasks", "documents", "invoices", "deliveries"] as const;
type Category = (typeof CATEGORIES)[number];

const CATEGORY: Record<QueueItemKind, Category> = {
  answer_lead: "tasks",
  take_lead: "tasks",
  triage_lead: "tasks",
  create_request: "tasks",
  service_request: "tasks",
  calc_task: "tasks",
  problem_project: "tasks",
  ticket: "tasks",
  integration_issue: "tasks",
  instruction: "tasks",
  instruction_extension: "tasks",
  acquaint: "tasks",
  inbound_mail: "tasks",
  inbound_mail_mine: "tasks",
  resolve_letter: "documents",
  approve_quote: "documents",
  approve_memo: "documents",
  rework_document: "documents",
  issue_contract: "documents",
  attach_scan: "documents",
  issue_act: "documents",
  register_reply: "documents",
  confirm_payment: "invoices",
  issue_invoice: "invoices",
  pay_memo: "invoices",
  overdue_invoice: "invoices",
  supplier_overdue: "deliveries",
};

function toEvent(item: QueueItem): EventInput[] {
  if (!item.due_at) return [];
  const overdue = item.due_label === "overdue";
  return [
    {
      id: item.id,
      title: item.title,
      start: item.due_at,
      allDay: true,
      url: objectLink(item.object),
      classNames: [`pf-cal-${CATEGORY[item.kind]}`, ...(overdue ? ["pf-cal-overdue"] : [])],
      extendedProps: { overdue },
    },
  ];
}

/** Органайзер · Календарь: сроки из задач сотрудника на FullCalendar. */
export function CalendarPage() {
  const { t, i18n } = useTranslation(["modules"]);
  const { me } = useAuth();
  const { mobile } = useViewport();
  const navigate = useNavigate();
  const role = me.active_role ?? undefined;
  const queue = useGetQueue(role ? { role } : undefined, { query: usePollQuery() });
  const [shown, setShown] = useState<readonly Category[]>(CATEGORIES);
  const title = t("modules:chats.sections.calendar");
  useDocumentTitle(title);

  const events = useMemo(
    () =>
      (queue.data?.items ?? [])
        .filter((item) => shown.includes(CATEGORY[item.kind]))
        .flatMap(toEvent),
    [queue.data, shown],
  );

  const open = (info: EventClickArg) => {
    info.jsEvent.preventDefault();
    void navigate(info.event.url);
  };

  const content = (arg: EventContentArg) => (
    <span className="pf-cal-event">
      {arg.event.extendedProps["overdue"] ? (
        <span className="pf-cal-event-flag">{t("modules:dashboard.queue.due.overdue")}</span>
      ) : null}
      <span>{arg.event.title}</span>
    </span>
  );

  return (
    <div className="pf-calendar">
      <PageHeader
        title={title}
        extra={<SoonButton>{t("modules:chats.calendar.link")}</SoonButton>}
      />
      <Checkbox.Group
        className="pf-cal-filters"
        aria-label={t("modules:chats.calendar.filter")}
        value={[...shown]}
        options={CATEGORIES.map((value) => ({
          value,
          label: t(`modules:chats.calendar.kinds.${value}`),
        }))}
        onChange={(values) => {
          setShown(values);
        }}
      />
      {queue.isError ? (
        <Alert
          type="error"
          showIcon
          message={t("modules:chats.calendar.loadError")}
          action={
            <Button
              size="small"
              onClick={() => {
                void queue.refetch();
              }}
            >
              {t("modules:chats.calendar.retry")}
            </Button>
          }
        />
      ) : null}
      <FullCalendar
        key={mobile ? "list" : "grid"}
        plugins={[dayGridPlugin, listPlugin]}
        initialView={mobile ? "listWeek" : "dayGridWeek"}
        locales={[ruLocale, uzLocale]}
        locale={i18n.language}
        firstDay={1}
        buttonIcons={false}
        buttonText={{
          prev: t("modules:chats.calendar.prev"),
          next: t("modules:chats.calendar.next"),
        }}
        height="auto"
        headerToolbar={
          mobile
            ? { left: "prev,next", center: "", right: "today" }
            : {
                left: "prev,next today",
                center: "title",
                right: "dayGridMonth,dayGridWeek,listWeek",
              }
        }
        events={events}
        eventContent={content}
        eventClick={open}
      />
    </div>
  );
}
