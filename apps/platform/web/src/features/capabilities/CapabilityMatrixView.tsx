import { Alert, Button, Skeleton, Tooltip } from "antd";
import { type CSSProperties, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type {
  CapabilityAuthority,
  CapabilityMatrix,
  CapabilityText,
  CapabilityZone,
} from "../../shared/api/generated/model";
import { useGetCapabilityMatrix } from "../../shared/api/generated/platform-bff";
import { currencyLabel } from "../../shared/lib/money";
import { useFormat } from "../../shared/lib/useFormat";
import { EmptyState } from "../../shared/ui/EmptyState";
import { MoneyText } from "../../shared/ui/MoneyText";
import { LevelTag } from "./LevelTag";
import { useKindNames } from "./useKindNames";
import { WarningsList } from "./WarningsList";
import { areaLevel } from "./areas";
import { pickText } from "./model";

import "./capabilities.css";

export interface CapabilityMatrixViewProps {
  /** Адрес карточки человека в боковом окне */
  hrefOf: (id: string) => string;
  /** Подсвеченный (открытый) сотрудник */
  selectedId: string | null;
}

/**
 * «Кто что может» (ДОСТ-1, пересборка ДОСТ-1п): строки — области сделки (их пять), столбцы — действующие сотрудники, в
 * клетке — высший уровень человека в области («Смотреть / Работать / Решать»); «не всё» — только в раскрытых строках; строка
 * раскрывается в возможности. Внизу — «Подписывает» и «Отвечает за» одним коротким значением в клетке, подробности — в подсказке.
 * Только чтение: нажатие на имя открывает страницу человека.
 */
export function CapabilityMatrixView({ hrefOf, selectedId }: CapabilityMatrixViewProps) {
  const { t, i18n } = useTranslation("capabilities");
  const query = useGetCapabilityMatrix();
  if (query.isPending) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (query.isError) {
    return (
      <Alert
        type="error"
        showIcon
        message={t("matrix.unavailable")}
        action={
          <Button
            size="small"
            onClick={() => {
              void query.refetch();
            }}
          >
            {t("matrix.retry")}
          </Button>
        }
      />
    );
  }
  if (query.data.employees.length === 0) {
    return <EmptyState title={t("matrix.empty.title")} text={t("matrix.empty.text")} level={2} />;
  }
  return (
    <MatrixTable
      matrix={query.data}
      hrefOf={hrefOf}
      selectedId={selectedId}
      language={i18n.language}
    />
  );
}

function signingShort(
  items: readonly CapabilityAuthority[],
  t: (key: string) => string,
): { text: string; money?: CapabilityAuthority["limit"] } | null {
  if (items.length === 0) return null;
  if (items.some((item) => !item.limit)) return { text: t("matrix.unlimited") };
  const first = items[0]?.limit;
  if (!first) return null;
  const same = items.flatMap((item) =>
    item.limit?.currency === first.currency ? [item.limit] : [],
  );
  const top = same.reduce((a, b) => (Number(b.amount) > Number(a.amount) ? b : a), first);
  return { text: "", money: top };
}

function zoneShort(zones: readonly CapabilityZone[], language: string): string {
  const first = zones[0];
  if (!first) return "";
  const more = new Set(zones.map((zone) => zone.id)).size - 1;
  return `${pickText(first.name, language)}${more > 0 ? ` +${String(more)}` : ""}`;
}

function MatrixTable({
  matrix,
  hrefOf,
  selectedId,
  language,
}: CapabilityMatrixViewProps & { matrix: CapabilityMatrix; language: string }) {
  const { t } = useTranslation("capabilities");
  const format = useFormat();
  const kindName = useKindNames(matrix.signing_known);
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const toggle = (key: string) => {
    const next = new Set(open);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setOpen(next);
  };
  const allOpen = open.size === matrix.groups.length;
  const names = useMemo(() => {
    const map: Record<string, CapabilityText> = {};
    for (const group of matrix.groups)
      for (const cap of group.capabilities) map[cap.key] = cap.name;
    return map;
  }, [matrix.groups]);
  const only = useMemo(
    () =>
      new Set(
        matrix.warnings
          .filter((w) => w.code === "only_decider" && w.person && w.capability)
          .map((w) => `${w.person?.id ?? ""}:${w.capability ?? ""}`),
      ),
    [matrix.warnings],
  );
  const columns = matrix.employees.length;
  return (
    <div data-testid="cap-matrix">
      <WarningsList warnings={matrix.warnings} names={names} />
      <div className="pf-cap-legend" role="group" aria-label={t("legend.label")}>
        {(["view", "work", "decide"] as const).map((level) => (
          <LevelTag key={level} level={level} />
        ))}
        <span>{t("legend.partial")}</span>
        <span className="pf-cap-only">
          <span className="pf-cap-only-mark" aria-hidden="true" /> {t("legend.only")}
        </span>
      </div>
      <div className="pf-cap-matrix-wrap" tabIndex={0} role="region" aria-label={t("matrix.label")}>
        <div
          className="pf-cap-matrix"
          role="table"
          aria-label={t("matrix.label")}
          style={{ "--pf-cap-cols": columns } as CSSProperties}
        >
          <div role="rowgroup">
            <div role="row" className="pf-cap-line">
              <div role="columnheader" className="pf-cap-cell pf-cap-corner">
                <button
                  type="button"
                  className="pf-cap-more"
                  onClick={() => {
                    setOpen(allOpen ? new Set() : new Set(matrix.groups.map((group) => group.key)));
                  }}
                >
                  {allOpen ? t("matrix.collapseAll") : t("matrix.expandAll")}
                </button>
              </div>
              {matrix.employees.map((employee) => (
                <div
                  key={employee.person.id}
                  role="columnheader"
                  className="pf-cap-cell"
                  aria-current={employee.person.id === selectedId ? "true" : undefined}
                >
                  <Link
                    className="pf-cap-person"
                    title={employee.person.name}
                    to={hrefOf(employee.person.id)}
                    aria-label={t("matrix.open", { name: employee.person.name })}
                  >
                    {employee.person.name}
                  </Link>
                  {employee.person.position ? (
                    <span className="pf-cap-person-roles" title={employee.person.position}>
                      {employee.person.position}
                    </span>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
          {matrix.groups.map((group) => {
            const expanded = open.has(group.key);
            const label = pickText(group.name, language);
            return (
              <div role="rowgroup" key={group.key} aria-label={label} data-area={group.key}>
                <div role="row" className="pf-cap-line pf-cap-arearow">
                  <div role="rowheader" className="pf-cap-cell pf-cap-rowhead pf-cap-areahead">
                    <button
                      type="button"
                      className="pf-cap-areabtn"
                      aria-expanded={expanded}
                      onClick={() => {
                        toggle(group.key);
                      }}
                    >
                      <span className="pf-cap-chevron" aria-hidden="true">
                        {expanded ? "▾" : "▸"}
                      </span>
                      <span>{label}</span>
                    </button>
                  </div>
                  {matrix.employees.map((employee) => {
                    const level = areaLevel(
                      group.capabilities.map((cap) => ({
                        level: employee.cells[cap.key]?.level ?? "none",
                      })),
                    );
                    const decider = group.capabilities.some((cap) =>
                      only.has(`${employee.person.id}:${cap.key}`),
                    );
                    return (
                      <div role="cell" className="pf-cap-cell" key={employee.person.id}>
                        {level === "none" ? (
                          <span className="pf-hint" aria-label={t("level.none")}>
                            —
                          </span>
                        ) : (
                          <LevelTag level={level} />
                        )}
                        {decider ? (
                          <span
                            className="pf-cap-only-mark"
                            role="img"
                            aria-label={t("matrix.onlyMark")}
                            title={t("matrix.onlyMark")}
                          />
                        ) : null}
                      </div>
                    );
                  })}
                </div>
                {expanded
                  ? group.capabilities.map((cap) => (
                      <div
                        role="row"
                        className="pf-cap-line pf-cap-caprow"
                        key={cap.key}
                        data-capability={cap.key}
                      >
                        <div role="rowheader" className="pf-cap-cell pf-cap-rowhead pf-cap-caphead">
                          {pickText(cap.name, language)}
                        </div>
                        {matrix.employees.map((employee) => {
                          const cell = employee.cells[cap.key];
                          const level = cell?.level ?? "none";
                          return (
                            <div role="cell" className="pf-cap-cell" key={employee.person.id}>
                              {level === "none" ? (
                                <span className="pf-hint" aria-label={t("level.none")}>
                                  —
                                </span>
                              ) : (
                                <LevelTag level={level} partial={cell?.partial ?? false} />
                              )}
                              {only.has(`${employee.person.id}:${cap.key}`) ? (
                                <span
                                  className="pf-cap-only-mark"
                                  role="img"
                                  aria-label={t("matrix.onlyMark")}
                                  title={t("matrix.onlyMark")}
                                />
                              ) : null}
                            </div>
                          );
                        })}
                      </div>
                    ))
                  : null}
              </div>
            );
          })}
          <div role="rowgroup" aria-label={t("matrix.apart")}>
            {matrix.signing_known ? (
              <div role="row" className="pf-cap-line pf-cap-apart" data-testid="cap-row-signing">
                <div role="rowheader" className="pf-cap-cell pf-cap-rowhead">
                  {t("matrix.signs")}
                </div>
                {matrix.employees.map((employee) => {
                  const short = signingShort(employee.signing, t);
                  return (
                    <div role="cell" className="pf-cap-cell" key={employee.person.id}>
                      {short === null ? (
                        <span className="pf-hint">{t("matrix.noSigning")}</span>
                      ) : (
                        <Tooltip
                          title={
                            <div>
                              {employee.signing.map((item) => (
                                <div key={item.id}>
                                  {item.kinds.map(kindName).join(", ")}
                                  {" · "}
                                  {item.limit ? (
                                    <MoneyText
                                      value={item.limit.amount}
                                      currency={item.limit.currency}
                                    />
                                  ) : (
                                    t("matrix.unlimited")
                                  )}
                                  {item.valid_to
                                    ? ` · ${t("card.signingUntil", { date: format.date(item.valid_to) })}`
                                    : ""}
                                </div>
                              ))}
                            </div>
                          }
                        >
                          <span className="pf-cap-short" tabIndex={0}>
                            {short.money
                              ? t("matrix.upTo", {
                                  amount: `${new Intl.NumberFormat(language, {
                                    notation: "compact",
                                    maximumFractionDigits: 1,
                                  }).format(
                                    Number(short.money.amount),
                                  )} ${currencyLabel(short.money.currency, language)}`,
                                })
                              : short.text}
                          </span>
                        </Tooltip>
                      )}
                    </div>
                  );
                })}
              </div>
            ) : null}
            {matrix.zones_known ? (
              <div role="row" className="pf-cap-line pf-cap-apart" data-testid="cap-row-zones">
                <div role="rowheader" className="pf-cap-cell pf-cap-rowhead">
                  {t("matrix.responsible")}
                </div>
                {matrix.employees.map((employee) => (
                  <div role="cell" className="pf-cap-cell" key={employee.person.id}>
                    {employee.zones.length === 0 ? (
                      <span className="pf-hint">{t("matrix.noZones")}</span>
                    ) : (
                      <Tooltip
                        title={
                          <div>
                            {employee.zones.map((zone) => (
                              <div key={`${zone.id}-${zone.role}`}>
                                {pickText(zone.name, language)} ·{" "}
                                {t(`card.responsibleRole.${zone.role}`)}
                              </div>
                            ))}
                          </div>
                        }
                      >
                        <span className="pf-cap-short" tabIndex={0}>
                          {zoneShort(employee.zones, language)}
                        </span>
                      </Tooltip>
                    )}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
