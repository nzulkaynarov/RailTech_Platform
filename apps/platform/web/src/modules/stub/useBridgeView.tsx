import { Skeleton } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { canSee } from "../../app/access";
import { useAuth } from "../../app/auth/useAuth";
import { useGetBridge } from "../../shared/api/generated/platform-bff";
import { LinkButton } from "../../shared/ui/LinkButton";
import { type BridgeEntry, legacyHref } from "../bridge";
import { matchSection } from "../registry";
import { LegacyLink } from "./LegacyLink";

export interface BridgeView {
  /** «Сейчас эта работа делается в старой CRM: раздел «Лиды»…» (страница) или «Сейчас — в старой CRM: раздел «Лиды».» (поповер) */
  intro: string;
  /** Кнопка «Открыть в …» (или ссылка на раздел Платформы); `null` — открывать нечего */
  action: ReactNode;
  /** Пояснение под кнопкой: нужен ли повторный вход, или почему кнопки нет */
  note: string | null;
  /** «Когда появится: …» */
  when: string;
}

/**
 * Где эта работа делается сейчас — одно место для страницы-заглушки, поповера «Где сделать» в «Моих задачах» и
 * «Где посмотреть» в поиске и колокольчике (W15-H1, W15-H2). Карта — `modules/bridge.ts`; адрес старой системы и вход
 * в старый ERP — тот же `LegacyLink`. `short` — короткая фраза для поповера.
 */
export function useBridgeView(
  entry: BridgeEntry,
  objectId: string | undefined,
  variant: "page" | "short" = "page",
): BridgeView {
  const { t } = useTranslation(["bridge", "modules"]);
  const { me } = useAuth();
  const bridge = useGetBridge();
  const intro = variant === "page" ? "intro" : "short";
  const when = t("bridge:when", { when: t(`bridge:whenValue.${entry.when}`) });

  // Старый экран без нужного раздела ничего не покажет (B-D18-1) — тогда честно «кто делает», без кнопки.
  const legacy =
    entry.legacy && (!entry.legacyNeeds || canSee(me, { resource: entry.legacyNeeds }))
      ? entry.legacy
      : undefined;
  if (legacy) {
    const system = legacy.system;
    const where = t(`bridge:where.${legacy.where}`);
    const text = t(`bridge:${intro}.legacy`, { system: t(`bridge:system.${system}.in`), where });
    if (bridge.isPending) {
      return {
        intro: text,
        action: <Skeleton.Button active aria-hidden="true" />,
        note: null,
        when,
      };
    }
    const base = system === "crm" ? bridge.data?.crm_url : bridge.data?.erp_url;
    const href = legacyHref(legacy, base, objectId);
    if (!href) {
      return {
        intro: text,
        action: null,
        note: t("bridge:noAddress", { name: t(`bridge:system.${system}.name`) }),
        when,
      };
    }
    const sso = system === "erp" && bridge.data?.erp_sso === true;
    return {
      intro: text,
      action: <LegacyLink system={system} href={href} sso={sso} />,
      note: sso ? t("bridge:login.erpSso", { where }) : t(`bridge:login.${system}`),
      when,
    };
  }

  if (entry.internal) {
    const target = matchSection(entry.internal.to);
    const name = t(`modules:${target?.module.code ?? "admin"}.sections.${entry.internal.section}`);
    const open = target !== undefined && canSee(me, target.section.access);
    return {
      intro: t(`bridge:${intro}.internal`, { section: name }),
      action: open ? (
        <LinkButton to={entry.internal.to}>
          {t("bridge:internalOpen", { section: name })}
        </LinkButton>
      ) : null,
      note: null,
      when,
    };
  }

  return {
    intro: t(`bridge:${intro}.none`, { who: t(`bridge:who.${entry.who ?? "unknown"}`) }),
    action: null,
    note: null,
    when,
  };
}
