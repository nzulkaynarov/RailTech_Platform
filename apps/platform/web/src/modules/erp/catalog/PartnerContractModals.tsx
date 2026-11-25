import { Alert, Input, Segmented, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { PartnerApplicationItem } from "../../../shared/api/generated/model";
import {
  useDecidePartnerContract,
  useGetPartnerContractOptions,
  usePreparePartnerContract,
  useUploadPartnerContractFile,
} from "../../../shared/api/generated/platform-bff";
import { DateField } from "../../../shared/ui/DateField";
import { FileField } from "../../../shared/ui/FileField";
import { FormField } from "../../../shared/ui/FormParts";
import { FormPanel } from "./common";

const CONTRACT_MAX_BYTES = 20 * 1024 * 1024;
const CONTRACT_ACCEPT = ".pdf,.docx";
const LANGUAGES = ["ru", "en", "uz"] as const;
type Language = (typeof LANGUAGES)[number];
type Mode = "template" | "file";

/** Путь к библиотеке шаблонов договоров: там партнёрский шаблон готовят и утверждают. */
export const TEMPLATE_LIBRARY_PATH = "/eds/contract-templates";

/**
 * «Подготовить договор» (ПД-1): утверждённый партнёрский шаблон библиотеки на языке договора либо свой файл.
 * Нет ни шаблона, ни файла — подготовка не идёт, и словами сказано, чего не хватает; встроенного образца нет.
 * Шаблон без отступлений готов к отправке; файл или текст отступления уходят на решение держателя «Право».
 */
export function PrepareContractModal({
  item,
  onDone,
  onClose,
}: {
  item: PartnerApplicationItem;
  onDone: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation("catalog");
  const options = useGetPartnerContractOptions();
  const data = options.data;
  // Панель открывается, когда шаблоны получены: иначе она перерисовывалась бы на полпути
  if (!data) {
    if (!options.error) return null;
    return (
      <FormPanel
        title={t("partnerApplications.prepareModal.title", { name: item.company_name })}
        okLabel={t("partnerApplications.prepareModal.ok")}
        loading={false}
        error={options.error}
        disabled
        onOk={() => undefined}
        onCancel={onClose}
      >
        <p className="pf-hint">{t("partnerApplications.prepareModal.loading")}</p>
      </FormPanel>
    );
  }
  return (
    <PrepareForm
      item={item}
      templates={data.templates}
      defaultTemplateId={data.default_template_id}
      approvers={data.approvers}
      deviationsAllowed={data.deviations_allowed}
      onDone={onDone}
      onClose={onClose}
    />
  );
}

function PrepareForm({
  item,
  templates,
  defaultTemplateId,
  approvers,
  deviationsAllowed,
  onDone,
  onClose,
}: {
  item: PartnerApplicationItem;
  templates: { id: string; name: string; edition: number; languages: Language[] }[];
  defaultTemplateId: string | null;
  approvers: string[];
  deviationsAllowed: boolean;
  onDone: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation("catalog");
  const ids = { template: useId(), language: useId(), file: useId(), deviation: useId() };
  const numId = useId();
  const dateId = useId();
  const hasTemplates = templates.length > 0;
  const [mode, setMode] = useState<Mode>(hasTemplates ? "template" : "file");
  const [templateId, setTemplateId] = useState<string | undefined>(
    defaultTemplateId ?? (templates.length === 1 ? templates[0]?.id : undefined),
  );
  const chosen = templates.find((tpl) => tpl.id === templateId);
  const [language, setLanguage] = useState<Language>(item.language);
  const [file, setFile] = useState<File | null>(null);
  const [deviation, setDeviation] = useState("");
  const [number, setNumber] = useState(item.contract_number);
  const [date, setDate] = useState(item.contract_date ?? "");
  const languages: readonly Language[] =
    mode === "template" && chosen ? chosen.languages : LANGUAGES;
  const shownLanguage = languages.includes(language) ? language : "ru";

  const prepare = usePreparePartnerContract({ mutation: { onSuccess: onDone } });
  const upload = useUploadPartnerContractFile({ mutation: { onSuccess: onDone } });
  const pending = prepare.isPending || upload.isPending;
  const error = prepare.error ?? upload.error;
  const extra = {
    ...(number.trim() ? { contract_number: number.trim() } : {}),
    ...(date ? { contract_date: date } : {}),
  };
  const needsApproval = mode === "file" || deviation.trim() !== "";

  return (
    <FormPanel
      title={t("partnerApplications.prepareModal.title", { name: item.company_name })}
      okLabel={t("partnerApplications.prepareModal.ok")}
      loading={pending}
      error={error}
      disabled={mode === "template" ? !templateId : file === null}
      onOk={() => {
        if (mode === "template" && templateId) {
          prepare.mutate({
            id: item.id,
            data: {
              template_id: templateId,
              language: shownLanguage,
              ...(deviation.trim() ? { deviation_text: deviation.trim() } : {}),
              ...extra,
            },
          });
        } else if (file) {
          upload.mutate({
            id: item.id,
            data: {
              file,
              language: shownLanguage,
              ...(deviation.trim() ? { deviation_text: deviation.trim() } : {}),
              ...extra,
            },
          });
        }
      }}
      onCancel={onClose}
    >
      {hasTemplates ? null : (
        <Alert
          type="warning"
          showIcon
          role="status"
          message={t("partnerApplications.prepareModal.noTemplate")}
          description={
            <Link to={TEMPLATE_LIBRARY_PATH}>
              {t("partnerApplications.prepareModal.openLibrary")}
            </Link>
          }
        />
      )}
      {hasTemplates ? (
        <Segmented
          block
          aria-label={t("partnerApplications.prepareModal.mode")}
          value={mode}
          options={[
            { value: "template", label: t("partnerApplications.prepareModal.fromTemplate") },
            { value: "file", label: t("partnerApplications.prepareModal.ownFile") },
          ]}
          onChange={(value) => {
            setMode(value as Mode);
          }}
        />
      ) : null}

      {mode === "template" ? (
        <FormField id={ids.template} label={t("partnerApplications.prepareModal.template")}>
          <Select
            id={ids.template}
            value={templateId}
            placeholder={t("partnerApplications.prepareModal.templatePlaceholder")}
            options={templates.map((tpl) => ({
              value: tpl.id,
              label: t("partnerApplications.prepareModal.templateOption", {
                name: tpl.name,
                edition: tpl.edition,
              }),
            }))}
            onChange={(value) => {
              setTemplateId(value);
            }}
          />
        </FormField>
      ) : (
        <FormField
          id={ids.file}
          label={t("partnerApplications.prepareModal.file")}
          hint={t("partnerApplications.prepareModal.fileHint")}
        >
          <FileField
            id={ids.file}
            value={file ? [file] : []}
            accept={CONTRACT_ACCEPT}
            maxSize={CONTRACT_MAX_BYTES}
            aria-describedby={`${ids.file}-hint`}
            onChange={(files) => {
              setFile(files[0] ?? null);
            }}
          />
        </FormField>
      )}

      <FormField id={ids.language} label={t("partnerApplications.prepareModal.language")}>
        <Select
          id={ids.language}
          value={shownLanguage}
          options={languages.map((code) => ({
            value: code,
            label: t(`partnerApplications.prepareModal.languages.${code}`),
          }))}
          onChange={(value) => {
            setLanguage(value);
          }}
        />
      </FormField>

      <FormField id={numId} label={t("partnerApplications.contractNumber")}>
        <Input
          id={numId}
          value={number}
          maxLength={64}
          placeholder={t("partnerApplications.contractNumberPlaceholder")}
          onChange={(event) => {
            setNumber(event.target.value);
          }}
        />
      </FormField>
      <FormField id={dateId} label={t("partnerApplications.contractDate")}>
        <DateField id={dateId} value={date} onChange={setDate} />
      </FormField>

      {deviationsAllowed ? (
        <FormField
          id={ids.deviation}
          label={t("partnerApplications.prepareModal.deviation")}
          hint={t("partnerApplications.prepareModal.deviationHint")}
        >
          <Input.TextArea
            id={ids.deviation}
            rows={3}
            value={deviation}
            maxLength={4000}
            aria-describedby={`${ids.deviation}-hint`}
            onChange={(event) => {
              setDeviation(event.target.value);
            }}
          />
        </FormField>
      ) : null}

      <p className="pf-hint" role="note">
        {needsApproval
          ? t("partnerApplications.prepareModal.needsApproval", {
              who:
                approvers.length > 0 ? approvers.join(", ") : t("partnerApplications.noApprovers"),
            })
          : t("partnerApplications.prepareModal.readyToSend")}
      </p>
    </FormPanel>
  );
}

/** Решение держателя зоны «Право» по своему файлу или отступлению: согласовать или вернуть с замечанием. */
export function ContractDecisionModal({
  item,
  onDone,
  onClose,
}: {
  item: PartnerApplicationItem;
  onDone: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation("catalog");
  const noteId = useId();
  const [decision, setDecision] = useState<"approve" | "return">("approve");
  const [note, setNote] = useState("");
  const mutation = useDecidePartnerContract({ mutation: { onSuccess: onDone } });
  return (
    <FormPanel
      title={t("partnerApplications.decisionModal.title", { name: item.company_name })}
      okLabel={t(`partnerApplications.decisionModal.ok.${decision}`)}
      loading={mutation.isPending}
      error={mutation.error}
      disabled={decision === "return" && note.trim() === ""}
      onOk={() => {
        mutation.mutate({
          id: item.id,
          data: { decision, ...(note.trim() ? { note: note.trim() } : {}) },
        });
      }}
      onCancel={onClose}
    >
      <p>
        {item.contract_source === "upload"
          ? t("partnerApplications.decisionModal.hintFile")
          : t("partnerApplications.decisionModal.hintDeviation")}
      </p>
      {item.contract_deviation_text ? (
        <blockquote className="pf-hint">{item.contract_deviation_text}</blockquote>
      ) : null}
      <Segmented
        block
        aria-label={t("partnerApplications.decisionModal.decision")}
        value={decision}
        options={[
          { value: "approve", label: t("partnerApplications.decisionModal.approve") },
          { value: "return", label: t("partnerApplications.decisionModal.return") },
        ]}
        onChange={(value) => {
          setDecision(value as "approve" | "return");
        }}
      />
      <FormField id={noteId} label={t("partnerApplications.decisionModal.note")}>
        <Input.TextArea
          id={noteId}
          rows={3}
          value={note}
          maxLength={1000}
          onChange={(event) => {
            setNote(event.target.value);
          }}
        />
      </FormField>
    </FormPanel>
  );
}
