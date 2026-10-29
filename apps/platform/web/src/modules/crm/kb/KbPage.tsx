import { Segmented } from "antd";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router";

import { canEdit } from "../../../app/access";
import { useAuth } from "../../../app/auth/useAuth";
import { PanelPortal } from "../../../app/shell/PanelSlot";
import { useDocumentTitle } from "../../../shared/lib/useDocumentTitle";
import { LinkButton } from "../../../shared/ui/LinkButton";
import { LockIcon } from "../../../shared/ui/icons";
import { PageHeader } from "../../../shared/ui/PageHeader";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { CreateDocumentPanel } from "./CreateDocumentPanel";
import { DocumentPanel } from "./DocumentPanel";
import { DocumentsView } from "./DocumentsView";
import { GapPanel } from "./GapPanel";
import { GapsView } from "./GapsView";
import { parseId, withParams } from "./refresh";
import { SandboxView } from "./SandboxView";

import "./kb.css";

const VIEWS = ["docs", "gaps", "sandbox"] as const;
type View = (typeof VIEWS)[number];

function viewOf(value: string | null, editable: boolean): View {
  const found = VIEWS.find((v) => v === value);
  if (found === undefined || (found === "sandbox" && !editable)) return "docs";
  return found;
}

/**
 * CRM · База знаний (SPEC-v3 §7.2): документы бота с поиском «Что найдёт бот», пробелы базы знаний и песочница. Читают роли с
 * `crm.leads` и `admin`; загружает, переиндексирует, закрывает пробелы и проверяет бота администратор (`admin` — полный).
 * Вкладка экрана — `?view=docs|gaps|sandbox`; карточка документа или пробела и формы создания — в боковом окне.
 */
export function KbPage() {
  const { t } = useTranslation(["kb", "modules"]);
  const { me } = useAuth();
  const editable = canEdit(me, "admin");
  const [params, setParams] = useSearchParams();
  const view = viewOf(params.get("viewTab") ?? params.get("view"), editable);
  const title = t("modules:crm.sections.kb");
  useDocumentTitle(title);

  const docId = parseId(params.get("doc"));
  const gapId = parseId(params.get("gap"));
  const creating = params.get("new");
  const kind = creating === "upload" || creating === "manual" ? creating : null;

  let panel;
  if (view === "docs" && editable && kind)
    panel = <CreateDocumentPanel key={kind} kind={kind} draft={null} />;
  else if (view === "docs" && docId !== null)
    panel = <DocumentPanel key={docId} id={docId} editable={editable} />;
  else if (view === "gaps" && gapId !== null)
    panel = <GapPanel key={gapId} id={gapId} editable={editable} />;

  return (
    <div className="pf-kb">
      <PageHeader
        title={title}
        subtitle={t(editable ? "kb:subtitle" : "kb:readOnlySubtitle")}
        extra={
          editable && view === "docs" ? (
            <div className="pf-fp-row">
              <LinkButton
                type="primary"
                to={withParams(params, { new: "upload", doc: null, panel: "open" })}
              >
                {t("kb:documents.upload")}
              </LinkButton>
              <LinkButton to={withParams(params, { new: "manual", doc: null, panel: "open" })}>
                {t("kb:documents.manual")}
              </LinkButton>
            </div>
          ) : editable ? null : (
            <StatusTag tone="default">
              <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                <LockIcon size={12} />
                {t("kb:viewOnly")}
              </span>
            </StatusTag>
          )
        }
      />
      <Segmented
        aria-label={t("kb:views.label")}
        value={view}
        options={VIEWS.filter((v) => editable || v !== "sandbox").map((value) => ({
          value,
          label: t(`kb:views.${value}`),
        }))}
        onChange={(value) => {
          setParams(
            (prev) => {
              const next = new URLSearchParams(prev);
              next.set("view", value);
              next.set("viewTab", value);
              for (const key of ["doc", "gap", "new", "page", "status"]) next.delete(key);
              return next;
            },
            { replace: true },
          );
        }}
      />
      {view === "docs" ? <DocumentsView editable={editable} /> : null}
      {view === "gaps" ? <GapsView /> : null}
      {view === "sandbox" ? <SandboxView /> : null}
      {panel ? <PanelPortal tab="card">{panel}</PanelPortal> : null}
    </div>
  );
}
