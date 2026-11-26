import { useTranslation } from "react-i18next";

import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { ContractTemplates } from "../../admin/company/tabs/ContractTemplates";
import { PageFrame } from "../../../shared/ui/PageFrame";

import "../../admin/company/company.css";

/**
 * Документы · Шаблоны · Договоры (ДОК-10): тот же список, что вкладка «Договоры» в Настройках, для держателя зоны «Право»
 * (юрист без раздела Настроек): утвердить шаблон, увидеть редакции. Права на действия решает ERP.
 */
export function ContractTemplatesPage() {
  const { t } = useTranslation("company");
  useDocumentTitle(t("contractTemplates.title"));
  return (
    <PageFrame layout="object">
      <div className="pf-co-body">
        <PageHeader title={t("contractTemplates.title")} />
        <ContractTemplates titled={false} />
      </div>
    </PageFrame>
  );
}
