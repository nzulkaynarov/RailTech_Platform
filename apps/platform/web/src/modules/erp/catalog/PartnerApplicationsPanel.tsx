import { Button, Input, Modal, Radio, Select } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";

import { useAuth } from "../../../app/auth/useAuth";
import { canEdit } from "../../../app/access";
import type {
  PartnerApplicationItem,
  PartnerApplicationKind,
  PartnerApplicationStatus,
} from "../../../shared/api/generated/model";
import {
  getListPartnerApplicationsQueryKey,
  useApprovePartnerApplication,
  useListPartnerApplications,
  useRejectPartnerApplication,
  useSendContractPartnerApplication,
} from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { DateField } from "../../../shared/ui/DateField";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { FormField, QueryState } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { type Column, DataList, FormModal } from "./common";
import { errorFields } from "./errors";
import { queryLabels } from "./labels";

const STATUS_FILTERS: readonly (PartnerApplicationStatus | "all")[] = [
  "all",
  "submitted",
  "contract_sent",
  "candidate_agreed",
  "approved",
  "rejected",
];
type FilterStatus = PartnerApplicationStatus | "all";

const KINDS: PartnerApplicationKind[] = ["manufacturer", "supplier", "principal", "other"];

/**
 * Очередь заявок кандидатов в партнёры (PART-ONBOARD-2, ADR-0022).
 * Договорной шлюз для снабжения:
 * - Просмотр анкет заявителей (публичные и из кабинета клиента);
 * - Сопоставление с базой контрагентов по ИНН: совпадение — вопрос сотруднику, не автопривязка (FX-1);
 * - Отправка проекта договора;
 * - Одобрение после согласия кандидата (без согласия — только с причиной в журнале, FX-1);
 * - Отклонение с указанием причины.
 */
export function PartnerApplicationsPanel() {
  const { t } = useTranslation("catalog");
  const { date } = useFormat();
  const { me } = useAuth();
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<FilterStatus>("all");
  const query = useListPartnerApplications({
    status: filter === "all" ? undefined : filter,
  });

  const [sendContractRow, setSendContractRow] = useState<PartnerApplicationItem | null>(null);
  const [approveRow, setApproveRow] = useState<PartnerApplicationItem | null>(null);
  const [rejectRow, setRejectRow] = useState<PartnerApplicationItem | null>(null);

  const canManage = canEdit(me, "erp.stock");

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: getListPartnerApplicationsQueryKey() });
  };

  const columns: Column<PartnerApplicationItem>[] = [
    {
      key: "company",
      title: t("partnerApplications.columns.company"),
      render: (row) => (
        <div>
          <strong>{row.company_name}</strong>
          {row.inn ? (
            <span className="pf-cat-sub">{t("partnerApplications.inn", { inn: row.inn })}</span>
          ) : null}
          {row.matching_company_name ? (
            <div className="pf-cat-match-badge" title={t("partnerApplications.matchHint")}>
              {t("partnerApplications.matchFound", { name: row.matching_company_name })}
            </div>
          ) : null}
        </div>
      ),
    },
    {
      key: "contact",
      title: t("partnerApplications.columns.contact"),
      render: (row) => (
        <div>
          <div>{row.contact_name}</div>
          <span className="pf-cat-sub">{row.email}</span>
          {row.phone ? <span className="pf-cat-sub">{row.phone}</span> : null}
          {row.invite_delivery === "failed" ? (
            <span className="pf-cat-sub pf-cat-danger">
              {t("partnerApplications.inviteFailed")}
            </span>
          ) : null}
        </div>
      ),
    },
    {
      key: "kind",
      title: t("partnerApplications.columns.kind"),
      render: (row) => (
        <div>
          <div>{t(`cabinetAccess.kind.${row.kind}`)}</div>
          {row.categories_description ? (
            <span className="pf-cat-sub">{row.categories_description}</span>
          ) : null}
        </div>
      ),
    },
    {
      key: "source",
      title: t("partnerApplications.columns.source"),
      render: (row) => <span>{t(`partnerApplications.source.${row.source}`)}</span>,
    },
    {
      key: "contract",
      title: t("partnerApplications.columns.contract"),
      render: (row) => (
        <div>
          {row.contract_number ? (
            <div>№ {row.contract_number}</div>
          ) : (
            <span className="pf-cat-sub">—</span>
          )}
          {row.contract_date ? <span className="pf-cat-sub">{date(row.contract_date)}</span> : null}
        </div>
      ),
    },
    {
      key: "status",
      title: t("partnerApplications.columns.status"),
      render: (row) => (
        <div>
          <StatusTag kind="partnerApplication" status={row.status}>
            {t(`partnerApplications.status.${row.status}`)}
          </StatusTag>
          {row.rejected_reason ? (
            <span className="pf-cat-sub pf-cat-danger" title={row.rejected_reason}>
              {row.rejected_reason}
            </span>
          ) : null}
          {row.reviewed_at ? (
            <span className="pf-cat-sub">
              {t("partnerApplications.reviewedAt", { date: date(row.reviewed_at) })}
            </span>
          ) : null}
        </div>
      ),
    },
    {
      key: "created",
      title: t("partnerApplications.columns.created"),
      render: (row) => <span>{date(row.created_at)}</span>,
    },
    {
      key: "actions",
      title: t("partnerApplications.columns.actions"),
      width: 220,
      render: (row) => {
        if (!canManage || row.status === "approved" || row.status === "rejected") {
          return null;
        }
        return (
          <div className="pf-cat-actions">
            {row.status === "submitted" ||
            (row.status === "contract_sent" && row.invite_delivery === "failed") ? (
              <Button
                size="small"
                onClick={() => {
                  setSendContractRow(row);
                }}
              >
                {t(
                  row.status === "submitted"
                    ? "partnerApplications.actions.sendContract"
                    : "partnerApplications.actions.resendContract",
                )}
              </Button>
            ) : null}
            {row.status === "submitted" ? null : (
              <Button
                type={row.status === "candidate_agreed" ? "primary" : "default"}
                size="small"
                onClick={() => {
                  setApproveRow(row);
                }}
              >
                {t(
                  row.status === "candidate_agreed"
                    ? "partnerApplications.actions.approve"
                    : "partnerApplications.actions.approveWithoutAgreement",
                )}
              </Button>
            )}
            <Button
              danger
              size="small"
              onClick={() => {
                setRejectRow(row);
              }}
            >
              {t("partnerApplications.actions.reject")}
            </Button>
          </div>
        );
      },
    },
  ];

  return (
    <div className="pf-cat-applications">
      <div className="pf-cat-toolbar">
        <div
          className="pf-cat-filters"
          role="group"
          aria-label={t("partnerApplications.filterLabel")}
        >
          {STATUS_FILTERS.map((s) => (
            <Button
              key={s}
              type={filter === s ? "primary" : "default"}
              size="small"
              onClick={() => {
                setFilter(s);
              }}
            >
              {t(`partnerApplications.filter.${s}`)}
            </Button>
          ))}
        </div>
      </div>

      <QueryState query={query} labels={queryLabels(t)}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState
              title={t("partnerApplications.empty.title")}
              text={t("partnerApplications.empty.hint")}
            />
          ) : (
            <DataList
              label={t("partnerApplications.title")}
              columns={columns}
              rows={data.items}
              rowKey={(r) => r.id}
            />
          )
        }
      </QueryState>

      {sendContractRow ? (
        <SendContractModal
          item={sendContractRow}
          onDone={() => {
            invalidate();
            setSendContractRow(null);
          }}
          onClose={() => {
            setSendContractRow(null);
          }}
        />
      ) : null}

      {approveRow ? (
        <ApproveModal
          item={approveRow}
          onDone={() => {
            invalidate();
            setApproveRow(null);
          }}
          onClose={() => {
            setApproveRow(null);
          }}
        />
      ) : null}

      {rejectRow ? (
        <RejectModal
          item={rejectRow}
          onDone={() => {
            invalidate();
            setRejectRow(null);
          }}
          onClose={() => {
            setRejectRow(null);
          }}
        />
      ) : null}
    </div>
  );
}

type CompanyChoice = "match" | "new";

/** Запрос к форме по решению сотрудника о найденной организации: подтвердить её или завести новую. */
function companyDecision(item: PartnerApplicationItem, choice: CompanyChoice | undefined) {
  if (!item.company_match_pending) return {};
  return choice === "new"
    ? { create_new_company: true }
    : { company_id: item.matching_company_id ?? undefined };
}

/**
 * Вопрос о найденной организации: ИНН и рег. номер в анкете никем не проверены, совпадение — предложение, а не привязка
 * (DECISIONS 2026-11-04). Занятый ИНН завести заново нельзя: другая компания с таким ИНН — это опечатка, заявка отклоняется.
 */
function CompanyMatchChoice({
  item,
  value,
  onChange,
}: {
  item: PartnerApplicationItem;
  value: CompanyChoice | undefined;
  onChange: (next: CompanyChoice) => void;
}) {
  const { t } = useTranslation("catalog");
  return (
    <div className="pf-cat-match-choice" style={{ marginBottom: 16 }}>
      <p>
        <strong>
          {t("partnerApplications.matchQuestion", { name: item.matching_company_name })}
        </strong>
      </p>
      <Radio.Group
        value={value}
        onChange={(e) => {
          onChange(e.target.value as CompanyChoice);
        }}
      >
        <Radio value="match">
          {t("partnerApplications.approveModal.linkToExisting", {
            name: item.matching_company_name ?? item.matching_company_id,
          })}
        </Radio>
        {item.company_match_pending === "registration_number" ? (
          <Radio value="new">{t("partnerApplications.approveModal.createNew")}</Radio>
        ) : null}
      </Radio.Group>
      {item.company_match_pending === "inn" ? (
        <p className="pf-cat-sub">{t("partnerApplications.matchInnTaken")}</p>
      ) : null}
    </div>
  );
}

function SendContractModal({
  item,
  onDone,
  onClose,
}: {
  item: PartnerApplicationItem;
  onDone: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation("catalog");
  const numId = useId();
  const dateId = useId();
  const [contractNumber, setContractNumber] = useState(item.contract_number || "");
  const [contractDate, setContractDate] = useState(item.contract_date || "");
  const [companyChoice, setCompanyChoice] = useState<CompanyChoice | undefined>(undefined);
  const needsChoice = Boolean(item.company_match_pending);

  const sendContract = useSendContractPartnerApplication({
    mutation: {
      onSuccess: onDone,
    },
  });

  return (
    <FormModal
      title={t("partnerApplications.sendContractModal.title", { name: item.company_name })}
      okLabel={t("partnerApplications.sendContractModal.ok")}
      loading={sendContract.isPending}
      error={sendContract.error}
      disabled={needsChoice && !companyChoice}
      onOk={() => {
        sendContract.mutate({
          id: item.id,
          data: {
            contract_number: contractNumber.trim() || undefined,
            contract_date: contractDate || undefined,
            ...companyDecision(item, companyChoice),
          },
        });
      }}
      onCancel={onClose}
    >
      <p>{t("partnerApplications.sendContractModal.hint")}</p>
      {needsChoice ? (
        <CompanyMatchChoice item={item} value={companyChoice} onChange={setCompanyChoice} />
      ) : null}
      <FormField id={numId} label={t("partnerApplications.contractNumber")}>
        <Input
          id={numId}
          value={contractNumber}
          onChange={(e) => {
            setContractNumber(e.target.value);
          }}
          placeholder={t("partnerApplications.contractNumberPlaceholder")}
        />
      </FormField>
      <FormField id={dateId} label={t("partnerApplications.contractDate")}>
        <DateField
          id={dateId}
          value={contractDate}
          onChange={(val) => {
            setContractDate(val);
          }}
        />
      </FormField>
    </FormModal>
  );
}

function ApproveModal({
  item,
  onDone,
  onClose,
}: {
  item: PartnerApplicationItem;
  onDone: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation("catalog");
  const numId = useId();
  const dateId = useId();
  const kindId = useId();
  const [contractNumber, setContractNumber] = useState(item.contract_number || "");
  const [contractDate, setContractDate] = useState(
    item.contract_date || new Date().toISOString().slice(0, 10),
  );
  const [kind, setKind] = useState<PartnerApplicationKind>(item.kind || "supplier");
  const [companyChoice, setCompanyChoice] = useState<CompanyChoice | undefined>(undefined);
  const [overrideReason, setOverrideReason] = useState("");
  const needsChoice = Boolean(item.company_match_pending);
  const withoutAgreement = item.status === "contract_sent";

  const approve = useApprovePartnerApplication({
    mutation: {
      onSuccess: onDone,
    },
  });

  const fields = errorFields(approve.error);
  const reasonId = useId();

  return (
    <FormModal
      title={t("partnerApplications.approveModal.title", { name: item.company_name })}
      okLabel={t("partnerApplications.approveModal.ok")}
      loading={approve.isPending}
      error={approve.error}
      disabled={
        !contractNumber.trim() ||
        (needsChoice && !companyChoice) ||
        (withoutAgreement && !overrideReason.trim())
      }
      onOk={() => {
        approve.mutate({
          id: item.id,
          data: {
            contract_number: contractNumber.trim(),
            contract_date: contractDate || undefined,
            kind,
            ...companyDecision(item, companyChoice),
            ...(withoutAgreement ? { override_reason: overrideReason.trim() } : {}),
          },
        });
      }}
      onCancel={onClose}
    >
      <p>
        {t(
          withoutAgreement
            ? "partnerApplications.approveModal.hintOverride"
            : "partnerApplications.approveModal.hint",
        )}
      </p>

      {needsChoice ? (
        <CompanyMatchChoice item={item} value={companyChoice} onChange={setCompanyChoice} />
      ) : null}

      {withoutAgreement ? (
        <FormField id={reasonId} label={t("partnerApplications.approveModal.overrideLabel")}>
          <Input.TextArea
            id={reasonId}
            rows={2}
            value={overrideReason}
            onChange={(e) => {
              setOverrideReason(e.target.value);
            }}
            placeholder={t("partnerApplications.approveModal.overridePlaceholder")}
            maxLength={1000}
          />
        </FormField>
      ) : null}

      <FormField id={numId} label={t("partnerApplications.contractNumber")}>
        <Input
          id={numId}
          value={contractNumber}
          status={fields.includes("contract_number") ? "error" : undefined}
          onChange={(e) => {
            setContractNumber(e.target.value);
          }}
          placeholder={t("partnerApplications.contractNumberPlaceholder")}
        />
      </FormField>

      <FormField id={dateId} label={t("partnerApplications.contractDate")}>
        <DateField
          id={dateId}
          value={contractDate}
          onChange={(val) => {
            setContractDate(val);
          }}
        />
      </FormField>

      <FormField id={kindId} label={t("partnerApplications.kind")}>
        <Select
          id={kindId}
          value={kind}
          onChange={(v) => {
            setKind(v);
          }}
          options={KINDS.map((k) => ({
            value: k,
            label: t(`cabinetAccess.kind.${k}`),
          }))}
        />
      </FormField>
    </FormModal>
  );
}

function RejectModal({
  item,
  onDone,
  onClose,
}: {
  item: PartnerApplicationItem;
  onDone: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation("catalog");
  const reasonId = useId();
  const [reason, setReason] = useState("");

  const reject = useRejectPartnerApplication({
    mutation: {
      onSuccess: onDone,
    },
  });

  const fields = errorFields(reject.error);

  return (
    <Modal
      open
      title={t("partnerApplications.rejectModal.title", { name: item.company_name })}
      okText={t("partnerApplications.rejectModal.ok")}
      okButtonProps={{ danger: true, loading: reject.isPending, disabled: !reason.trim() }}
      cancelText={t("cancel")}
      onOk={() => {
        reject.mutate({
          id: item.id,
          data: {
            rejected_reason: reason.trim(),
          },
        });
      }}
      onCancel={onClose}
    >
      <p>{t("partnerApplications.rejectModal.hint")}</p>
      <FormField id={reasonId} label={t("partnerApplications.rejectModal.reasonLabel")}>
        <Input.TextArea
          id={reasonId}
          rows={4}
          value={reason}
          status={fields.includes("rejected_reason") ? "error" : undefined}
          onChange={(e) => {
            setReason(e.target.value);
          }}
          placeholder={t("partnerApplications.rejectModal.reasonPlaceholder")}
          maxLength={1000}
          showCount
        />
      </FormField>
    </Modal>
  );
}
