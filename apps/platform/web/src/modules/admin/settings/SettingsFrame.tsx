import { Select } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { USER_SCOPE, panelsKey, usePanelsStore } from "../../../app/shell/panelsStore";
import { useViewport } from "../../../app/shell/useViewport";
import { FormField } from "../../../shared/ui/FormParts";
import { SETTINGS_HOME } from "../module";
import { SETTINGS, SETTINGS_GROUPS, entryAt } from "../settingsRegistry";

import "./settings.css";

/**
 * Рамка страницы Настроек (НАСТ-1, макеты 54 и 55; ЕВ-2а, polish 2026-11-24 п. 16 — одно меню): все страницы Настроек стоят в меню
 * модуля (`AppShell`) сразу, по группам, рамка меню не рисует. Пока меню не видно (телефон, свёрнутое меню на 768–1439 px),
 * над страницей остаётся один выпадающий список с теми же группами и пунктами и поиском. «Состояние» (`/admin`) и страницы
 * группы — в нём же. Скрытые страницы без пункта (мастер, обращение) стоят без выбора. Страница под выбором не пересоздаётся.
 */
export function SettingsFrame({ children }: { children: ReactNode }) {
  const { t } = useTranslation("modules");
  const { me } = useAuth();
  const { mobile, menuWide } = useViewport();
  // Меню модуля свёрнуто (по умолчанию так на 768–1439 px) — страницы не видны, нужен выбор здесь.
  const menuOpen =
    usePanelsStore((state) => state.entries[panelsKey(me.id, USER_SCOPE)]?.menuOpen) ?? menuWide;
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const current = entryAt(pathname);
  const onState = pathname.replace(/\/+$/, "") === SETTINGS_HOME;
  if (!current && !onState) return <>{children}</>;
  const showPicker = mobile || !menuOpen;
  const visible = SETTINGS.filter((entry) => canSee(me, entry.access));
  const stateLabel = t("admin.nav.state");
  const options = [
    { value: SETTINGS_HOME, label: stateLabel },
    ...SETTINGS_GROUPS.map((group) => ({
      label: t(`admin.groups.${group}`),
      title: t(`admin.groups.${group}`),
      options: visible
        .filter((entry) => entry.group === group)
        .map((entry) => ({ value: entry.path, label: t(`admin.sections.${entry.key}`) })),
    })).filter((group) => group.options.length > 0),
  ];
  return (
    <div className="pf-set-frame" style={{ gridTemplateColumns: "minmax(0, 1fr)" }}>
      {showPicker ? (
        <FormField id="pf-set-frame-nav" label={t("admin.frame.nav")}>
          <Select
            id="pf-set-frame-nav"
            showSearch
            virtual={false}
            optionFilterProp="label"
            value={current?.path ?? SETTINGS_HOME}
            options={options}
            onChange={(path: string) => {
              void navigate(path);
            }}
          />
        </FormField>
      ) : null}
      <div className="pf-set-frame-body">{children}</div>
    </div>
  );
}
