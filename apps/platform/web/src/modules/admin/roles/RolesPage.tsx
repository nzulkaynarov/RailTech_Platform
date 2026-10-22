import { useQueryClient } from "@tanstack/react-query";
import { App, Button, Card, Skeleton } from "antd";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { PanelPortal } from "../../../app/shell/PanelSlot";
import { useViewport } from "../../../app/shell/useViewport";
import type { Role } from "../../../shared/api/generated/model";
import {
  getGetMeQueryKey,
  getGetSessionQueryKey,
  getListEmployeesQueryKey,
  getListRolesQueryKey,
  useCreateRole,
  useDeleteRole,
  useListEmployees,
  useListRoles,
  useUpdateRole,
} from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { PlusIcon } from "../../../shared/ui/icons";
import { NEW_ROLE, type RoleDraft, changesOf, draftOf, newDraft } from "./draft";
import { LevelMark, type MatrixColumn, RoleMatrix } from "./RoleMatrix";
import { RoleEditor, SystemRoleCard } from "./RoleEditor";

import "../../../features/assign-role/assign-role.css";
import "./roles.css";

const PATH = "/admin/roles";

/** Сотрудники выбранной роли (вкладка «Сотрудники» бокового окна): ссылки на карточки в Оргструктуре. */
function RoleEmployees({ role }: { role: Role }) {
  const { t } = useTranslation("modules");
  const list = useListEmployees();
  const holders = (list.data?.items ?? []).filter((e) => e.roles.some((r) => r.id === role.id));
  if (list.isPending) return <Skeleton active paragraph={{ rows: 3 }} title={false} />;
  return (
    <div className="pf-panel-stack">
      <h3 style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>
        {t("admin.roles.employeesTitle", { name: role.name })}
      </h3>
      {holders.length === 0 ? (
        <p className="pf-hint" style={{ margin: 0 }}>
          {t("admin.roles.employeesEmpty")}
        </p>
      ) : (
        <ul className="pf-role-employees">
          {holders.map((employee) => (
            <li key={employee.id}>
              <span>
                {employee.name}
                {employee.position ? (
                  <span className="pf-hint" style={{ display: "block" }}>
                    {employee.position}
                  </span>
                ) : null}
              </span>
              <Link
                className="pf-focusable"
                to={`/admin/org?employee=${encodeURIComponent(employee.id)}&panel=open`}
                aria-label={t("admin.roles.openEmployee", { name: employee.name })}
              >
                {t("admin.roles.change")}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * Admin · Ролевая матрица (SPEC-v3 §7.6, ADR-0012, R-2): роли — данные. Строки — разделы каталога по модулям, столбцы —
 * роли компании; системные роли («Администратор», «Директор») только для чтения. Выбранная роль (`?role=<id>`) редактируется
 * в своём столбце и в боковом окне; «Создать роль» (`?role=new`) — с нуля или из шаблона. Перед сохранением — «Что
 * произойдёт» из предпросмотра CRM. Матрицы ролей видит и меняет только администратор (раздел `admin` — полный).
 */
export function RolesPage() {
  const { t } = useTranslation(["modules", "shell"]);
  const { me } = useAuth();
  const editable = canEdit(me, "admin");
  const title = t("modules:admin.roles.title");
  useDocumentTitle(title);

  if (!editable) {
    return (
      <>
        <PageHeader title={title} subtitle={t("modules:admin.roles.subtitle")} />
        <Card>
          <EmptyState
            title={t("modules:admin.roles.readOnly.title")}
            text={t("modules:admin.roles.readOnly.text")}
          />
        </Card>
      </>
    );
  }
  return <RolesEditorPage title={title} selfRoleIds={me.roles.map((r) => r.id)} />;
}

function RolesEditorPage({ title, selfRoleIds }: { title: string; selfRoleIds: string[] }) {
  const { t } = useTranslation(["modules", "shell"]);
  const { message } = App.useApp();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { wide } = useViewport();
  const [params] = useSearchParams();
  const list = useListRoles();
  const roles = useMemo(() => list.data?.items ?? [], [list.data]);
  const selectedId = params.get("role");
  const selected = roles.find((role) => role.id === selectedId) ?? null;
  const creating = selectedId === NEW_ROLE;

  // Черновик выбранной изменяемой роли (или новой): сбрасывается при выборе другой роли.
  const base: RoleDraft | null = creating
    ? newDraft(null)
    : selected && !selected.system
      ? draftOf(selected)
      : null;
  const baseKey = creating ? NEW_ROLE : selected ? `${selected.id}:${selected.updated_at}` : "";
  // Черновик привязан к ключу роли: выбрали другую роль (или роль сохранили) — черновик берётся заново (React:
  // «изменение состояния при смене входных данных» прямо при отрисовке, без эффекта).
  const [state, setState] = useState<{ key: string; draft: RoleDraft | null }>({
    key: baseKey,
    draft: base,
  });
  let current = state.draft;
  if (state.key !== baseKey) {
    setState({ key: baseKey, draft: base });
    current = base;
  }
  const setDraft = (next: RoleDraft) => {
    setState({ key: baseKey, draft: next });
  };

  const href = (id: string | null) => {
    const next = new URLSearchParams({ panel: "open", tab: "role" });
    if (id) next.set("role", id);
    return `${PATH}?${next.toString()}`;
  };
  const select = (id: string) => {
    void navigate(href(id));
  };
  const closeEditor = () => {
    void navigate(`${PATH}?panel=${wide ? "open" : "closed"}`, { replace: true });
  };

  const refresh = (roleId?: string) => {
    void queryClient.invalidateQueries({ queryKey: getListRolesQueryKey() });
    void queryClient.invalidateQueries({ queryKey: getListEmployeesQueryKey() });
    if (roleId && selfRoleIds.includes(roleId)) {
      void queryClient.invalidateQueries({ queryKey: getGetMeQueryKey() });
      void queryClient.invalidateQueries({ queryKey: getGetSessionQueryKey() });
    }
  };
  const create = useCreateRole({
    mutation: {
      onSuccess: (role) => {
        refresh();
        void message.success(t("modules:admin.roles.createdToast", { name: role.name }));
        void navigate(href(role.id), { replace: true });
      },
    },
  });
  const update = useUpdateRole({
    mutation: {
      onSuccess: (role) => {
        refresh(role.id);
        void message.success(t("modules:admin.roles.savedToast"));
      },
    },
  });
  const remove = useDeleteRole({
    mutation: {
      onSuccess: () => {
        refresh();
        void message.success(t("modules:admin.roles.deletedToast"));
        closeEditor();
      },
    },
  });
  // Ошибки прошлой роли не переходят к следующей.
  const { reset: resetCreate } = create;
  const { reset: resetUpdate } = update;
  const { reset: resetRemove } = remove;
  useEffect(() => {
    resetCreate();
    resetUpdate();
    resetRemove();
  }, [selectedId, resetCreate, resetUpdate, resetRemove]);

  const save = () => {
    if (!current) return;
    if (creating) {
      create.mutate({
        data: {
          name: current.name.trim(),
          description: current.description.trim(),
          access: current.access,
          restricted_fields: current.restricted_fields,
        },
      });
      return;
    }
    if (!selected || !base) return;
    const changes = changesOf(base, current);
    update.mutate({
      id: selected.id,
      data: {
        ...(changes.name ? { name: current.name.trim() } : {}),
        ...(changes.description ? { description: current.description.trim() } : {}),
        ...(changes.access ? { access: current.access } : {}),
        ...(changes.fields ? { restricted_fields: current.restricted_fields } : {}),
      },
    });
  };

  const columns: MatrixColumn[] = [
    ...roles.map((role) =>
      current && role.id === selectedId
        ? {
            id: role.id,
            name: role.name,
            system: role.system,
            access: current.access,
            restricted_fields: current.restricted_fields,
          }
        : {
            id: role.id,
            name: role.name,
            system: role.system,
            access: role.access,
            restricted_fields: role.restricted_fields,
          },
    ),
    ...(creating && current
      ? [
          {
            id: NEW_ROLE,
            name: current.name.trim() || t("modules:admin.roles.new.title"),
            system: false,
            access: current.access,
            restricted_fields: current.restricted_fields,
          },
        ]
      : []),
  ];

  let body;
  if (list.isPending) {
    body = <Skeleton active paragraph={{ rows: 10 }} title={false} />;
  } else if (list.isError) {
    body = (
      <EmptyState
        title={t("modules:admin.roles.loadError.title")}
        text={t("modules:admin.roles.loadError.text")}
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
  } else {
    body = (
      <RoleMatrix
        columns={columns}
        selectedId={selectedId}
        onSelect={select}
        draft={current}
        onDraft={setDraft}
      />
    );
  }

  let panel = null;
  if (creating && current) {
    panel = (
      <RoleEditor
        key={NEW_ROLE}
        role={null}
        base={newDraft(null)}
        draft={current}
        onDraft={setDraft}
        onReset={closeEditor}
        onSave={save}
        saving={create.isPending}
        saveError={create.error}
        onDelete={() => undefined}
        deleting={false}
        deleteError={null}
      />
    );
  } else if (selected?.system) {
    panel = <SystemRoleCard role={selected} />;
  } else if (selected && base && current) {
    panel = (
      <RoleEditor
        key={selected.id}
        role={selected}
        base={base}
        draft={current}
        onDraft={setDraft}
        onReset={() => {
          setDraft(base);
        }}
        onSave={save}
        saving={update.isPending}
        saveError={update.error}
        onDelete={() => {
          remove.mutate({ id: selected.id });
        }}
        deleting={remove.isPending}
        deleteError={remove.error}
      />
    );
  } else if (selectedId && !list.isPending) {
    panel = (
      <EmptyState
        level={3}
        compact
        title={t("modules:admin.roles.notFound.title")}
        text={t("modules:admin.roles.notFound.text")}
      />
    );
  }

  return (
    <>
      <PageHeader
        title={title}
        subtitle={t("modules:admin.roles.subtitle")}
        extra={
          <div className="pf-roles-legend" style={{ justifyContent: "flex-end" }}>
            <span>
              <LevelMark level="full" />
              <span aria-hidden="true">{t("modules:admin.roles.level.full")}</span>
            </span>
            <span>
              <LevelMark level="read" />
              <span aria-hidden="true">{t("modules:admin.roles.level.read")}</span>
            </span>
            <span>
              <LevelMark level={undefined} />
              <span aria-hidden="true">{t("modules:admin.roles.level.hidden")}</span>
            </span>
            <Button
              icon={<PlusIcon />}
              onClick={() => {
                select(NEW_ROLE);
              }}
              disabled={creating}
            >
              {t("modules:admin.roles.create")}
            </Button>
          </div>
        }
      />
      <Card styles={{ body: { padding: 0 } }}>{body}</Card>
      {panel ? <PanelPortal tab="role">{panel}</PanelPortal> : null}
      {selected ? (
        <PanelPortal tab="employees">
          <RoleEmployees role={selected} />
        </PanelPortal>
      ) : null}
    </>
  );
}
