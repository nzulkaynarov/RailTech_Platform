import { keepPreviousData } from "@tanstack/react-query";
import { Button, Card, Pagination, Skeleton } from "antd";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useSearchParams } from "react-router";

import { PanelPortal } from "../../../app/shell/PanelSlot";
import { useViewport } from "../../../app/shell/useViewport";
import type { AuditEntry, ListAuditParams } from "../../../shared/api/generated/model";
import { useListAudit, useListEmployees } from "../../../shared/api/generated/platform-bff";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { AuditEntryCard } from "./AuditEntryCard";
import { AuditFilters } from "./AuditFilters";
import { type AuditFilterValues, NO_FILTERS, hasFilters } from "./filters";
import { AuditList } from "./AuditList";
import { JournalFilter } from "../journal/JournalFilter";
import { companyDayStart } from "./describe";

import "./audit.css";

const PATH = "/admin/audit";
const PAGE = 50;
/** Уже этой ширины блока таблица из четырёх колонок не помещается без прокрутки */
const TABLE_MIN_WIDTH = 700;

/**
 * Admin · Журнал аудита (W13-A6, BFF 0.12.0): кто, что и когда изменил. Пункт меню раздела Admin рядом с Оргструктурой:
 * журнал — рабочий экран с фильтрами и страницами, а не вкладка одной карточки (SPEC-v3 §6.2 перечисляет минимум пунктов,
 * §7.6 требует «журнал — кто и когда»). Читают администратор и директор (раздел `admin` — чтение); записи не меняются.
 * Запись открывается в боковом окне без перехода (`?entry=<id>`); сужение до объекта — `?entity_type=&entity_id=`.
 */
export function AuditPage() {
  const { t } = useTranslation(["audit", "modules"]);
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { wide } = useViewport();
  // Один «Журнал» (W15-H4): заголовок — общий, фильтр «Действия людей / Обмен между системами» — под ним.
  const title = t("modules:admin.sections.audit");
  useDocumentTitle(title);

  const blockRef = useRef<HTMLDivElement>(null);
  const [blockWidth, setBlockWidth] = useState(0);
  useEffect(() => {
    const element = blockRef.current;
    if (!element || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(([entry]) => {
      setBlockWidth(entry?.contentRect.width ?? 0);
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);
  const compact = blockWidth > 0 ? blockWidth < TABLE_MIN_WIDTH : !wide;

  const entityId = params.get("entity_id");
  const [filters, setFilters] = useState<AuditFilterValues>({
    ...NO_FILTERS,
    entityType: params.get("entity_type") ?? "",
    action: params.get("action") ?? "",
    actor: params.get("actor_id") ?? "",
  });
  const [page, setPage] = useState(1);
  const update = (next: AuditFilterValues) => {
    setFilters(next);
    setPage(1);
  };
  const reset = () => {
    setFilters(NO_FILTERS);
    setPage(1);
    if (entityId) void navigate(PATH, { replace: true });
  };

  const query: ListAuditParams = {
    limit: PAGE,
    offset: (page - 1) * PAGE,
    ...(filters.actor ? { actor_id: filters.actor } : {}),
    ...(filters.action ? { action: filters.action } : {}),
    ...(filters.entityType ? { entity_type: filters.entityType } : {}),
    ...(entityId ? { entity_id: entityId } : {}),
    ...(companyDayStart(filters.from) ? { from: companyDayStart(filters.from) } : {}),
    ...(companyDayStart(filters.to, 1) ? { to: companyDayStart(filters.to, 1) } : {}),
    ...(filters.logins ? { include_logins: true } : {}),
  };
  const list = useListAudit(query, { query: { placeholderData: keepPreviousData } });
  const employees = useListEmployees();
  const actors = useMemo(
    () => (employees.data?.items ?? []).map((e) => ({ id: e.id, name: e.name })),
    [employees.data],
  );
  const names = useMemo(() => new Map(actors.map((a) => [a.id, a.name])), [actors]);
  const items = list.data?.items ?? [];

  // Выбранная запись переживает смену страницы и фильтров: запоминаем её, а не ищем в текущей выдаче.
  const entryParam = params.get("entry");
  const [picked, setPicked] = useState<AuditEntry | null>(null);
  const fromList = entryParam ? items.find((e) => e.id === entryParam) : undefined;
  if (fromList && picked?.id !== fromList.id) setPicked(fromList);
  const selected = entryParam && (fromList ?? (picked?.id === entryParam ? picked : null));

  const entryHref = (id: string) => {
    const next = new URLSearchParams(params);
    next.set("entry", id);
    next.set("panel", "open");
    return `${PATH}?${next.toString()}`;
  };

  let body;
  if (list.isPending) {
    body = <Skeleton active paragraph={{ rows: 8 }} title={false} />;
  } else if (list.isError) {
    body = (
      <EmptyState
        title={t("audit:loadError.title")}
        text={t("audit:loadError.text")}
        action={
          <Button
            onClick={() => {
              void list.refetch();
            }}
          >
            {t("audit:loadError.retry")}
          </Button>
        }
      />
    );
  } else if (items.length === 0 && hasFilters(filters, entityId)) {
    body = (
      <EmptyState
        title={t("audit:noMatch.title")}
        text={t("audit:noMatch.text")}
        action={<Button onClick={reset}>{t("audit:noMatch.action")}</Button>}
      />
    );
  } else if (items.length === 0) {
    body = <EmptyState title={t("audit:empty.title")} text={t("audit:empty.text")} />;
  } else {
    body = (
      <AuditList
        items={items}
        selectedId={selected ? selected.id : null}
        hrefOf={entryHref}
        names={names}
        compact={compact}
      />
    );
  }

  const total = list.data?.total ?? 0;
  const closeHref = () => {
    const next = new URLSearchParams(params);
    next.delete("entry");
    next.set("panel", wide ? "open" : "closed");
    return `${PATH}?${next.toString()}`;
  };

  return (
    <>
      <PageHeader title={title} subtitle={t("audit:page.subtitle")} />
      <JournalFilter current="people" />
      <div ref={blockRef}>
        <Card styles={{ body: { padding: 0 } }}>
          <AuditFilters
            value={filters}
            onChange={update}
            actors={actors}
            entityId={entityId}
            onReset={reset}
          />
          {body}
          {list.data && total > 0 ? (
            <div className="pf-audit-footer">
              <span className="pf-hint" aria-live="polite">
                {t("audit:count", { count: total })}
              </span>
              {total > PAGE ? (
                <Pagination
                  current={page}
                  pageSize={PAGE}
                  total={total}
                  showSizeChanger={false}
                  size="small"
                  aria-label={t("audit:pager")}
                  onChange={setPage}
                />
              ) : null}
            </div>
          ) : null}
        </Card>
      </div>
      <PanelPortal tab="card">
        {selected ? (
          <AuditEntryCard key={selected.id} entry={selected} names={names} />
        ) : entryParam && !list.isPending ? (
          <EmptyState
            level={3}
            compact
            title={t("audit:card.notFound")}
            text={t("audit:card.hint")}
            action={
              <Button
                onClick={() => {
                  void navigate(closeHref(), { replace: true });
                }}
              >
                {t("audit:filters.reset")}
              </Button>
            }
          />
        ) : (
          <EmptyState
            level={3}
            compact
            title={t("audit:card.hintTitle")}
            text={t("audit:card.hint")}
          />
        )}
      </PanelPortal>
    </>
  );
}
