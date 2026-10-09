import { useMutation } from "@tanstack/react-query";
import { Alert, Card, Input, List, Select, Space, Tag, Typography } from "antd";
import { useState } from "react";

import { kbTestSearch } from "../../api/generated/crm";
import { unwrap } from "../../api/http";
import { t } from "../../i18n/ru";

/** «Что найдёт бот на этот вопрос» — тот же поиск и порог, что у диалогового агента. */
export function TestSearch() {
  const [language, setLanguage] = useState<"ru" | "uz" | "en" | undefined>();
  const search = useMutation({
    mutationFn: async (query: string) =>
      unwrap(await kbTestSearch({ query, language: language ?? null })),
  });
  const result = search.data;
  return (
    <Card size="small" title={t.kb.testSearch}>
      <Space.Compact style={{ width: "100%" }}>
        <Select
          allowClear
          placeholder={t.kb.language}
          style={{ width: 90 }}
          value={language}
          options={["ru", "uz", "en"].map((v) => ({ value: v, label: v.toUpperCase() }))}
          onChange={(v?: "ru" | "uz" | "en") => {
            setLanguage(v);
          }}
        />
        <Input.Search
          enterButton
          placeholder={t.kb.query}
          loading={search.isPending}
          onSearch={(q) => {
            if (q.trim()) search.mutate(q.trim());
          }}
        />
      </Space.Compact>
      {result ? (
        <>
          <Alert
            style={{ margin: "12px 0" }}
            showIcon
            type={result.confident ? "success" : "warning"}
            message={`${result.confident ? t.kb.confident : t.kb.notConfident} · ${result.best_score?.toFixed(2) ?? "—"} / ${String(result.min_score)}`}
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
                      {t.kb.similarity} {hit.similarity?.toFixed(2) ?? "—"}
                    </Tag>
                  </Space>
                  <Typography.Paragraph
                    ellipsis={{ rows: 3, expandable: true }}
                    style={{ margin: 0 }}
                  >
                    {hit.content}
                  </Typography.Paragraph>
                </Space>
              </List.Item>
            )}
          />
        </>
      ) : null}
    </Card>
  );
}
