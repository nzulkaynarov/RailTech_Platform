import { Checkbox } from "antd";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";

import {
  MODULES,
  RESOURCE_KEYS,
  RESOURCES,
  RESTRICTED_FIELDS,
  type AccessLevel,
  type ResourceKey,
  type RestrictedField,
} from "../../../app/rbac.generated";
import { fieldLabel, sectionLabel } from "../../../entities/role/roles";
import { findModule } from "../../registry";
import { CheckIcon, LockIcon } from "../../../shared/ui/icons";
import { type RoleDraft, setLevel, toggleField } from "./draft";

/** Столбец матрицы: роль из данных или черновик новой роли. */
export interface MatrixColumn {
  id: string;
  name: string;
  system: boolean;
  access: Partial<Record<string, AccessLevel>>;
  restricted_fields: readonly string[];
}

const FIELDS = Object.keys(RESTRICTED_FIELDS) as RestrictedField[];

/** Уровень словом для скринридера и значком для глаз (легенда над таблицей). */
export function LevelMark({ level }: { level: AccessLevel | undefined }) {
  const { t } = useTranslation("modules");
  if (level === "full") {
    return (
      <>
        <span className="pf-lvl pf-lvl-full" aria-hidden="true">
          <CheckIcon size={11} />
        </span>
        <span className="pf-sr-only">{t("admin.roles.level.full")}</span>
      </>
    );
  }
  if (level === "read") {
    return (
      <>
        <span className="pf-lvl pf-lvl-read" aria-hidden="true">
          <CheckIcon size={10} />
        </span>
        <span className="pf-sr-only">{t("admin.roles.level.read")}</span>
      </>
    );
  }
  return (
    <>
      <span className="pf-lvl-none" aria-hidden="true">
        —
      </span>
      <span className="pf-sr-only">{t("admin.roles.level.hidden")}</span>
    </>
  );
}

function FieldMark({ on }: { on: boolean }) {
  const { t } = useTranslation("modules");
  return on ? (
    <>
      <span className="pf-lvl pf-lvl-full" aria-hidden="true">
        <CheckIcon size={11} />
      </span>
      <span className="pf-sr-only">{t("admin.roles.field.on")}</span>
    </>
  ) : (
    <>
      <span className="pf-lvl-none" aria-hidden="true">
        —
      </span>
      <span className="pf-sr-only">{t("admin.roles.field.off")}</span>
    </>
  );
}

export interface RoleMatrixProps {
  columns: readonly MatrixColumn[];
  /** Выбранный столбец (подсветка, как в макете) */
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** Черновик выбранной роли, если её можно менять: столбец превращается в поля ввода */
  draft: RoleDraft | null;
  onDraft: (next: RoleDraft) => void;
}

/**
 * Матрица «разделы × роли» (SPEC-v3 §4.2, ADR-0012): строки — разделы каталога по модулям, столбцы — роли компании.
 * Ячейка — полный / чтение / скрыто (значок и слово для скринридера). Столбец выбранной изменяемой роли — поля выбора
 * уровня и флажки полей с ограничением; системные роли только для чтения (замок и подпись «системная роль»).
 */
export function RoleMatrix({ columns, selectedId, onSelect, draft, onDraft }: RoleMatrixProps) {
  const { t, i18n } = useTranslation("modules");
  const levelOptions = (key: ResourceKey) => [
    ...(["full", "read"] as const)
      .filter((level) => (RESOURCES[key].levels as readonly string[]).includes(level))
      .map((level) => ({ value: level, label: t(`admin.roles.level.${level}`) })),
    { value: "hidden", label: t("admin.roles.level.hidden") },
  ];
  // Выбранный (и новый) столбец прокручивается в видимую часть таблицы: на 1440 с открытым боковым окном правые
  // столбцы уходят за край. Прокручивается только таблица, страница стоит на месте; учитывается закреплённый столбец.
  const scrollRef = useRef<HTMLDivElement>(null);
  // Ширина столбца меняется вместе с названием (новая роль): ключ — названия столбцов.
  const columnKey = columns.map((column) => `${column.id}:${column.name}`).join("|");
  useEffect(() => {
    const box = scrollRef.current;
    if (!box || !selectedId) return;
    const cell = box.querySelector<HTMLElement>(`th[data-col="${selectedId}"]`);
    const pinned = box.querySelector<HTMLElement>("thead th")?.offsetWidth ?? 0;
    if (!cell) return;
    const left = cell.offsetLeft - pinned;
    const right = cell.offsetLeft + cell.offsetWidth - box.clientWidth;
    if (box.scrollLeft > left) box.scrollLeft = left;
    else if (box.scrollLeft < right) box.scrollLeft = right;
  }, [selectedId, columnKey]);
  const isEditing = (column: MatrixColumn) => draft !== null && column.id === selectedId;
  const sel = (column: MatrixColumn) => (column.id === selectedId ? "pf-matrix-sel" : undefined);

  return (
    <div className="pf-matrix-scroll" ref={scrollRef}>
      <table className="pf-matrix">
        <caption className="pf-sr-only">{t("admin.roles.caption")}</caption>
        <thead>
          <tr>
            <th scope="col">{t("admin.roles.sectionColumn")}</th>
            {columns.map((column) => (
              <th key={column.id} scope="col" className={sel(column)} data-col={column.id}>
                <button
                  type="button"
                  className="pf-matrix-role pf-focusable"
                  aria-pressed={column.id === selectedId}
                  onClick={() => {
                    onSelect(column.id);
                  }}
                >
                  <span>{column.name}</span>
                  {column.system ? (
                    <span className="pf-matrix-role-sub">
                      <LockIcon size={12} />
                      {t("admin.roles.system")}
                    </span>
                  ) : null}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {MODULES.map((module) => {
            const keys = RESOURCE_KEYS.filter((key) => RESOURCES[key].module === module);
            if (keys.length === 0) return null;
            const config = findModule(module);
            return [
              <tr key={`group:${module}`} className="pf-matrix-group">
                <th scope="colgroup" colSpan={columns.length + 1}>
                  <span className="pf-matrix-group-label">
                    {`${String(config?.order ?? "")}. ${config?.name ?? module}`}
                  </span>
                </th>
              </tr>,
              ...keys.map((key) => {
                const label = sectionLabel(key, i18n.language);
                return (
                  <tr key={key}>
                    <th scope="row">{label}</th>
                    {columns.map((column) => (
                      <td key={column.id} className={sel(column)}>
                        {isEditing(column) && draft ? (
                          <select
                            className="pf-level-select pf-focusable"
                            aria-label={t("admin.roles.cellLabel", {
                              section: label,
                              role: draft.name.trim() || column.name,
                            })}
                            value={draft.access[key] ?? "hidden"}
                            onChange={(event) => {
                              onDraft(
                                setLevel(draft, key, event.target.value as AccessLevel | "hidden"),
                              );
                            }}
                          >
                            {levelOptions(key).map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <LevelMark level={column.access[key]} />
                        )}
                      </td>
                    ))}
                  </tr>
                );
              }),
            ];
          })}
          <tr className="pf-matrix-group">
            <th scope="colgroup" colSpan={columns.length + 1}>
              <span className="pf-matrix-group-label">{t("admin.roles.fieldsGroup")}</span>
            </th>
          </tr>
          {FIELDS.map((field) => {
            const label = fieldLabel(field, i18n.language);
            return (
              <tr key={field}>
                <th scope="row">{label}</th>
                {columns.map((column) => (
                  <td key={column.id} className={sel(column)}>
                    {isEditing(column) && draft ? (
                      <Checkbox
                        aria-label={t("admin.roles.fieldLabel", {
                          field: label,
                          role: draft.name.trim() || column.name,
                        })}
                        checked={draft.restricted_fields.includes(field)}
                        onChange={(event) => {
                          onDraft(toggleField(draft, field, event.target.checked));
                        }}
                      />
                    ) : (
                      <FieldMark on={column.restricted_fields.includes(field)} />
                    )}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
