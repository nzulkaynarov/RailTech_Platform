import { Alert, Button, Dropdown, Input, Radio, Segmented, Select } from "antd";
import { Dialog } from "../../../shared/ui/Dialog";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";

import { useAuth } from "../../../app/auth/useAuth";
import { canEdit } from "../../../app/access";
import type {
  PartnerApplicationItem,
  PartnerApplicationKind,
  PartnerApplicationStatus,
  PartnerFromArchiveUpload,
} from "../../../shared/api/generated/model";
import {
  getDownloadPartnerApplicationDocumentUrl,
  getListPartnerApplicationsQueryKey,
  useApprovePartnerApplication,
  useGetPartnerContractOptions,
  useRecordPartnerPackageFromArchive,
  useInvitePartnerCandidate,
  useListPartnerApplications,
  useRejectPartnerApplication,
  useSendContractPartnerApplication,
  useUploadPartnerSignedScan,
} from "../../../shared/api/generated/platform-bff";
import { downloadFile } from "../../../shared/api/download";
import { useFormat } from "../../../shared/lib/useFormat";
import { DateField } from "../../../shared/ui/DateField";
import { EmptyState } from "../../../shared/ui/EmptyState";
import { FilterBar } from "../../../shared/ui/FilterBar";
import { FileField } from "../../../shared/ui/FileField";
import { FormField, QueryState } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { type Column, DataList, FormPanel } from "./common";
import {
  ContractDecisionModal,
  PrepareContractModal,
  TEMPLATE_LIBRARY_PATH,
} from "./PartnerContractModals";
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

  const [prepareRow, setPrepareRow] = useState<PartnerApplicationItem | null>(null);
  const [decisionRow, setDecisionRow] = useState<PartnerApplicationItem | null>(null);
  const [sendContractRow, setSendContractRow] = useState<PartnerApplicationItem | null>(null);
  const [approveRow, setApproveRow] = useState<PartnerApplicationItem | null>(null);
  const [archiveRow, setArchiveRow] = useState<PartnerApplicationItem | null>(null);
  const [inviteRow, setInviteRow] = useState<PartnerApplicationItem | null>(null);
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
      priority: 2,
      title: t("partnerApplications.columns.source"),
      render: (row) => <span>{t(`partnerApplications.source.${row.source}`)}</span>,
    },
    {
      key: "contract",
      title: t("partnerApplications.columns.contract"),
      render: (row) => <ContractCell row={row} />,
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
      priority: 1,
      title: t("partnerApplications.columns.created"),
      render: (row) => <span>{date(row.created_at)}</span>,
    },
    {
      key: "actions",
      title: t("partnerApplications.columns.actions"),
      width: 215,
      render: (row) => {
        if (row.status === "approved" || row.status === "rejected") return null;
        const canPrepare =
          row.status === "submitted" ||
          (row.status === "contract_sent" && row.candidate_returned_at !== null);
        const canSend =
          (row.status === "submitted" ||
            (row.status === "contract_sent" && row.candidate_returned_at !== null)) &&
          row.contract_blocker === null;
        const canResend = row.status === "contract_sent" && row.invite_delivery === "failed";
        const actions: { key: string; label: string; danger?: boolean; run: () => void }[] = [];
        if (row.can_decide_contract && row.contract_approval === "requested") {
          actions.push({
            key: "decide",
            label: t("partnerApplications.actions.decide"),
            run: () => {
              setDecisionRow(row);
            },
          });
        }
        if (canManage && canPrepare && row.contract_source === "") {
          actions.push({
            key: "prepare",
            label: t("partnerApplications.actions.prepare"),
            run: () => {
              setPrepareRow(row);
            },
          });
        }
        if (canManage && (canSend || canResend)) {
          actions.push({
            key: "send",
            label: t(
              canSend
                ? "partnerApplications.actions.sendContract"
                : "partnerApplications.actions.resendContract",
            ),
            run: () => {
              setSendContractRow(row);
            },
          });
        }
        if (canManage && canPrepare && row.contract_source !== "") {
          actions.push({
            key: "prepare",
            label: t("partnerApplications.actions.prepareAgain"),
            run: () => {
              setPrepareRow(row);
            },
          });
        }
        if (canManage && row.status === "contract_sent" && row.email.trim() === "") {
          actions.push({
            key: "invite",
            label: t("partnerApplications.actions.invite"),
            run: () => {
              setInviteRow(row);
            },
          });
        }
        if (canManage && row.status !== "submitted") {
          actions.push({
            key: "approve",
            label: t(
              row.status === "candidate_agreed"
                ? "partnerApplications.actions.approve"
                : "partnerApplications.actions.approveWithoutAgreement",
            ),
            run: () => {
              setApproveRow(row);
            },
          });
        }
        if (canManage && row.status === "submitted") {
          actions.push({
            key: "archive",
            label: t("partnerApplications.actions.fromArchive"),
            run: () => {
              setArchiveRow(row);
            },
          });
        }
        if (canManage) {
          actions.push({
            key: "reject",
            label: t("partnerApplications.actions.reject"),
            danger: true,
            run: () => {
              setRejectRow(row);
            },
          });
        }
        const [first, ...rest] = actions;
        if (!first) return null;
        return (
          <div className="pf-cat-actions">
            <Button
              type={first.danger ? "default" : "primary"}
              danger={first.danger}
              size="small"
              onClick={first.run}
            >
              {first.label}
            </Button>
            {rest.length > 0 ? (
              <Dropdown
                trigger={["click"]}
                menu={{
                  items: rest.map((x) => ({ key: x.key, label: x.label, danger: x.danger })),
                  onClick: ({ key }) => {
                    rest.find((x) => x.key === key)?.run();
                  },
                }}
              >
                <Button size="small" aria-label={t("partnerApplications.actions.more")}>
                  {t("partnerApplications.actions.more")}
                </Button>
              </Dropdown>
            ) : null}
          </div>
        );
      },
    },
  ];

  return (
    <div className="pf-cat-applications">
      <FilterBar>
        <Segmented
          aria-label={t("partnerApplications.filterLabel")}
          value={filter}
          options={STATUS_FILTERS.map((s) => ({
            value: s,
            label: t(`partnerApplications.filter.${s}`),
          }))}
          onChange={(value) => {
            setFilter(value);
          }}
        />
      </FilterBar>

      <QueryState query={query} labels={queryLabels(t)}>
        {(data) =>
          data.items.length === 0 ? (
            <EmptyState
              title={t("partnerApplications.empty.title")}
              text={t("partnerApplications.empty.hint")}
            />
          ) : (
            <DataList
              tableId="erp.catalog.applications"
              label={t("partnerApplications.title")}
              columns={columns}
              rows={data.items}
              rowKey={(r) => r.id}
            />
          )
        }
      </QueryState>

      {prepareRow ? (
        <PrepareContractModal
          item={prepareRow}
          onDone={() => {
            invalidate();
            setPrepareRow(null);
          }}
          onClose={() => {
            setPrepareRow(null);
          }}
        />
      ) : null}

      {decisionRow ? (
        <ContractDecisionModal
          item={decisionRow}
          onDone={() => {
            invalidate();
            setDecisionRow(null);
          }}
          onClose={() => {
            setDecisionRow(null);
          }}
        />
      ) : null}

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

      {archiveRow ? (
        <FromArchiveModal
          item={archiveRow}
          onDone={() => {
            invalidate();
            setArchiveRow(null);
          }}
          onClose={() => {
            setArchiveRow(null);
          }}
        />
      ) : null}

      {inviteRow ? (
        <InviteModal
          item={inviteRow}
          onDone={() => {
            invalidate();
            setInviteRow(null);
          }}
          onClose={() => {
            setInviteRow(null);
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

/**
 * Договор в строке: номер и дата, откуда он и кто решает — словами, из фактов заявки. Что дальше, названо одной строкой:
 * не подготовлен (со ссылкой на библиотеку шаблонов), ждёт решения «Право», возвращён, готов к отправке, у кандидата.
 */
function ContractCell({ row }: { row: PartnerApplicationItem }) {
  const { t } = useTranslation("catalog");
  const { date } = useFormat();
  const open = (which: "contract" | "scan" | "candidate", doc?: string) => {
    void downloadFile(
      getDownloadPartnerApplicationDocumentUrl(row.id, { which, ...(doc ? { doc } : {}) }),
      `${which}-${doc ?? row.id}`,
    ).catch(() => undefined);
  };
  const pack = row.package;
  const approvalLine =
    row.contract_approval === "requested"
      ? t("partnerApplications.contractLine.requested", {
          who:
            row.contract_approvers.length > 0
              ? row.contract_approvers.join(", ")
              : t("partnerApplications.noApprovers"),
        })
      : row.contract_approval === "approved"
        ? t("partnerApplications.contractLine.approved", {
            who: row.contract_approval_decided_by ?? "",
          })
        : row.contract_approval === "returned"
          ? t("partnerApplications.contractLine.returned", { note: row.contract_approval_note })
          : null;
  const waiting = row.contract_waiting_for.join(", ");
  const voted = row.contract_votes
    .filter((vote) => vote.decision === "approve")
    .map((vote) => vote.name);
  return (
    <div>
      {row.contract_number ? <div>№ {row.contract_number}</div> : null}
      {row.contract_date ? <span className="pf-cat-sub">{date(row.contract_date)}</span> : null}
      {row.from_archive ? (
        <span className="pf-cat-sub">{t("partnerApplications.contractLine.fromArchive")}</span>
      ) : null}
      {pack.length > 0 ? (
        <span className="pf-cat-sub">
          {t("partnerApplications.contractLine.package", {
            names: pack.map((doc) => doc.title).join(", "),
            language: t(
              `partnerApplications.prepareModal.languages.${row.contract_language || "ru"}`,
            ),
          })}
        </span>
      ) : null}
      {pack
        .filter((doc) => doc.candidate_remark)
        .map((doc) => (
          <span key={`remark-${doc.id}`} className="pf-cat-sub pf-cat-danger">
            {t("partnerApplications.contractLine.documentRemark", {
              title: doc.title,
              note: doc.candidate_remark,
            })}
          </span>
        ))}
      {row.status === "approved"
        ? pack.map((doc) =>
            doc.valid_until ? (
              <span key={`term-${doc.id}`} className="pf-cat-sub">
                {t("partnerApplications.contractLine.documentUntil", {
                  title: doc.title,
                  date: date(doc.valid_until),
                })}
              </span>
            ) : doc.base_role === "nda" && doc.valid_from ? (
              <span key={`term-${doc.id}`} className="pf-cat-sub">
                {doc.trade_secret_indefinite
                  ? t("partnerApplications.contractLine.secretIndefinite", { title: doc.title })
                  : doc.confidentiality_years
                    ? t("partnerApplications.contractLine.secretYears", {
                        title: doc.title,
                        years: doc.confidentiality_years,
                      })
                    : null}
              </span>
            ) : null,
          )
        : null}
      {row.contract_source === "template" && pack.length === 0 ? (
        <span className="pf-cat-sub">
          {t("partnerApplications.contractLine.template", {
            name: row.contract_template_name ?? "",
            edition: row.contract_template_edition ?? 1,
            language: t(
              `partnerApplications.prepareModal.languages.${row.contract_language || "ru"}`,
            ),
          })}
        </span>
      ) : null}
      {row.contract_source === "upload" ? (
        <span className="pf-cat-sub">{t("partnerApplications.contractLine.upload")}</span>
      ) : null}
      {approvalLine ? <span className="pf-cat-sub">{approvalLine}</span> : null}
      {row.contract_approval === "requested" && voted.length > 0 ? (
        <span className="pf-cat-sub">
          {t("partnerApplications.contractLine.votedApprove", { who: voted.join(", ") })}
        </span>
      ) : null}
      {row.contract_approval === "requested" && row.contract_disagreement ? (
        <span className="pf-cat-sub pf-cat-danger">
          {t("partnerApplications.contractLine.disagreement", { who: waiting })}
        </span>
      ) : null}
      {row.contract_approval === "requested" && !row.contract_disagreement && waiting ? (
        <span className="pf-cat-sub">
          {t("partnerApplications.contractLine.waitingFor", { who: waiting })}
        </span>
      ) : null}
      {row.status === "submitted" && row.contract_blocker === "CONTRACT_NOT_PREPARED" ? (
        <>
          <span className="pf-cat-sub pf-cat-danger">
            {t("partnerApplications.contractLine.notPrepared")}
          </span>
          <span className="pf-cat-sub">
            <Link to={TEMPLATE_LIBRARY_PATH}>{t("partnerApplications.contractLine.library")}</Link>
          </span>
        </>
      ) : null}
      {row.status === "submitted" && row.contract_blocker === null ? (
        <span className="pf-cat-sub">{t("partnerApplications.contractLine.ready")}</span>
      ) : null}
      {row.status === "contract_sent" && row.candidate_returned_at ? (
        <span className="pf-cat-sub pf-cat-danger">
          {t("partnerApplications.contractLine.candidateReturned", { note: row.candidate_notes })}
        </span>
      ) : null}
      {row.status === "contract_sent" && !row.candidate_returned_at ? (
        <span className="pf-cat-sub">{t("partnerApplications.contractLine.waitingCandidate")}</span>
      ) : null}
      {row.status === "contract_sent" && row.email.trim() === "" ? (
        <span className="pf-cat-sub pf-cat-danger">
          {t("partnerApplications.contractLine.noEmail")}
        </span>
      ) : null}
      {row.status === "candidate_agreed" ? (
        <span className="pf-cat-sub">
          {t("partnerApplications.contractLine.awaitingSignature")}
          {row.has_signed_scan
            ? ` · ${t("partnerApplications.contractLine.scanReady", {
                date: row.signed_scan_at ? date(row.signed_scan_at) : "",
              })}`
            : ""}
        </span>
      ) : null}
      {row.status === "approved" && row.contract_valid_until ? (
        <span className="pf-cat-sub">
          {t("partnerApplications.contractLine.validUntil", {
            date: date(row.contract_valid_until),
          })}
          {row.signed_note
            ? ` · ${t("partnerApplications.contractLine.signedNote", { note: row.signed_note })}`
            : ""}
        </span>
      ) : null}
      {pack.length > 0
        ? pack.map((doc) => (
            <span key={`open-${doc.id}`}>
              {doc.has_file ? (
                <Button
                  type="link"
                  size="small"
                  onClick={() => {
                    open("contract", doc.id);
                  }}
                >
                  {doc.title}
                </Button>
              ) : null}
              {doc.has_candidate_file ? (
                <Button
                  type="link"
                  size="small"
                  onClick={() => {
                    open("candidate", doc.id);
                  }}
                >
                  {t("partnerApplications.contractLine.openCandidateFile")}
                </Button>
              ) : null}
            </span>
          ))
        : null}
      {row.contract_source && pack.length === 0 ? (
        <Button
          type="link"
          size="small"
          onClick={() => {
            open("contract");
          }}
        >
          {t("partnerApplications.contractLine.openContract")}
        </Button>
      ) : null}
      {row.has_candidate_file && pack.length === 0 ? (
        <Button
          type="link"
          size="small"
          onClick={() => {
            open("candidate");
          }}
        >
          {t("partnerApplications.contractLine.openCandidateFile")}
        </Button>
      ) : null}
      {row.has_signed_scan ? (
        <Button
          type="link"
          size="small"
          onClick={() => {
            open("scan");
          }}
        >
          {t("partnerApplications.contractLine.openScan")}
        </Button>
      ) : null}
    </div>
  );
}

/** Отправка подготовленного договора: номер, дата и текст уже зафиксированы; здесь только вопрос о найденной компании. */
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
  const [companyChoice, setCompanyChoice] = useState<CompanyChoice | undefined>(undefined);
  const needsChoice = Boolean(item.company_match_pending);

  const sendContract = useSendContractPartnerApplication({
    mutation: {
      onSuccess: onDone,
    },
  });

  return (
    <FormPanel
      title={t("partnerApplications.sendContractModal.title", { name: item.company_name })}
      okLabel={t("partnerApplications.sendContractModal.ok")}
      loading={sendContract.isPending}
      error={sendContract.error}
      disabled={needsChoice && !companyChoice}
      onOk={() => {
        sendContract.mutate({
          id: item.id,
          data: { ...companyDecision(item, companyChoice) },
        });
      }}
      onCancel={onClose}
    >
      <p>{t("partnerApplications.sendContractModal.hint", { email: item.email })}</p>
      {needsChoice ? (
        <CompanyMatchChoice item={item} value={companyChoice} onChange={setCompanyChoice} />
      ) : null}
      {item.email.trim() === "" ? (
        <Alert
          type="warning"
          showIcon
          role="alert"
          message={t("partnerApplications.sendContractModal.noEmail")}
        />
      ) : null}
    </FormPanel>
  );
}

/**
 * «Уже подписано на бумаге» (ОСН-1): партнёр подписал пакет раньше. Заявка сразу одобряется с настоящей датой подписи и
 * сканами по документам; в Кабинет и по почте ничего не уходит. Неполные данные допустимы: сканов может не быть.
 */
function FromArchiveModal({
  item,
  onDone,
  onClose,
}: {
  item: PartnerApplicationItem;
  onDone: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation("catalog");
  const ids = { date: useId(), number: useId(), note: useId() };
  const options = useGetPartnerContractOptions();
  const roles = options.data?.package.roles ?? [];
  const [signedOn, setSignedOn] = useState("");
  const [number, setNumber] = useState(item.contract_number || "");
  const [note, setNote] = useState("");
  const [roleDates, setRoleDates] = useState<Record<string, string>>({});
  const [scans, setScans] = useState<Record<string, File | null>>({});
  const [companyChoice, setCompanyChoice] = useState<CompanyChoice | undefined>(undefined);
  const needsChoice = Boolean(item.company_match_pending);
  const today = new Date().toISOString().slice(0, 10);
  const dateOk = signedOn !== "" && signedOn <= today;

  const record = useRecordPartnerPackageFromArchive({ mutation: { onSuccess: onDone } });

  const send = () => {
    const data: PartnerFromArchiveUpload = {
      signed_on: signedOn,
      ...(number.trim() ? { contract_number: number.trim() } : {}),
      ...(note.trim() ? { note: note.trim() } : {}),
      ...companyDecision(item, companyChoice),
    };
    for (const role of roles) {
      const own = roleDates[role.base_role];
      const scan = scans[role.base_role];
      if (own) data[`signed_on_${role.base_role}`] = own;
      if (scan) data[`scan_${role.base_role}`] = scan;
    }
    record.mutate({ id: item.id, data });
  };

  return (
    <FormPanel
      title={t("partnerApplications.archiveModal.title", { name: item.company_name })}
      okLabel={t("partnerApplications.archiveModal.ok")}
      loading={record.isPending}
      error={record.error}
      disabled={!dateOk || (needsChoice && !companyChoice)}
      onOk={send}
      onCancel={onClose}
    >
      <p>{t("partnerApplications.archiveModal.hint")}</p>
      {needsChoice ? (
        <CompanyMatchChoice item={item} value={companyChoice} onChange={setCompanyChoice} />
      ) : null}
      <FormField
        id={ids.date}
        label={t("partnerApplications.archiveModal.signedOn")}
        hint={t("partnerApplications.archiveModal.signedOnHint")}
      >
        <DateField id={ids.date} value={signedOn} max={today} onChange={setSignedOn} />
      </FormField>
      <FormField id={ids.number} label={t("partnerApplications.contractNumber")}>
        <Input
          id={ids.number}
          value={number}
          maxLength={64}
          placeholder={t("partnerApplications.archiveModal.numberPlaceholder")}
          onChange={(e) => {
            setNumber(e.target.value);
          }}
        />
      </FormField>
      {roles.map((role) => {
        const dateId = `${ids.date}-${role.base_role}`;
        const scanId = `${ids.date}-scan-${role.base_role}`;
        return (
          <fieldset key={role.base_role} className="pf-cat-fieldset">
            <legend>{role.role_name}</legend>
            <FormField id={dateId} label={t("partnerApplications.archiveModal.ownDate")}>
              <DateField
                id={dateId}
                value={roleDates[role.base_role] ?? ""}
                onChange={(value) => {
                  setRoleDates((prev) => ({ ...prev, [role.base_role]: value }));
                }}
              />
            </FormField>
            <FormField
              id={scanId}
              label={t("partnerApplications.archiveModal.scan")}
              hint={t("partnerApplications.archiveModal.scanHint")}
            >
              <FileField
                id={scanId}
                value={scans[role.base_role] ? [scans[role.base_role] as File] : []}
                accept=".pdf,.jpg,.jpeg,.png,.webp"
                maxSize={20 * 1024 * 1024}
                aria-describedby={`${scanId}-hint`}
                onChange={(files) => {
                  setScans((prev) => ({ ...prev, [role.base_role]: files[0] ?? null }));
                }}
              />
            </FormField>
          </fieldset>
        );
      })}
      <FormField id={ids.note} label={t("partnerApplications.approveModal.noteLabel")}>
        <Input.TextArea
          id={ids.note}
          rows={2}
          value={note}
          maxLength={1000}
          placeholder={t("partnerApplications.approveModal.notePlaceholder")}
          onChange={(e) => {
            setNote(e.target.value);
          }}
        />
      </FormField>
    </FormPanel>
  );
}

/**
 * «Отметить: подписан» (ПК-1): скан подписанного договора ИЛИ заметка — скан не обязателен. Срок договора считается в
 * этот момент по правилу компании. Без согласия кандидата — только с причиной (журнал), как и раньше.
 */
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
  const scanId = useId();
  const noteId = useId();
  const [contractNumber, setContractNumber] = useState(item.contract_number || "");
  const [contractDate, setContractDate] = useState(
    item.contract_date || new Date().toISOString().slice(0, 10),
  );
  const [kind, setKind] = useState<PartnerApplicationKind>(item.kind || "supplier");
  const [companyChoice, setCompanyChoice] = useState<CompanyChoice | undefined>(undefined);
  const [overrideReason, setOverrideReason] = useState("");
  const [signedNote, setSignedNote] = useState("");
  const [scan, setScan] = useState<File | null>(null);
  const needsChoice = Boolean(item.company_match_pending);
  const withoutAgreement = item.status === "contract_sent";
  // Договор подготовлен в системе: «подписан» подтверждается сканом ИЛИ заметкой (скан не обязателен)
  const needsProof = item.contract_source !== "" && !item.has_signed_scan;
  const proofGiven = scan !== null || signedNote.trim() !== "";

  const approve = useApprovePartnerApplication({
    mutation: {
      onSuccess: onDone,
    },
  });
  const upload = useUploadPartnerSignedScan();

  const fields = errorFields(approve.error);
  const reasonId = useId();
  const send = () => {
    approve.mutate({
      id: item.id,
      data: {
        contract_number: contractNumber.trim(),
        contract_date: contractDate || undefined,
        kind,
        ...companyDecision(item, companyChoice),
        ...(withoutAgreement ? { override_reason: overrideReason.trim() } : {}),
        ...(signedNote.trim() ? { signed_note: signedNote.trim() } : {}),
      },
    });
  };

  return (
    <FormPanel
      title={t("partnerApplications.approveModal.title", { name: item.company_name })}
      okLabel={t("partnerApplications.approveModal.ok")}
      loading={approve.isPending || upload.isPending}
      error={approve.error ?? upload.error}
      disabled={
        !contractNumber.trim() ||
        (needsChoice && !companyChoice) ||
        (needsProof && !proofGiven) ||
        (withoutAgreement && !overrideReason.trim())
      }
      onOk={() => {
        if (scan) {
          upload.mutate({ id: item.id, data: { file: scan } }, { onSuccess: send });
        } else {
          send();
        }
      }}
      onCancel={onClose}
    >
      {withoutAgreement && !overrideReason.trim() ? (
        <p className="pf-hint" role="status">
          {t("partnerApplications.approveModal.needReason")}
        </p>
      ) : !contractNumber.trim() ||
        (needsChoice && !companyChoice) ||
        (needsProof && !proofGiven) ? (
        <p className="pf-hint" role="status">
          {t("partnerApplications.approveModal.needFields")}
        </p>
      ) : null}
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

      {needsProof ? (
        <>
          <FormField
            id={scanId}
            label={t("partnerApplications.approveModal.scanLabel")}
            hint={t("partnerApplications.approveModal.scanHint")}
          >
            <FileField
              id={scanId}
              value={scan ? [scan] : []}
              accept=".pdf,.jpg,.jpeg,.png,.webp"
              maxSize={20 * 1024 * 1024}
              aria-describedby={`${scanId}-hint`}
              onChange={(files) => {
                setScan(files[0] ?? null);
              }}
            />
          </FormField>
          <FormField id={noteId} label={t("partnerApplications.approveModal.noteLabel")}>
            <Input.TextArea
              id={noteId}
              rows={2}
              value={signedNote}
              onChange={(e) => {
                setSignedNote(e.target.value);
              }}
              placeholder={t("partnerApplications.approveModal.notePlaceholder")}
              maxLength={1000}
            />
          </FormField>
        </>
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
    </FormPanel>
  );
}

/** «Пригласить в Кабинет» позже (ПК-1): договор ушёл без почты, теперь адрес известен. */
function InviteModal({
  item,
  onDone,
  onClose,
}: {
  item: PartnerApplicationItem;
  onDone: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation("catalog");
  const emailId = useId();
  const [email, setEmail] = useState("");
  const valid = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim());
  const invite = useInvitePartnerCandidate({ mutation: { onSuccess: onDone } });
  return (
    <FormPanel
      title={t("partnerApplications.inviteModal.title", { name: item.company_name })}
      okLabel={t("partnerApplications.inviteModal.ok")}
      loading={invite.isPending}
      error={invite.error}
      disabled={!valid}
      onOk={() => {
        invite.mutate({ id: item.id, data: { email: email.trim() } });
      }}
      onCancel={onClose}
    >
      <p>{t("partnerApplications.inviteModal.hint")}</p>
      <FormField id={emailId} label={t("partnerApplications.inviteModal.email")}>
        <Input
          id={emailId}
          type="email"
          value={email}
          maxLength={254}
          onChange={(e) => {
            setEmail(e.target.value);
          }}
        />
      </FormField>
    </FormPanel>
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
    <Dialog
      open
      title={t("partnerApplications.rejectModal.title", { name: item.company_name })}
      okLabel={t("partnerApplications.rejectModal.ok")}
      danger={true}
      loading={reject.isPending}
      okDisabled={!reason.trim()}
      cancelLabel={t("cancel")}
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
    </Dialog>
  );
}
