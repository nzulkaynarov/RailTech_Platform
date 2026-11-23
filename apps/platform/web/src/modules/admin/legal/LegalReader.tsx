import { Alert, Button, Radio, Skeleton } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { useGetLegalEdition } from "../../../shared/api/generated/platform-bff";
import { useFormat } from "../../../shared/lib/useFormat";
import { LegalText, type LegalLang } from "./LegalText";

import "./legal.css";

const LANGS: readonly LegalLang[] = ["ru", "uz", "en"];

/** Чтение редакции на трёх языках: так текст увидит контакт кабинета (подстановки реквизитов уже заполнены). */
export function LegalReader({ id, onClose }: { id: string; onClose: () => void }) {
  const { t, i18n } = useTranslation("legal");
  const format = useFormat();
  const query = useGetLegalEdition(id);
  const initial = (LANGS as readonly string[]).includes(i18n.language)
    ? (i18n.language as LegalLang)
    : "ru";
  const [lang, setLang] = useState<LegalLang>(initial);

  if (query.isPending) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (query.isError) {
    return (
      <Alert
        type="error"
        showIcon
        role="alert"
        message={t("loadError")}
        description={t("loadErrorText")}
        action={
          <Button
            onClick={() => {
              void query.refetch();
            }}
          >
            {t("retry")}
          </Button>
        }
      />
    );
  }
  const edition = query.data;
  const date = format.date(edition.published_at ?? edition.created_at);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <Button onClick={onClose}>{t("actions.back")}</Button>
      </div>
      <h2 style={{ margin: 0, fontSize: 16, lineHeight: "24px", fontWeight: 600 }}>
        {t("reader.title", { kind: t(`kinds.${edition.kind}`), date })}
      </h2>
      <p className="pf-hint" style={{ margin: 0 }}>
        {t("reader.note")}
      </p>
      <Radio.Group
        aria-label={t("reader.language")}
        optionType="button"
        value={lang}
        options={LANGS.map((value) => ({ value, label: t(`languages.${value}`) }))}
        onChange={(event) => {
          setLang(event.target.value as LegalLang);
        }}
      />
      <div
        className="pf-legal-reader"
        tabIndex={0}
        role="region"
        aria-label={t("reader.title", { kind: t(`kinds.${edition.kind}`), date })}
      >
        <LegalText content={edition.rendered} lang={lang} />
      </div>
    </div>
  );
}
