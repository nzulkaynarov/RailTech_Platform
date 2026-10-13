import { useMutation } from "@tanstack/react-query";
import { Alert, Card, Flex, Input, List, Select, Space, Tag, Typography } from "antd";
import { useState } from "react";

import { kbTestSearch } from "../../api/generated/crm";
import type { SearchResponse } from "../../api/generated/model";
import { SectionError } from "../../components/PageState";
import { languageOptions } from "../../domain/labels";
import { t } from "../../i18n/ru";

type Language = "ru" | "uz" | "en";

function Result({ result }: { result: SearchResponse }) {
  const score = `${result.best_score?.toFixed(2) ?? t.common.none} / ${String(result.min_score)}`;
  return (
    <>
      <Alert
        showIcon
        type={result.confident ? "success" : "warning"}
        message={`${result.confident ? t.kb.confident : t.kb.notConfident} · ${score}`}
      />
      <List
        size="small"
        dataSource={result.hits}
        renderItem={(hit) => (
          <List.Item>
            <Space direction="vertical" size={0}>
              <Space wrap>
                <Typography.Text strong>{hit.document_title}</Typography.Text>
                {hit.heading_path ? (
                  <Typography.Text type="secondary">{hit.heading_path}</Typography.Text>
                ) : null}
                <Tag>
                  {t.kb.similarity} {hit.similarity?.toFixed(2) ?? t.common.none}
                </Tag>
              </Space>
              <Typography.Paragraph ellipsis={{ rows: 3, expandable: true }} className="m-0">
                {hit.content}
              </Typography.Paragraph>
            </Space>
          </List.Item>
        )}
      />
    </>
  );
}

/** «Что найдёт бот на этот вопрос» — тот же поиск и порог, что у диалогового агента. */
export function TestSearch() {
  const [language, setLanguage] = useState<Language | undefined>();
  const [query, setQuery] = useState("");
  const search = useMutation({
    mutationFn: async (q: string) => await kbTestSearch({ query: q, language: language ?? null }),
  });
  const run = (q: string) => {
    setQuery(q.trim());
    if (q.trim()) search.mutate(q.trim());
  };
  return (
    <Card size="small" title={t.kb.testSearch}>
      <Flex vertical gap="small">
        <Typography.Text type="secondary">{t.kb.testSearchHint}</Typography.Text>
        <Flex wrap gap="small">
          <Select
            allowClear
            aria-label={t.kb.searchLanguage}
            placeholder={t.kb.searchLanguage}
            className="search-language"
            value={language}
            options={languageOptions()}
            onChange={(v?: Language) => {
              setLanguage(v);
            }}
          />
          <Input.Search
            className="compact-input"
            aria-label={t.kb.query}
            enterButton
            placeholder={t.kb.query}
            loading={search.isPending}
            onSearch={run}
          />
        </Flex>
        {search.isError ? (
          <SectionError
            error={search.error}
            onRetry={() => {
              run(query);
            }}
          />
        ) : null}
        {search.data ? <Result result={search.data} /> : null}
      </Flex>
    </Card>
  );
}
