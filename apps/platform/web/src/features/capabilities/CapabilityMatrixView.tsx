import { Alert, Button, Skeleton } from "antd";
import { type CSSProperties, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { CapabilityMatrix, CapabilityText } from "../../shared/api/generated/model";
import { useGetCapabilityMatrix } from "../../shared/api/generated/platform-bff";
import { useFormat } from "../../shared/lib/useFormat";
import { EmptyState } from "../../shared/ui/EmptyState";
import { MoneyText } from "../../shared/ui/MoneyText";
import { LevelTag } from "./LevelTag";
import { useKindNames } from "./useKindNames";
import { WarningsList } from "./WarningsList";
import { pickText, stepLabel } from "./model";

import "./capabilities.css";

export interface CapabilityMatrixViewProps {
  /** Адрес карточки человека в боковом окне */
  hrefOf: (id: string) => string;
  /** Подсвеченный (открытый) сотрудник */
  selectedId: string | null;
}

/**
 * «Кто что может» (ДОСТ-1): строки — возможности по шагам сделки, столбцы — действующие сотрудники, в клетке — уровень
 * («Смотреть / Работать / Решать»), «не всё» и пометка «единственный, кто решает». Внизу — подпись и «отвечает за» отдельно от
 * возможностей. Только чтение: нажатие на имя открывает карточку человека.
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

function MatrixTable({
  matrix,
  hrefOf,
  selectedId,
  language,
}: CapabilityMatrixViewProps & { matrix: CapabilityMatrix; language: string }) {
  const { t } = useTranslation("capabilities");
  const format = useFormat();
  const kindName = useKindNames(matrix.signing_known);
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
      <p className="pf-hint" style={{ margin: "0 0 8px" }}>
        {t("matrix.readOnly")}
      </p>
      <div className="pf-cap-legend" role="group" aria-label={t("legend.label")}>
        {(["view", "work", "decide"] as const).map((level) => (
          <LevelTag key={level} level={level} />
        ))}
        <span>{t("legend.partial")}</span>
        <span className="pf-cap-only">{t("legend.only")}</span>
        <span>{t("matrix.hint")}</span>
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
                {t("matrix.capability")}
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
                    to={hrefOf(employee.person.id)}
                    aria-label={t("matrix.open", { name: employee.person.name })}
                  >
                    {employee.person.name}
                  </Link>
                  {employee.person.position ? (
                    <span className="pf-cap-person-roles">{employee.person.position}</span>
                  ) : null}
                </div>
              ))}
            </div>
          </div>
          {matrix.groups.map((group) => (
            <div role="rowgroup" key={group.key} aria-label={pickText(group.name, language)}>
              <div role="row" className="pf-cap-line pf-cap-grouprow">
                <div role="columnheader" className="pf-cap-cell pf-cap-groupcell">
                  {pickText(group.name, language)}
                  <span className="pf-cap-group-step pf-hint">
                    {stepLabel(group, language)}
                  </span>
                </div>
              </div>
              {group.capabilities.map((cap) => (
                <div role="row" className="pf-cap-line" key={cap.key} data-capability={cap.key}>
                  <div role="rowheader" className="pf-cap-cell pf-cap-rowhead">
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
                          <span className="pf-cap-only-mark">{t("matrix.onlyMark")}</span>
                        ) : null}
                      </div>
                    );
                  })}
                </div>
              ))}
            </div>
          ))}
          <div role="rowgroup" aria-label={t("matrix.apart")}>
            {matrix.signing_known || matrix.zones_known ? (
              <div role="row" className="pf-cap-line pf-cap-grouprow">
                <div role="columnheader" className="pf-cap-cell pf-cap-groupcell">
                  {t("matrix.apart")}
                </div>
              </div>
            ) : null}
            {matrix.signing_known ? (
              <div role="row" className="pf-cap-line pf-cap-apart" data-testid="cap-row-signing">
                <div role="rowheader" className="pf-cap-cell pf-cap-rowhead">
                  {t("matrix.signs")}
                </div>
                {matrix.employees.map((employee) => (
                  <div role="cell" className="pf-cap-cell" key={employee.person.id}>
                    {employee.signing.length === 0 ? (
                      <span className="pf-hint">{t("matrix.noSigning")}</span>
                    ) : (
                      employee.signing.map((item) => (
                        <div key={item.id}>
                          {item.kinds.map(kindName).join(", ")}
                          {" · "}
                          {item.limit ? (
                            <MoneyText value={item.limit.amount} currency={item.limit.currency} />
                          ) : (
                            t("matrix.unlimited")
                          )}
                          {item.valid_to
                            ? ` · ${t("card.signingUntil", { date: format.date(item.valid_to) })}`
                            : ""}
                        </div>
                      ))
                    )}
                  </div>
                ))}
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
                      employee.zones.map((zone) => (
                        <div key={`${zone.id}-${zone.role}`}>
                          {pickText(zone.name, language)} · {t(`card.responsibleRole.${zone.role}`)}
                        </div>
                      ))
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
