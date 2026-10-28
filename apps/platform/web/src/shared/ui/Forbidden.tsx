import { Button, Card } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { WriteToAdminModal } from "../../features/tickets/WriteToAdminModal";
import { useDocumentTitle } from "../lib/useDocumentTitle";
import { EmptyState } from "./EmptyState";
import { PageHeader } from "./PageHeader";

export interface ForbiddenProps {
  /** Названия ролей, которым раздел доступен («Раздел доступен ролям …»); без списка — общий текст */
  roles?: readonly string[];
  /** У сотрудника выбрана активная роль: раздел может быть доступен другой его роли («Все роли» в меню профиля) */
  activeRole?: boolean;
  /** Блок внутри другой страницы (витрина, боковое окно): без заголовка страницы `h1` и без смены заголовка вкладки */
  embedded?: boolean;
}

/**
 * 403 по прямому URL (SPEC-v3 §11.2 п. 7): раздел не положен ролям сотрудника. «Написать администратору» (W15-H7)
 * открывает обращение с темой «Нужен доступ к разделу»; страница и роль прикладываются сами, обращение видно в
 * «Настройки · Обращения сотрудников». Окно монтируется при первом нажатии: блок бывает и во витрине без сессии.
 */
export function Forbidden({ roles, activeRole = false, embedded = false }: ForbiddenProps) {
  const { t } = useTranslation("shell");
  const [writing, setWriting] = useState(false);
  useDocumentTitle(embedded ? undefined : t("forbidden.heading"));
  const text = activeRole
    ? t("forbidden.textActiveRole")
    : roles && roles.length > 0
      ? t("forbidden.textRoles", { roles: roles.join(", ") })
      : t("forbidden.text");
  return (
    <>
      {embedded ? null : <PageHeader title={t("forbidden.heading")} />}
      <Card style={{ marginTop: embedded ? 0 : 16 }}>
        <EmptyState
          title={activeRole ? t("forbidden.titleActiveRole") : t("forbidden.title")}
          text={text}
          level={embedded ? 3 : 2}
          action={
            <Button
              type="primary"
              onClick={() => {
                setWriting(true);
              }}
            >
              {t("forbidden.write")}
            </Button>
          }
        />
      </Card>
      {writing ? (
        <WriteToAdminModal
          open
          defaultSubject="access"
          onClose={() => {
            setWriting(false);
          }}
        />
      ) : null}
    </>
  );
}
