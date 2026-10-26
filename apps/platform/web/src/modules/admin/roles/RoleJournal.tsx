import { Button, Skeleton } from "antd";
import type { TFunction } from "i18next";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import { RoleChangeSummary } from "../../../entities/role/RoleChangeSummary";
import type { Role, RoleChange } from "../../../shared/api/generated/model";
import { useGetRoleJournal } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { History } from "../../../shared/ui/History";

import "../audit/audit.css";

const PAGE = 20;

function titleOf(change: RoleChange, t: TFunction) {
  if (change.action === "create") {
    return t("role.created", { name: change.after?.name ?? "" });
  }
  return t(change.action === "delete" ? "role.deleted" : "role.updated");
}

/**
 * Вкладка «Журнал» бокового окна роли (BFF 0.12.0, `GET /admin/roles/{id}/journal`): кто, когда и что менял в роли —
 * создание и каждое сохранение, новые первыми. Читают администратор и директор; записи только читаются.
 */
export function RoleJournal({ role }: { role: Role }) {
  const { t } = useTranslation("audit");
  const format = useFormat();
  const [limit, setLimit] = useState(PAGE);
  const journal = useGetRoleJournal(role.id, { limit });

  let body;
  if (journal.isPending) {
    body = <Skeleton active paragraph={{ rows: 4 }} title={false} />;
  } else if (journal.isError) {
    body = (
      <EmptyState
        level={3}
        compact
        title={t("roleJournal.error")}
        text={t("roleJournal.errorText")}
        action={
          <Button
            onClick={() => {
              void journal.refetch();
            }}
          >
            {t("roleJournal.retry")}
          </Button>
        }
      />
    );
  } else if (journal.data.items.length === 0) {
    body = (
      <EmptyState
        level={3}
        compact
        title={t("roleJournal.empty")}
        text={t("roleJournal.emptyText")}
      />
    );
  } else {
    body = (
      <>
        <ol className="pf-audit-journal" aria-label={t("roleJournal.label")}>
          {journal.data.items.map((change) => (
            <li key={change.id}>
              <History
                items={[
                  {
                    state: "done",
                    title: titleOf(change, t),
                    meta: t("roleJournal.by", {
                      when: format.date(change.at, "datetime"),
                      who: change.actor_name ?? t("roleJournal.unknownAuthor"),
                    }),
                  },
                ]}
              />
              <div className="pf-audit-journal-body">
                {change.action === "update" || change.action === "create" ? (
                  <RoleChangeSummary change={change} />
                ) : null}
              </div>
            </li>
          ))}
        </ol>
        {journal.data.total > journal.data.items.length ? (
          <Button
            block
            loading={journal.isFetching}
            onClick={() => {
              setLimit((n) => n + PAGE);
            }}
          >
            {t("roleJournal.more")}
          </Button>
        ) : null}
      </>
    );
  }

  return (
    <div className="pf-panel-stack">
      <h3 style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>
        {t("roleJournal.title", { name: role.name })}
      </h3>
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("roleJournal.hint")}
      </p>
      {body}
      <Link
        className="pf-focusable"
        to={`/admin/audit?entity_type=platform_role&entity_id=${role.id}`}
      >
        {t("roleJournal.all")}
      </Link>
    </div>
  );
}
