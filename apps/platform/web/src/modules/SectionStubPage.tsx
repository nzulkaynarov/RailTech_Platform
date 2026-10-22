import { Card } from "antd";
import { useTranslation } from "react-i18next";

import { canSee } from "../app/access";
import { useAuth } from "../app/auth/useAuth";
import { todayLabel } from "../shared/lib/format";
import { useDocumentTitle } from "../shared/lib/useDocumentTitle";
import { EmptyState } from "../shared/ui/EmptyState";
import { LinkButton } from "../shared/ui/LinkButton";
import { PageHeader } from "../shared/ui/PageHeader";
import { SoonButton } from "../shared/ui/SoonButton";
import { matchSection } from "./registry";
import type { ModuleConfig, SectionConfig } from "./types";

/**
 * Страница-заглушка раздела (PLT-12): заголовок, пустое состояние словами SPEC-v3 §7 и одно действие. Экраны с данными
 * заменят её в своих задачах; маршрут, доступ и боковое окно к тому времени уже работают.
 */
export function SectionStubPage({
  module,
  section,
  objectId,
}: {
  module: ModuleConfig;
  section: SectionConfig;
  objectId?: string;
}) {
  const { t, i18n } = useTranslation(["modules", "shell"]);
  const { me } = useAuth();
  const base = `${module.code}.`;
  const label = t(`modules:${base}sections.${section.key}`);
  const title = objectId ? t("shell:stub.object", { id: objectId }) : label;
  useDocumentTitle(title);

  const isQueue = module.code === "dashboard" && section.key === "queue";
  const roles =
    !me.active_role && me.roles.length > 1
      ? [t("shell:avatar.allRoles")]
      : (me.active_role ? [me.active_role] : me.roles).map((r) => t(`shell:roles.${r}`));
  const subtitle = isQueue
    ? [roles.join(", "), todayLabel(i18n.language)].join(" · ")
    : t("shell:stub.subtitle");

  const actionLabel = t(`modules:${base}stub.${section.key}.action`);
  const [targetPath = "", targetSearch = ""] = (section.actionTo ?? "").split("?");
  const target = section.actionTo ? matchSection(targetPath, targetSearch) : undefined;
  // Действие-ссылка показываем, только если раздел-цель доступен роли: иначе человек упёрся бы в «Нет доступа».
  const showLink = target !== undefined && canSee(me, target.section.access);

  return (
    <>
      <PageHeader title={title} subtitle={subtitle} />
      <Card>
        <EmptyState
          title={t(`modules:${base}stub.${section.key}.title`)}
          text={t(`modules:${base}stub.${section.key}.text`)}
          action={
            section.actionTo ? (
              showLink ? (
                <LinkButton to={section.actionTo}>{actionLabel}</LinkButton>
              ) : null
            ) : (
              <SoonButton>{actionLabel}</SoonButton>
            )
          }
        />
      </Card>
    </>
  );
}
