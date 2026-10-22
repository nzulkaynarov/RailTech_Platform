import { Card } from "antd";
import { useTranslation } from "react-i18next";

import { useDocumentTitle } from "../lib/useDocumentTitle";
import { EmptyState } from "./EmptyState";
import { PageHeader } from "./PageHeader";
import { SoonButton } from "./SoonButton";

export interface ForbiddenProps {
  /** Названия ролей, которым раздел доступен («Раздел доступен ролям …»); без списка — общий текст */
  roles?: readonly string[];
  /** У сотрудника выбрана активная роль: раздел может быть доступен другой его роли («Все роли» в меню профиля) */
  activeRole?: boolean;
}

/**
 * 403 по прямому URL (SPEC-v3 §11.2 п. 7): раздел не положен ролям сотрудника. Предложение написать
 * администратору — тикет Admin появится вместе с «Тикеты от команды», до тех пор кнопка неактивна с подсказкой.
 */
export function Forbidden({ roles, activeRole = false }: ForbiddenProps) {
  const { t } = useTranslation("shell");
  useDocumentTitle(t("forbidden.heading"));
  const text = activeRole
    ? t("forbidden.textActiveRole")
    : roles && roles.length > 0
      ? t("forbidden.textRoles", { roles: roles.join(", ") })
      : t("forbidden.text");
  return (
    <>
      <PageHeader title={t("forbidden.heading")} />
      <Card style={{ marginTop: 16 }}>
        <EmptyState
          title={activeRole ? t("forbidden.titleActiveRole") : t("forbidden.title")}
          text={text}
          action={<SoonButton>{t("forbidden.write")}</SoonButton>}
        />
      </Card>
    </>
  );
}
