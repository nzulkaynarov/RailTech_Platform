import { Button, Card, Input, Select, Skeleton } from "antd";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate, useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { PanelPortal } from "../../../app/shell/PanelSlot";
import { EMPLOYEE_STATUSES } from "../../../entities/employee/status";
import { isSystemAdmin } from "../../../entities/role/roles";
import { InviteEmployeeForm } from "../../../features/invite-employee/InviteEmployeeForm";
import type { EmployeeStatus } from "../../../shared/api/generated/model";
import { useListEmployees } from "../../../shared/api/generated/platform-bff";
import { useCompactBlock } from "../../../shared/lib/useCompactBlock";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { useViewport } from "../../../app/shell/useViewport";
import { EmployeeCard } from "./EmployeeCard";
import { EmployeeList } from "./EmployeeList";

import "./org.css";

const PATH = "/admin/org";
/** Уже этой ширины блока таблица из пяти колонок не помещается без горизонтальной прокрутки */
const TABLE_MIN_WIDTH = 700;

/**
 * Admin · Оргструктура (SPEC-v3 §7.6): сотрудники списком, карточка и приглашение — в боковом окне без перехода
 * (`?employee=<id>`, `?invite=open`). Выдача ролей — ADMIN; DIRECTOR видит список и карточки только для чтения.
 */
export function OrgPage({ objectId }: { objectId?: string }) {
  const { t } = useTranslation(["modules", "shell"]);
  const { me } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [params] = useSearchParams();
  const { wide } = useViewport();
  const editable = canEdit(me, "admin");
  const title = t("modules:admin.sections.org");
  useDocumentTitle(title);

  // Таблица или список — по ширине самого блока, с запасом 40 px у порога (useCompactBlock).
  const { ref: blockRef, compact } = useCompactBlock(TABLE_MIN_WIDTH, !wide);

  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<EmployeeStatus | "all">("all");
  const list = useListEmployees();
  const items = useMemo(() => list.data?.items ?? [], [list.data]);

  const selectedId = objectId ?? params.get("employee");
  const inviting = editable && params.get("invite") === "open";
  const selected = items.find((employee) => employee.id === selectedId);

  const filtered = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return items.filter(
      (employee) =>
        (status === "all" || employee.status === status) &&
        (needle === "" ||
          `${employee.name} ${employee.email} ${employee.position ?? ""}`
            .toLocaleLowerCase()
            .includes(needle)),
    );
  }, [items, query, status]);

  const keep = (next: URLSearchParams) => {
    const tab = params.get("tab");
    if (tab) next.set("tab", tab);
    return `${PATH}?${next.toString()}`;
  };
  const employeeHref = (id: string) => keep(new URLSearchParams({ employee: id, panel: "open" }));
  const inviteHref = keep(new URLSearchParams({ invite: "open", panel: "open" }));
  const openCard = (id: string) => {
    void navigate(employeeHref(id));
  };
  const closeCard = () => {
    void navigate(`${PATH}?panel=${wide ? "open" : "closed"}`, { replace: true });
  };

  const otherActiveAdmins = (id: string) =>
    items.filter((e) => e.id !== id && e.status !== "disabled" && e.roles.some(isSystemAdmin))
      .length;

  let body;
  if (list.isPending) {
    body = <Skeleton active paragraph={{ rows: 6 }} title={false} />;
  } else if (list.isError) {
    body = (
      <EmptyState
        title={t("modules:admin.org.loadError.title")}
        text={t("modules:admin.org.loadError.text")}
        action={
          <Button
            onClick={() => {
              void list.refetch();
            }}
          >
            {t("modules:admin.org.loadError.retry")}
          </Button>
        }
      />
    );
  } else if (items.length === 0) {
    body = (
      <EmptyState
        title={t("modules:admin.org.empty.title")}
        text={t("modules:admin.org.empty.text")}
        action={
          editable ? (
            <Button onClick={() => void navigate(inviteHref)}>
              {t("modules:admin.org.empty.action")}
            </Button>
          ) : undefined
        }
      />
    );
  } else if (filtered.length === 0) {
    body = (
      <EmptyState
        title={t("modules:admin.org.noMatch.title")}
        text={t("modules:admin.org.noMatch.text")}
        action={
          <Button
            onClick={() => {
              setQuery("");
              setStatus("all");
            }}
          >
            {t("modules:admin.org.noMatch.action")}
          </Button>
        }
      />
    );
  } else {
    body = (
      <EmployeeList
        items={filtered}
        selectedId={selected?.id ?? null}
        hrefOf={employeeHref}
        compact={compact}
      />
    );
  }

  let panel = null;
  if (inviting) {
    panel = (
      <div className="pf-panel-stack">
        <h3 style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>
          {t("modules:admin.org.invite.title")}
        </h3>
        <InviteEmployeeForm
          // Повторное нажатие «Пригласить сотрудника» ведёт на тот же адрес, но с новым ключом навигации: форма чистая.
          key={location.key}
          onInvited={(employee) => {
            openCard(employee.id);
          }}
          onOpenCard={openCard}
          onCancel={closeCard}
        />
      </div>
    );
  } else if (selectedId) {
    if (list.isPending) panel = <Skeleton active paragraph={{ rows: 5 }} />;
    else if (selected)
      panel = (
        <EmployeeCard
          key={selected.id}
          employee={selected}
          selfId={me.id}
          canEdit={editable}
          otherActiveAdmins={otherActiveAdmins(selected.id)}
        />
      );
    else if (!list.isError)
      panel = (
        <EmptyState
          level={3}
          compact
          title={t("modules:admin.org.cardError.title")}
          text={t("modules:admin.org.cardError.text")}
        />
      );
  }

  return (
    <>
      <PageHeader
        title={title}
        subtitle={editable ? t("modules:admin.org.subtitle") : t("modules:admin.org.readOnly")}
      />
      <div ref={blockRef}>
        <Card styles={{ body: { padding: 0 } }}>
          <div className="pf-org-filters">
            <Input.Search
              allowClear
              value={query}
              onChange={(event) => {
                setQuery(event.target.value);
              }}
              aria-label={t("modules:admin.org.search.label")}
              placeholder={t("modules:admin.org.search.placeholder")}
              style={{ maxWidth: 320 }}
            />
            <Select<EmployeeStatus | "all">
              value={status}
              onChange={setStatus}
              aria-label={t("modules:admin.org.statusFilter.label")}
              style={{ minWidth: 180 }}
              options={[
                { value: "all", label: t("modules:admin.org.statusFilter.all") },
                ...EMPLOYEE_STATUSES.map((value) => ({
                  value,
                  label: t(`modules:admin.org.status.${value}`),
                })),
              ]}
            />
            {list.data ? (
              <span className="pf-hint" aria-live="polite">
                {t("modules:admin.org.count", { count: filtered.length })}
              </span>
            ) : null}
          </div>
          {body}
        </Card>
      </div>
      {panel ? <PanelPortal tab="card">{panel}</PanelPortal> : null}
    </>
  );
}
