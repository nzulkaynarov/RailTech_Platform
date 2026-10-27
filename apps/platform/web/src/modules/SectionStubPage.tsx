import { Card, theme } from "antd";
import { useTranslation } from "react-i18next";
import { useLocation } from "react-router";

import { canSee } from "../app/access";
import { useAuth } from "../app/auth/useAuth";
import { viewRoleNames } from "../entities/role/roles";
import { useGetQueue } from "../shared/api/generated/platform-bff";
import type { ObjectKind, QueueItem } from "../shared/api/generated/model";
import { todayLabel } from "../shared/lib/format";
import { useDocumentTitle } from "../shared/lib/useDocumentTitle";
import { useFormat } from "../shared/lib/useFormat";
import { DefinitionList } from "../shared/ui/DefinitionList";
import { EmptyState } from "../shared/ui/EmptyState";
import { PageHeader } from "../shared/ui/PageHeader";
import { type BridgeEntry, bridgeEntry, objectIdOf, objectTitle } from "./bridge";
import { dueBadge } from "./dashboard/queue";
import { useBridgeView } from "./stub/useBridgeView";
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

  const view = useBridgeView(entry, objectId);

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
          text={view.intro}
          action={
            <>
              {view.action}
              {view.note ? (
                <p style={{ margin: "8px 0 0", color: token.colorTextSecondary }}>{view.note}</p>
              ) : null}
              <p style={{ margin: "8px 0 0", color: token.colorTextSecondary }}>{view.when}</p>
            </>
          }
        />
      </Card>
    </>
  );
}
