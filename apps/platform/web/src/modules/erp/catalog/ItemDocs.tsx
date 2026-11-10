import { useQueryClient } from "@tanstack/react-query";
import { App, Button, Input } from "antd";
import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router";

import type { CatalogItemDetail, CatalogTechDocRef } from "../../../shared/api/generated/model";
import {
  getGetCatalogItemQueryKey,
  getListCatalogItemsQueryKey,
  getListTechDocsQueryKey,
  useGetCatalogLookups,
  useUpdateTechDoc,
  useUploadTechDoc,
} from "../../../shared/api/generated/platform-bff";
import { formatFileSize } from "../../../shared/lib/fileSize";
import { useFormat } from "../../../shared/lib/useFormat";
import { FileField } from "../../../shared/ui/FileField";
import { FormField } from "../../../shared/ui/FormParts";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { FormModal } from "./common";
import { DocPassportFields } from "./DocPassport";
import { emptyPassport, passportFields, usePassport } from "./passportState";
import { errorFields } from "./errors";

export const DOC_MAX_BYTES = 20 * 1024 * 1024;
export const DOC_ACCEPT = ".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx";

/** Срок документа словом: «до 31.12.2027», «бессрочно»; истёкший — отдельной пометкой для сотрудника. */
export function DocValidity({
  doc,
}: {
  doc: Pick<CatalogTechDocRef, "valid_until" | "is_expired">;
}) {
  const { t } = useTranslation("catalog");
  const { date } = useFormat();
  return (
    <>
      {doc.valid_until
        ? t("cardDocs.validUntil", { date: date(doc.valid_until) })
        : t("cardDocs.forever")}
      {doc.is_expired ? (
        <>
          {" "}
          <StatusTag kind="validity" status="expired">
            {t("cardDocs.expired")}
          </StatusTag>
        </>
      ) : null}
    </>
  );
}

/**
 * Карточка товара · Документы (CAT-CARD-1): вид из справочника, номер, кем выдан, срок, «видно клиенту». Загрузка прямо из
 * карточки — документ сразу привязан к этому товару. Эталоны: 1С:УТ «Сертификаты номенклатуры», GS1 GDSN.
 */
export function ItemDocs({ card, editable }: { card: CatalogItemDetail; editable: boolean }) {
  const { t, i18n } = useTranslation("catalog");
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<CatalogTechDocRef | null>(null);
  return (
    <section aria-labelledby="pf-docs-title">
      <h3 className="pf-cat-section" id="pf-docs-title">
        {t("cardDocs.title")}{" "}
        {card.docs_count > 0 ? <span className="pf-hint pf-num">{card.docs_count}</span> : null}
      </h3>
      {card.tech_docs.length === 0 ? (
        <p className="pf-cat-note">{t("items.noDocs")}</p>
      ) : (
        <ul className="pf-cat-docs" aria-label={t("cardDocs.list")}>
          {card.tech_docs.map((doc) => (
            <li key={doc.id} className="pf-cat-doc">
              <div>
                <Link className="pf-focusable" to={`/erp/docs?doc=${doc.id}`}>
                  {doc.title}
                </Link>{" "}
                <span className="pf-hint">{doc.kind_name}</span>
              </div>
              <div className="pf-cat-sub">
                {doc.number || t("cardDocs.numberless")} · <DocValidity doc={doc} /> ·{" "}
                {doc.client_visible ? t("cardDocs.visible") : t("cardDocs.hidden")} ·{" "}
                {formatFileSize(doc.size_bytes, i18n.language)}
              </div>
              {doc.issued_by ? <div className="pf-cat-sub">{doc.issued_by}</div> : null}
              {editable ? (
                <div className="pf-cat-actions">
                  <Button
                    size="small"
                    aria-label={t("cardDocs.editNamed", { title: doc.title })}
                    onClick={() => {
                      setEditing(doc);
                    }}
                  >
                    {t("cardDocs.edit")}
                  </Button>
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {editable ? (
        <div className="pf-cat-actions">
          <Button
            onClick={() => {
              setAdding(true);
            }}
          >
            {t("cardDocs.add")}
          </Button>
        </div>
      ) : null}
      {adding ? (
        <AddDocForm
          card={card}
          onClose={() => {
            setAdding(false);
          }}
        />
      ) : null}
      {editing ? (
        <EditDocForm
          card={card}
          doc={editing}
          onClose={() => {
            setEditing(null);
          }}
        />
      ) : null}
    </section>
  );
}

function useRefresh(card: CatalogItemDetail) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: getGetCatalogItemQueryKey(card.id) });
    void queryClient.invalidateQueries({ queryKey: getListCatalogItemsQueryKey() });
    void queryClient.invalidateQueries({ queryKey: getListTechDocsQueryKey() });
  };
}

/** Загрузка документа из карточки: файл, название и паспорт; товар подставлен. */
function AddDocForm({ card, onClose }: { card: CatalogItemDetail; onClose: () => void }) {
  const { t } = useTranslation("catalog");
  const refresh = useRefresh(card);
  const kinds = useGetCatalogLookups().data?.document_kinds ?? [];
  const [passport, setPassport] = usePassport(kinds);
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const fileId = useId();
  const titleId = useId();
  const mutation = useUploadTechDoc({
    mutation: {
      onSuccess: () => {
        refresh();
        onClose();
      },
    },
  });
  const fields = errorFields(mutation.error);
  return (
    <FormModal
      title={t("cardDocs.addTitle")}
      okLabel={t("docs.form.ok")}
      loading={mutation.isPending}
      error={mutation.error}
      disabled={file === null}
      onOk={() => {
        if (!file) return;
        mutation.mutate({
          data: {
            file,
            product_id: card.id,
            ...(title.trim() ? { title: title.trim() } : {}),
            ...passportFields(passport),
          },
        });
      }}
      onCancel={onClose}
    >
      <FormField id={fileId} label={t("docs.form.file")} hint={t("docs.form.fileHint")}>
        <FileField
          id={fileId}
          value={file ? [file] : []}
          accept={DOC_ACCEPT}
          maxSize={DOC_MAX_BYTES}
          aria-describedby={`${fileId}-hint`}
          aria-invalid={fields.includes("file")}
          onChange={(files) => {
            const next = files[0] ?? null;
            setFile(next);
            if (next && title === "") setTitle(next.name.replace(/\.[^.]+$/, ""));
          }}
        />
      </FormField>
      <FormField id={titleId} label={t("docs.form.name")}>
        <Input
          id={titleId}
          value={title}
          maxLength={255}
          onChange={(event) => {
            setTitle(event.target.value);
          }}
        />
      </FormField>
      <DocPassportFields value={passport} onChange={setPassport} kinds={kinds} invalid={fields} />
    </FormModal>
  );
}

/** Правка паспорта документа: файл не меняется. */
function EditDocForm({
  card,
  doc,
  onClose,
}: {
  card: CatalogItemDetail;
  doc: CatalogTechDocRef;
  onClose: () => void;
}) {
  const { t } = useTranslation("catalog");
  const { message } = App.useApp();
  const refresh = useRefresh(card);
  const kinds = useGetCatalogLookups().data?.document_kinds ?? [];
  const [passport, setPassport] = usePassport(kinds, {
    ...emptyPassport(kinds),
    kind: doc.kind,
    number: doc.number,
    issuedBy: doc.issued_by,
    issuedAt: doc.issued_at ?? "",
    validUntil: doc.valid_until ?? "",
    clientVisible: doc.client_visible,
    visibleTouched: true,
  });
  const [title, setTitle] = useState(doc.title);
  const titleId = useId();
  const mutation = useUpdateTechDoc({
    mutation: {
      onSuccess: () => {
        refresh();
        void message.success(t("cardDocs.saved"));
        onClose();
      },
    },
  });
  const fields = errorFields(mutation.error);
  return (
    <FormModal
      title={t("cardDocs.editTitle")}
      okLabel={t("save")}
      loading={mutation.isPending}
      error={mutation.error}
      disabled={title.trim() === ""}
      onOk={() => {
        mutation.mutate({
          id: doc.id,
          data: {
            title: title.trim(),
            kind: passport.kind,
            number: passport.number.trim(),
            issued_by: passport.issuedBy.trim(),
            issued_at: passport.issuedAt || null,
            valid_until: passport.validUntil || null,
            client_visible: passport.clientVisible,
          },
        });
      }}
      onCancel={onClose}
    >
      <FormField id={titleId} label={t("docs.form.name")}>
        <Input
          id={titleId}
          value={title}
          maxLength={255}
          onChange={(event) => {
            setTitle(event.target.value);
          }}
        />
      </FormField>
      <DocPassportFields
        value={passport}
        onChange={setPassport}
        kinds={kinds}
        invalid={fields}
        currentKind={{ code: doc.kind, name: doc.kind_name }}
      />
    </FormModal>
  );
}
