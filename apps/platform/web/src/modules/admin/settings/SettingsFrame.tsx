import { Select } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useLocation, useNavigate } from "react-router";

import { canSee } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { USER_SCOPE, panelsKey, usePanelsStore } from "../../../app/shell/panelsStore";
import { useViewport } from "../../../app/shell/useViewport";
import { FormField } from "../../../shared/ui/FormParts";
import { SETTINGS, entryAt } from "../settingsRegistry";

import "./settings.css";

/**
 * Рамка страницы Настроек (ЕВ-2а, отчёт 2026-11-22 §7 п. 20; polish 2026-11-24 п. 16 — одно меню): страницы своей группы стоят
 * в подменю модуля под активной группой (`AppShell`), рамка меню не рисует. Пока меню не видно (телефон, свёрнутое меню
 * на 768–1439 px), над страницей остаётся выпадающий список. Страницы группы, которых сотруднику не видно, в меню нет; одна страница — меню нет.
 * «Состояние» (`/admin`) и скрытые страницы без группы стоят без меню.
 */
export function SettingsFrame({ children }: { children: ReactNode }) {
  const { t } = useTranslation("modules");
  const { me } = useAuth();
  const { mobile, menuWide } = useViewport();
  // Меню модуля свёрнуто (по умолчанию так на 768–1439 px) — страницы группы не видны, нужен выбор здесь.
  const menuOpen =
    usePanelsStore((state) => state.entries[panelsKey(me.id, USER_SCOPE)]?.menuOpen) ?? menuWide;
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const current = entryAt(pathname);
  const entries = current
    ? SETTINGS.filter((entry) => entry.group === current.group && canSee(me, entry.access))
    : [];
  if (!current || entries.length < 2) return <>{children}</>;
  const label = t("admin.frame.nav", { group: t(`admin.groups.${current.group}`) });
  // Страницы группы — в меню модуля под активной группой (одно меню, не два); выбор над страницей — только когда
  // меню не видно: телефон или свёрнутое меню на ноутбуке.
  // Одно и то же дерево при любой ширине: меняется только выбор страницы, страница под ним не пересоздаётся (форма не теряет ввод).
  const showPicker = mobile || !menuOpen;
  return (
    <div className="pf-set-frame" style={{ gridTemplateColumns: "minmax(0, 1fr)" }}>
      {showPicker ? (
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
      ) : null}
      <div className="pf-set-frame-body">{children}</div>
    </div>
  );
}
