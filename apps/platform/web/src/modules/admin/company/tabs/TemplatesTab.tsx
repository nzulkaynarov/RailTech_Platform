import { Segmented } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { TabHeader } from "../common";
import { DocumentTemplates } from "./DocumentTemplates";
import { EmailTemplates } from "./EmailTemplates";

type Part = "documents" | "emails";

/** Шаблоны документов (ERP `crm/document-templates`) и шаблоны писем (ERP `settings/email-templates`). */
export function TemplatesTab() {
  const { t } = useTranslation("company");
  const [part, setPart] = useState<Part>("documents");
  return (
    <div className="pf-co-body">
      <TabHeader title={t("templates.title")} hint={t("templates.hint")} />
      <Segmented<Part>
        aria-label={t("templates.part")}
        value={part}
        onChange={setPart}
        options={[
          { value: "documents", label: t("templates.parts.documents") },
          { value: "emails", label: t("templates.parts.emails") },
        ]}
      />
      {part === "documents" ? <DocumentTemplates /> : <EmailTemplates />}
    </div>
  );
}
