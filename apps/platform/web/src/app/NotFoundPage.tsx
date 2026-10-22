import { Card } from "antd";
import { useTranslation } from "react-i18next";

import { useDocumentTitle } from "../shared/lib/useDocumentTitle";
import { EmptyState } from "../shared/ui/EmptyState";
import { LinkButton } from "../shared/ui/LinkButton";
import { PageHeader } from "../shared/ui/PageHeader";
import { DEFAULT_HOME } from "./auth/redirect";

/** 404 внутри каркаса: адреса нет в карте маршрутов SPEC-v3 §6.3. */
export function NotFoundPage() {
  const { t } = useTranslation("shell");
  useDocumentTitle(t("notFound.heading"));
  return (
    <>
      <PageHeader title={t("notFound.heading")} />
      <Card>
        <EmptyState
          title={t("notFound.title")}
          text={t("notFound.text")}
          action={<LinkButton to={DEFAULT_HOME}>{t("notFound.back")}</LinkButton>}
        />
      </Card>
    </>
  );
}
