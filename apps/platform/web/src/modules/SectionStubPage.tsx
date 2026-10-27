import { Card, Skeleton, theme } from "antd";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";

import { canSee } from "../app/access";
import { useAuth } from "../app/auth/useAuth";
import { viewRoleNames } from "../entities/role/roles";
import { useGetBridge, useGetQueue } from "../shared/api/generated/platform-bff";
import type { ObjectKind, QueueItem } from "../shared/api/generated/model";
import { todayLabel } from "../shared/lib/format";
import { useDocumentTitle } from "../shared/lib/useDocumentTitle";
import { useFormat } from "../shared/lib/useFormat";
import { DefinitionList } from "../shared/ui/DefinitionList";
import { EmptyState } from "../shared/ui/EmptyState";
import { LinkButton } from "../shared/ui/LinkButton";
import { PageHeader } from "../shared/ui/PageHeader";
import { type BridgeEntry, bridgeEntry, legacyHref, objectIdOf, objectTitle } from "./bridge";
import { dueBadge } from "./dashboard/queue";
import { matchSection } from "./registry";
import { LegacyLink } from "./stub/LegacyLink";
import type { ModuleConfig, SectionConfig } from "./types";

/** Раздел без записи в мосте: честный запасной текст (тест `bridge.test.ts` не пускает такие разделы в сборку). */
const UNKNOWN: BridgeEntry = { who: "unknown", when: "pilot" };

/** Что «Моя очередь» знает об объекте по его номеру из адреса: первая строка, чей объект — этот номер. */
function queueItemFor(items: readonly QueueItem[] | undefined, objectId: string) {
  return items?.find((item) => item.object.number === objectId);
}

/**
 * Страница-заглушка раздела, который ещё переносится в Платформу (W15-H1, UX-оценка P0-2). Не врёт «пока нет»: говорит,
 * где эта работа делается сейчас (кнопка «Открыть в старой CRM / ERP» в новую вкладку) или кто её делает вне
 * интерфейса, и когда раздел появится — словами. Карточка объекта по прямой ссылке (`/eds/inbox/ВХ-104%2F26`) показывает
 * то, что о нём знает «Моя очередь» (без новых обращений к бэкендам). Куда ведёт мост — `modules/bridge.ts`.
 */
export function SectionStubPage({
  module,
  section,
  objectId: routeObjectId,
}: {
  module: ModuleConfig;
  section: SectionConfig;
  objectId?: string;
}) {
  const { t, i18n } = useTranslation(["bridge", "modules", "shell"]);
  const { token } = theme.useToken();
  const { me } = useAuth();
  const format = useFormat();
  const location = useLocation();

  const entry = bridgeEntry(module.code, section.key) ?? UNKNOWN;
  const objectId = objectIdOf({ objectId: routeObjectId }, location.search);
  const sectionLabel = t(`modules:${module.code}.sections.${section.key}`);

  // Очередь уже загружена «Моей очередью» (тот же ключ запроса); для карточки объекта других вызовов не нужно.
  const role = me.active_role ?? undefined;
  const queue = useGetQueue(role ? { role } : undefined, {
    query: {
      enabled: objectId !== undefined && canSee(me, { resource: "dashboard.queue" }),
    },
  });
  const item = objectId !== undefined ? queueItemFor(queue.data?.items, objectId) : undefined;

  const bridge = useGetBridge();

  const kind: ObjectKind | undefined = item?.object.kind ?? entry.objectKind;
  const kindLabel = kind ? t(`shell:search.kind.${kind}`) : undefined;
  const title = objectId !== undefined ? objectTitle(kindLabel, objectId) : sectionLabel;
  useDocumentTitle(title);

  const isQueue = module.code === "dashboard" && section.key === "queue";
  const roles = viewRoleNames(me, t("shell:avatar.allRoles"));
  const subtitle = isQueue
    ? [roles, todayLabel(i18n.language)].join(" · ")
    : objectId !== undefined
      ? sectionLabel
      : t("shell:stub.subtitle");

  const legacy = entry.legacy;
  let intro: string;
  let action: ReactNode = null;
  let note: string | null = null;

  if (legacy) {
    const system = legacy.system;
    intro = t("bridge:intro.legacy", {
      system: t(`bridge:system.${system}.in`),
      where: t(`bridge:where.${legacy.where}`),
    });
    if (bridge.isPending) {
      action = <Skeleton.Button active aria-hidden="true" />;
    } else {
      const base = system === "crm" ? bridge.data?.crm_url : bridge.data?.erp_url;
      const href = legacyHref(legacy, base, objectId);
      if (href) {
        const sso = system === "erp" && bridge.data?.erp_sso === true;
        action = <LegacyLink system={system} href={href} sso={sso} />;
        note =
          system === "erp" && sso
            ? t("bridge:login.erpSso", { where: t(`bridge:where.${legacy.where}`) })
            : t(`bridge:login.${system}`);
      } else {
        note = t("bridge:noAddress", { name: t(`bridge:system.${system}.name`) });
      }
    }
  } else if (entry.internal) {
    const target = matchSection(entry.internal.to);
    const name = t(`modules:${target?.module.code ?? "admin"}.sections.${entry.internal.section}`);
    intro = t("bridge:intro.internal", { section: name });
    if (target && canSee(me, target.section.access)) {
      action = (
        <LinkButton to={entry.internal.to}>
          {t("bridge:internalOpen", { section: name })}
        </LinkButton>
      );
    }
  } else {
    intro = t("bridge:intro.none", { who: t(`bridge:who.${entry.who ?? "unknown"}`) });
  }

  const known = item
    ? [
        { label: t("bridge:object.task"), value: item.title },
        { label: t("bridge:object.details"), value: item.subtitle },
        {
          label: t("bridge:object.due"),
          value: dueBadge(
            item,
            (key, options) => t(key, options),
            (value) => format.date(value, "short"),
          ).label,
        },
      ]
    : null;

  return (
    <>
      <PageHeader title={title} subtitle={subtitle} />
      {known ? (
        <Card>
          <section aria-labelledby="pf-stub-known">
            <h2
              id="pf-stub-known"
              style={{ margin: "0 0 12px", fontSize: 16, lineHeight: "24px", fontWeight: 600 }}
            >
              {t("bridge:objectKnown")}
            </h2>
            <DefinitionList items={known} />
          </section>
        </Card>
      ) : null}
      <Card>
        <EmptyState
          title={t("bridge:title")}
          text={intro}
          action={
            <>
              {action}
              {note ? (
                <p style={{ margin: "8px 0 0", color: token.colorTextSecondary }}>{note}</p>
              ) : null}
              <p style={{ margin: "8px 0 0", color: token.colorTextSecondary }}>
                {t("bridge:when", { when: t(`bridge:whenValue.${entry.when}`) })}
              </p>
            </>
          }
        />
      </Card>
    </>
  );
}
