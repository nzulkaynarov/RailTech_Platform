import { Select } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { useViewport } from "../../../app/shell/useViewport";
import { FormField } from "../../../shared/ui/FormParts";
import { SETTINGS, entryAt } from "../settingsRegistry";

import "./settings.css";

/**
 * Рамка страницы Настроек (ЕВ-2а, отчёт 2026-11-22 §7 п. 20; polish 2026-11-24 п. 16 — одно меню): страницы своей группы стоят
 * в подменю модуля под активной группой (`AppShell`), рамка меню не рисует. На телефоне подменю — в ящике, поэтому над
 * страницей остаётся выпадающий список. Страницы группы, которых сотруднику не видно, в меню нет; одна страница — меню нет.
 * «Состояние» (`/admin`) и скрытые страницы без группы стоят без меню.
 */
export function SettingsFrame({ children }: { children: ReactNode }) {
  const { t } = useTranslation("modules");
  const { me } = useAuth();
  const { mobile } = useViewport();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const current = entryAt(pathname);
  const entries = current
    ? SETTINGS.filter((entry) => entry.group === current.group && canSee(me, entry.access))
    : [];
  if (!current || entries.length < 2) return <>{children}</>;
  const label = t("admin.frame.nav", { group: t(`admin.groups.${current.group}`) });
  // На рабочем столе страницы группы — в меню модуля под активной группой (одно меню, не два); здесь только телефон.
  if (!mobile) return <>{children}</>;
  return (
    <div className="pf-set-frame">
      <FormField id="pf-set-frame-nav" label={label}>
        <Select
          id="pf-set-frame-nav"
          value={current.key}
          options={entries.map((entry) => ({
            value: entry.key,
            label: t(`admin.sections.${entry.key}`),
          }))}
          onChange={(key: string) => {
            const next = entries.find((entry) => entry.key === key);
            if (next) void navigate(next.path);
          }}
        />
      </FormField>
      <div className="pf-set-frame-body">{children}</div>
    </div>
  );
}
