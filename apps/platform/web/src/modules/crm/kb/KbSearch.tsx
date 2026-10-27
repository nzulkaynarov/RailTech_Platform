import { Alert, Button, Card, Input, Select } from "antd";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import type { KbSearchResult, Language } from "../../../shared/api/generated/model";
import { useSearchKb } from "../../../shared/api/generated/platform-bff";
import { StatusTag } from "../../../shared/ui/StatusTag";
import { ErrorNote, FormField } from "../../../shared/ui/FormParts";
import { kbErrorText } from "./errors";

const LANGUAGES: readonly Language[] = ["ru", "uz", "en"];

function Result({ result }: { result: KbSearchResult }) {
  const { t } = useTranslation("kb");
  const score = result.best_score === null ? t("search.noScore") : result.best_score.toFixed(2);
  return (
    <div className="pf-kb-result">
      <Alert
        showIcon
        role="status"
        type={result.confident ? "success" : "warning"}
        message={t(result.confident ? "search.confident" : "search.notConfident")}
        description={t("search.score", { score, min: result.min_score.toFixed(2) })}
      />
      {result.hits.length === 0 ? (
        <p className="pf-hint">{t("search.noHits")}</p>
      ) : (
        <ol className="pf-kb-hits" aria-label={t("search.hitsLabel")}>
          {result.hits.map((hit) => (
            <li key={hit.chunk_id}>
              <div className="pf-kb-hit-head">
                <strong>{hit.document_title}</strong>
                {hit.heading_path ? <span className="pf-hint">{hit.heading_path}</span> : null}
                <StatusTag tone="default">
                  {t("search.similarity", {
                    value:
                      hit.similarity === null ? t("search.noScore") : hit.similarity.toFixed(2),
                  })}
                </StatusTag>
              </div>
              <p className="pf-kb-hit-text">{hit.content}</p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** «Что найдёт бот на этот вопрос» — тот же поиск и порог, что у диалогового агента; ничего не меняет. */
export function KbSearch() {
  const { t, i18n } = useTranslation("kb");
  const [query, setQuery] = useState("");
  const [language, setLanguage] = useState<Language | "any">("any");
  const search = useSearchKb();
  const run = () => {
    const text = query.trim();
    if (text === "" || search.isPending) return;
    search.mutate({ data: { query: text, ...(language === "any" ? {} : { language }) } });
  };
  return (
    <Card
      title={<h2 className="pf-kb-section-title">{t("search.title")}</h2>}
      styles={{ body: { display: "flex", flexDirection: "column", gap: 12 } }}
    >
      <p className="pf-fp-sub">{t("search.hint")}</p>
      <form
        className="pf-kb-search-form"
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          run();
        }}
      >
        <FormField id="kb-search-query" label={t("search.query")}>
          <Input
            id="kb-search-query"
            value={query}
            maxLength={2000}
            autoComplete="off"
            onChange={(event) => {
              setQuery(event.target.value);
            }}
          />
        </FormField>
        <FormField id="kb-search-language" label={t("search.language")}>
          <Select
            id="kb-search-language"
            value={language}
            style={{ minWidth: 160 }}
            options={[
              { value: "any", label: t("search.anyLanguage") },
              ...LANGUAGES.map((value) => ({ value, label: t(`languages.${value}`) })),
            ]}
            onChange={setLanguage}
          />
        </FormField>
        <div className="pf-kb-search-action">
          <Button
            type="primary"
            htmlType="submit"
            loading={search.isPending}
            disabled={query.trim() === ""}
          >
            {t("search.submit")}
          </Button>
        </div>
      </form>
      <ErrorNote message={search.isError ? kbErrorText(t, search.error, i18n.language) : null} />
      {search.data ? <Result result={search.data} /> : null}
    </Card>
  );
}
