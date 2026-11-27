import { Button, Card } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { AccessRule } from "../../modules/types";
import { findMissing } from "../../features/capabilities/model";
import { WriteToAdminModal } from "../../features/tickets/WriteToAdminModal";
import { useGetMyCapabilities } from "../api/generated/platform-bff";
import { pickText } from "../../features/capabilities/model";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { EmptyState } from "./EmptyState";
import { PageHeader } from "./PageHeader";

export interface ForbiddenProps {
  /** Названия ролей, которым раздел доступен («Раздел доступен ролям …»); без списка — общий текст */
  roles?: readonly string[];
  /** Блок внутри другой страницы (витрина, боковое окно): без заголовка страницы `h1` и без смены заголовка вкладки */
  embedded?: boolean;
  /** Правило закрытого раздела: по нему экран называет недостающую возможность (ДОСТ-1); без правила — общий текст */
  rule?: AccessRule;
}

/**
 * 403 по прямому URL (SPEC-v3 §11.2 п. 7): раздел не положен ролям сотрудника. «Написать администратору» (W15-H7)
 * открывает обращение с темой «Нужен доступ к разделу»; страница и роль прикладываются сами, обращение видно в
 * «Настройки · Обращения сотрудников». Окно монтируется при первом нажатии: блок бывает и во витрине без сессии.
 */
export function Forbidden({ roles, embedded = false, rule }: ForbiddenProps) {
  const { t, i18n } = useTranslation(["shell", "capabilities"]);
  const [writing, setWriting] = useState(false);
  // «Мои возможности» читаются только когда известно, какой раздел закрыт; не пришли — общий текст, а не ошибка.
  const mine = useGetMyCapabilities({ query: { enabled: rule !== undefined, retry: false } });
  const missing =
    rule && mine.data
      ? findMissing(
          mine.data,
          "resource" in rule ? [rule.resource] : rule.anyOf,
          rule.level ?? "read",
        )
      : null;
  const name = missing ? pickText(missing.name, i18n.language) : "";
  const level = missing ? t(`capabilities:levelVerb.${missing.needed}`) : "";
  useDocumentTitle(embedded ? undefined : t("forbidden.heading"));
  const grantors = mine.data?.grantors;
  const who =
    grantors === undefined
      ? t("capabilities:denied.who")
      : grantors.length === 0
        ? t("capabilities:denied.nobody")
        : t("capabilities:denied.grantors", { names: grantors.map((p) => p.name).join(", ") });
  const text = missing
    ? `${t("capabilities:denied.need", { name, level, current: t(`capabilities:level.${missing.current}`) })} ${who}`
    : roles && roles.length > 0
      ? t("forbidden.textRoles", { roles: roles.join(", ") })
      : t("forbidden.text");
  return (
    <>
      {embedded ? null : <PageHeader title={t("forbidden.heading")} />}
      <Card style={{ marginTop: embedded ? 0 : 16 }}>
        <EmptyState
          title={missing ? t("capabilities:denied.title", { name }) : t("forbidden.title")}
          text={text}
          level={embedded ? 3 : 2}
          action={
            <Button
              type="primary"
              onClick={() => {
                setWriting(true);
              }}
            >
              {missing ? t("capabilities:denied.ask") : t("forbidden.write")}
            </Button>
          }
        />
      </Card>
      {writing ? (
        <WriteToAdminModal
          open
          defaultSubject="access"
          {...(missing ? { defaultBody: t("capabilities:denied.askBody", { name, level }) } : {})}
          onClose={() => {
            setWriting(false);
          }}
        />
      ) : null}
    </>
  );
}
